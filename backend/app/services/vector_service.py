import chromadb
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple

class VectorDbServiceClient:
    """Cliente para interactuar con ChromaDB"""

    def __init__(self):
        vector_url = os.getenv("VECTOR_DB_URL", "http://vector-db:8000")
        # vector-db en docker network resolve a 172.x.x.x
        host = vector_url.replace("http://", "").split(":")[0]
        port = int(vector_url.split(":")[-1])
        
        try:
            self.client = chromadb.HttpClient(host=host, port=port)
        except Exception as e:
            print(f"ChromaDB connect error: {e}")
            self.client = None

    def _sanitize_name(self, collection_name: str) -> str:
        """Sanitiza el nombre para que sea compatible con ChromaDB (longitud 3-63, alfanumérico, etc)"""
        import re
        name = collection_name.lower()
        # Reemplazar todo lo que no sea alfanumérico, guión o guión bajo por nada
        name = re.sub(r'[^a-z0-9_-]', '', name)
        # 2. Asegurar que empiece y termine con letra o número
        name = re.sub(r'^[^a-z0-9]+', '', name)
        name = re.sub(r'[^a-z0-9]+$', '', name)
        # 3. Handle longitud y mínimos
        if not name or len(name) < 3:
            name = f"session_{name}" if name else "session_default"
        safe_name = name[:63]
        return safe_name

    def _pick_vector_collection(self, session_id: str) -> Tuple[Optional[Any], bool]:
        """
        Resuelve la colección Chroma donde hay embeddings de esta sesión.

        Returns:
            (colección, require_session_where): si require_session_where es True,
            las consultas deben filtrar ``where={"session_id": session_id}`` porque
            la colección puede agrupar varias sesiones (índice legado o nombre distinto).
        """
        if not self.client:
            return None, False
        safe_name = self._sanitize_name(session_id)
        try:
            primary = self.client.get_or_create_collection(name=safe_name)
            peek = primary.get(limit=1)
            if peek.get("ids"):
                return primary, False
        except Exception as e:
            print(f"[VectorDB] _pick_vector_collection primary peek: {e}")
            try:
                primary = self.client.get_or_create_collection(name=safe_name)
            except Exception:
                return None, False

        for coll in self.client.list_collections():
            if coll.name == safe_name:
                continue
            try:
                other = self.client.get_collection(coll.name)
                hit = other.get(where={"session_id": session_id}, limit=1)
                if hit.get("ids"):
                    print(
                        f"[VectorDB] RAG: usando colección '{coll.name}' "
                        f"(metadato session_id; la colección '{safe_name}' está vacía o ausente)"
                    )
                    return other, True
            except Exception:
                continue
        return primary, False

    def get_or_create_collection(self, collection_name: str):
        if not self.client:
           return None
        safe_name = self._sanitize_name(collection_name)
        print(f"DEBUG: VectorDB get_or_create collection -> '{safe_name}'")
        try:
            return self.client.get_or_create_collection(name=safe_name)
        except Exception as e:
            print(f"ERROR: ChromaDB failed to get/create collection '{safe_name}': {e}")
            raise e

    def add_texts(self, session_id: str, texts: List[str], metadatas: List[Dict[str, Any]]):
        """Añade fragmentos de texto a la colección de la licitación específica"""
        collection = self.get_or_create_collection(session_id)
        if not collection:
            return False
            
        ids = [str(uuid.uuid4()) for _ in texts]
        collection.add(
            documents=texts,
            metadatas=metadatas,
            ids=ids
        )
        return True

    def query_texts(self, session_id: str, query: str, n_results: int = 5) -> Dict[str, Any]:
        """Busca el contexto más similar por coseno en RAG"""
        collection, need_session_where = self._pick_vector_collection(session_id)
        if not collection:
            return {"error": "Conexión a base vector fallida", "documents": [], "metadatas": [], "distances": []}

        qargs: Dict[str, Any] = {"query_texts": [query], "n_results": n_results}
        if need_session_where:
            qargs["where"] = {"session_id": session_id}
        try:
            results = collection.query(**qargs)
        except Exception as e:
            print(f"ERROR query_texts (where={need_session_where}): {e}")
            return {"documents": [], "metadatas": [], "distances": []}
        return {
            "documents": results.get("documents", [[]])[0],
            "metadatas": results.get("metadatas", [[]])[0],
            "distances": results.get("distances", [[]])[0]
        }

    def get_full_pages(self, session_id: str, source: str, pages: List[int]) -> str:
        """Recupera el contenido íntegro de una lista de páginas en orden."""
        collection, need_session_where = self._pick_vector_collection(session_id)
        if not collection:
            return ""

        all_content = []
        for pg in sorted(pages):
            conds: List[Dict[str, Any]] = [{"source": source}, {"page": str(pg)}]
            if need_session_where:
                conds.insert(0, {"session_id": session_id})
            res = collection.get(where={"$and": conds})
            if res and res["documents"]:
                all_content.append(f"--- PÁGINA {pg} ---\n" + "\n".join(res["documents"]))

        return "\n".join(all_content)

    def fetch_page_documents(self, session_id: str, source: str, page: Any) -> List[str]:
        """
        Devuelve los fragmentos almacenados para una página concreta (int o str).
        Usa la misma resolución de colección que query_texts (incl. cross-collection).
        """
        collection, need_session_where = self._pick_vector_collection(session_id)
        if not collection:
            return []
        variants = [page]
        if isinstance(page, str) and page.isdigit():
            variants.append(int(page))
        elif isinstance(page, int):
            variants.append(str(page))
        for pv in variants:
            conds = [{"source": source}]
            if need_session_where:
                conds.insert(0, {"session_id": session_id})
            conds.append({"page": pv})
            res = collection.get(where={"$and": conds})
            if res and res.get("documents"):
                return list(res["documents"])
        return []

    def query_by_page_range(self, session_id: str, source: str, start_page: int, end_page: int) -> str:
        """Barrido secuencial de un rango de páginas."""
        pages = list(range(start_page, end_page + 1))
        return self.get_full_pages(session_id, source, pages)

    def get_sources(self, session_id: str) -> List[str]:
        """Devuelve la lista de nombres de archivo únicos indexados en la colección.
        Si la colección propia está vacía, busca en todas las colecciones usando session_id en metadatos."""
        collection = self.get_or_create_collection(session_id)
        if not collection:
            return []
        try:
            all_metas = collection.get()["metadatas"]
            sources = list({m.get("source", "") for m in all_metas if m.get("source")})
            
            # Si la colección propia está vacía, buscar cross-collection por session_id en metadatos
            if not sources and self.client:
                print(f"[VectorDB] Colección propia vacía, buscando cross-collection para session_id={session_id}")
                for coll in self.client.list_collections():
                    try:
                        other_col = self.client.get_collection(coll.name)
                        results = other_col.get(where={"session_id": session_id})
                        if results["metadatas"]:
                            cross_sources = list({m.get("source", "") for m in results["metadatas"] if m.get("source")})
                            if cross_sources:
                                print(f"[VectorDB] Encontrado en colección '{coll.name}': {cross_sources}")
                                # Guardamos el nombre de colección real para reutilizarlo
                                self._resolved_collection = coll.name
                                return cross_sources
                    except Exception:
                        continue
            return sources
        except Exception as e:
            print(f"ERROR get_sources: {e}")
            return []

    def query_texts_filtered(self, session_id: str, query: str, source_filter: str, n_results: int = 20) -> Dict[str, Any]:
        """Búsqueda semántica restringida a un documento específico (misma resolución de colección que query_texts)."""
        resolved = getattr(self, "_resolved_collection", None)
        if resolved and self.client:
            try:
                collection = self.client.get_collection(resolved)
                print(f"[VectorDB] Usando colección resuelta (get_sources): {resolved}")
                results = collection.query(
                    query_texts=[query],
                    n_results=n_results,
                    where={"source": source_filter},
                )
                return {
                    "documents": results.get("documents", [[]])[0],
                    "metadatas": results.get("metadatas", [[]])[0],
                    "distances": results.get("distances", [[]])[0],
                }
            except Exception as e:
                print(f"[VectorDB] Fallo colección resuelta, fallback _pick: {e}")

        collection, need_session_where = self._pick_vector_collection(session_id)
        if not collection:
            return {"error": "Conexión a base vector fallida", "documents": [], "metadatas": [], "distances": []}

        if need_session_where:
            where_clause: Dict[str, Any] = {"$and": [{"session_id": session_id}, {"source": source_filter}]}
        else:
            where_clause = {"source": source_filter}

        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_clause,
            )
            return {
                "documents": results.get("documents", [[]])[0],
                "metadatas": results.get("metadatas", [[]])[0],
                "distances": results.get("distances", [[]])[0],
            }
        except Exception as e:
            print(f"ERROR query_texts_filtered: {e}")
            return self.query_texts(session_id, query, n_results)

    def delete_by_doc_id(self, session_id: str, doc_id: str) -> bool:
        """Elimina todos los fragmentos asociados a un doc_id en la colección de la sesión."""
        collection = self.get_or_create_collection(session_id)
        if not collection:
            return False
        try:
            # ChromaDB permite borrar por metadatos
            collection.delete(where={"doc_id": doc_id})
            print(f"DEBUG: VectorDB eliminó correctamente doc_id={doc_id} de sesión={session_id}")
            return True
        except Exception as e:
            print(f"ERROR delete_by_doc_id: {e}")
            return False

    def delete_collection(self, session_id: str) -> bool:
        """Elimina físicamente la colección de ChromaDB al borrar la licitación."""
        if not self.client:
            return False
        
        safe_name = self._sanitize_name(session_id)
        try:
            # En ChromaDB 0.4.x+, el borrado correcto es por nombre
            self.client.delete_collection(name=safe_name)
            print(f"DEBUG: VectorDB eliminó físicamente la colección '{safe_name}'")
            return True
        except Exception as e:
            # El error es común si la colección no existía: lo silenciamos sanamente
            print(f"INFO: No se pudo borrar la colección '{safe_name}' (posiblemente inexistente): {e}")
            return False
