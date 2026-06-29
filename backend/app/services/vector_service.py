import chromadb
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple

class VectorDbServiceClient:
    """Cliente para interactuar con ChromaDB"""

    def __init__(self):
        vector_url = os.getenv("VECTOR_DB_URL", "http://vector-db:8000")
        # En host (fuera de Docker), "vector-db" no resuelve; usar localhost publicado.
        if not os.path.exists("/.dockerenv") and "vector-db" in vector_url:
            vector_url = vector_url.replace("vector-db", "127.0.0.1")
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
        if not collection_name:
            return "session_default"
        # Normalización universal para evitar desalineación (strips, lower, guiones)
        name = collection_name.strip().lower().replace("-", "_")
        # Reemplazar todo lo que no sea alfanumérico o guión bajo
        name = re.sub(r'[^a-z0-9_]', '', name)
        # Asegurar que empiece y termine con letra o número
        name = re.sub(r'^[^a-z0-9]+', '', name)
        name = re.sub(r'[^a-z0-9]+$', '', name)
        if not name or len(name) < 3:
            name = f"sess_{name}" if name else "session_default"
        return name[:63]

    def _pick_vector_collection(self, session_id: str) -> Tuple[Optional[Any], bool]:
        """
        Resuelve la colección Chroma donde hay embeddings de esta sesión.
        
        CORREGIDO: Eliminado cross-collection fallback para garantizar aislamiento de sesiones.
        Ahora solo retorna la colección de la sesión especificada, nunca busca en otras colecciones.

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

        # CORRECCIÓN: Eliminado cross-collection fallback
        # ANTES: Buscaba en otras colecciones si la principal estaba vacía
        # AHORA: Retorna la colección principal vacía (garantiza aislamiento)
        # 
        # El siguiente código fue eliminado para prevenir mezcla de datos:
        # for coll in self.client.list_collections():
        #     if coll.name == safe_name:
        #         continue
        #     try:
        #         other = self.client.get_collection(coll.name)
        #         hit = other.get(where={"session_id": session_id}, limit=1)
        #         if hit.get("ids"):
        #             print(f"[VectorDB] RAG: usando colección '{coll.name}' ...")
        #             return other, True
        #     except Exception:
        #         continue
        
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
        """Añade fragmentos de texto a la colección de la licitación específica."""
        clean_id = self._sanitize_name(session_id)
        collection = self.get_or_create_collection(clean_id)
        if not collection:
            return False
        
        for i, metadata in enumerate(metadatas):
            metadata["session_id"] = clean_id
            
        ids = [str(uuid.uuid4()) for _ in texts]
        collection.add(
            documents=texts,
            metadatas=metadatas,
            ids=ids
        )
        return True

    def query_texts(self, session_id: str, query: str, n_results: int = 5) -> Dict[str, Any]:
        """Busca el contexto más similar por coseno en RAG."""
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return {"documents": [], "metadatas": [], "distances": []}

        qargs: Dict[str, Any] = {
            "query_texts": [query], 
            "n_results": n_results,
            "where": {"session_id": clean_id}
        }

        # REGLA UNIVERSAL DE BÚSQUEDA HÍBRIDA v3 (Hito 10.1 - Precisión Quirúrgica)
        # Implementa COEXISTENCIA ($and) para reducir el ruido de palabras comunes.
        
        target_filters = []
        q_lower = query.lower()
        
        # Concepto 1: Junta de Aclaraciones
        if "junta" in q_lower or "aclaraci" in q_lower:
            # Buscamos que contenga 'junta' Y algo parecido a 'aclaracion'
            target_filters.append({"$or": [{"$contains": "junta"}, {"$contains": "Junta"}, {"$contains": "JUNTA"}]})
            target_filters.append({"$or": [{"$contains": "aclaraci"}, {"$contains": "Aclaraci"}, {"$contains": "ACLARACI"}]})
            
        # Concepto 2: Visita a Instalaciones
        if "visita" in q_lower:
            target_filters.append({"$or": [{"$contains": "visita"}, {"$contains": "Visita"}, {"$contains": "VISITA"}]})
            if "instalaci" in q_lower or "campo" in q_lower or "sitio" in q_lower:
                target_filters.append({"$or": [
                    {"$contains": "instalaci"}, {"$contains": "Instalaci"}, {"$contains": "INSTALACI"},
                    {"$contains": "campo"}, {"$contains": "Campo"}, {"$contains": "CAMPO"},
                    {"$contains": "sitio"}, {"$contains": "Sitio"}, {"$contains": "SITIO"}
                ]})

        # Concepto 3: Propuesta / Precios
        if "propuesta" in q_lower or "precio" in q_lower or "economica" in q_lower:
            target_filters.append({"$or": [
                {"$contains": "propuesta"}, {"$contains": "Propuesta"}, {"$contains": "PROPUESTA"},
                {"$contains": "precio"}, {"$contains": "Precio"}, {"$contains": "PRECIO"},
                {"$contains": "economica"}, {"$contains": "Economica"}, {"$contains": "ECONOMICA"}
            ]})

        # Concepto 4: Póliza de Seguro / Responsabilidad Civil / Garantías / Daños a Terceros
        if (
            "póliza" in q_lower
            or "poliza" in q_lower
            or "seguro" in q_lower
            or "fianza" in q_lower
            or "garantía" in q_lower
            or "garantia" in q_lower
            or "garantias" in q_lower
            or "responsabilidad" in q_lower
            or "daños a terceros" in q_lower
            or "danos a terceros" in q_lower
        ):
            target_filters.append({"$or": [
                {"$contains": "póliza"}, {"$contains": "poliza"}, {"$contains": "Póliza"}, {"$contains": "Poliza"}, {"$contains": "PÓLIZA"}, {"$contains": "POLIZA"},
                {"$contains": "seguro"}, {"$contains": "Seguro"}, {"$contains": "SEGURO"},
                {"$contains": "fianza"}, {"$contains": "Fianza"}, {"$contains": "FIANZA"},
                {"$contains": "garantía"}, {"$contains": "Garantía"}, {"$contains": "GARANTÍA"},
                {"$contains": "garantia"}, {"$contains": "Garantia"}, {"$contains": "GARANTIA"},
                {"$contains": "responsabilidad"}, {"$contains": "Responsabilidad"}, {"$contains": "RESPONSABILIDAD"},
                {"$contains": "terceros"}, {"$contains": "Terceros"}, {"$contains": "TERCEROS"}
            ]})
            # Si se pregunta específicamente por responsabilidad o daños a terceros, forzamos a que contenga esta combinación exacta
            if "responsabilidad" in q_lower or "civil" in q_lower or "tercero" in q_lower or "daño" in q_lower:
                target_filters.append({"$or": [
                    {"$contains": "responsabilidad civil"}, {"$contains": "Responsabilidad Civil"}, {"$contains": "RESPONSABILIDAD CIVIL"},
                    {"$contains": "daños a terceros"}, {"$contains": "Daños a Terceros"}, {"$contains": "DAÑOS A TERCEROS"},
                    {"$contains": "responsabilidad civil por daños a terceros"}
                ]})

        if target_filters:
            # Si tenemos múltiples criterios, usamos $and para obligar a que coexistan
            if len(target_filters) > 1:
                qargs["where_document"] = {"$and": target_filters}
            else:
                qargs["where_document"] = target_filters[0]
            
            print(f"[*] [HybridSearch-v3] Filtro de coexistencia aplicado (Filtros: {len(target_filters)})")
        
        try:
            print(f"[VectorDB] Querying session '{clean_id}' (n={n_results})...")
            results = collection.query(**qargs)
        except Exception as e:
            print(f"ERROR query_texts: {e}")
            return {"documents": [], "metadatas": [], "distances": []}
        
        documents = results.get("documents", [[]])
        metadatas = results.get("metadatas", [[]])
        distances = results.get("distances", [[]])
        
        # Validación post-búsqueda: Filtro de seguridad redundante
        final_docs = []
        final_metas = []
        final_dists = []
        
        if documents and len(documents) > 0:
            for doc, meta, dist in zip(documents[0], metadatas[0], distances[0]):
                if meta.get("session_id") == clean_id:
                    final_docs.append(doc)
                    final_metas.append(meta)
                    final_dists.append(dist)
                else:
                    print(f"⚠️ [VectorDB] BLOQUEADO: Intento de fuga de datos de sesión '{meta.get('session_id')}' detectado en query de '{clean_id}'")
        
        return {
            "documents": final_docs,
            "metadatas": final_metas,
            "distances": final_dists
        }

    def get_full_pages(self, session_id: str, source: str, pages: List[int]) -> str:
        """Recupera el contenido íntegro de una lista de páginas."""
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return ""

        all_content = []
        for pg in sorted(pages):
            conds: List[Dict[str, Any]] = [
                {"session_id": clean_id},
                {"source": source},
                {"page": str(pg)}
            ]
            res = collection.get(where={"$and": conds})
            if res and res["documents"]:
                all_content.append(f"--- PÁGINA {pg} ---\n" + "\n".join(res["documents"]))

        return "\n".join(all_content)

    def fetch_page_documents(self, session_id: str, source: str, page: Any) -> List[str]:
        """Devuelve los fragmentos almacenados para una página concreta."""
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return []
        variants = [page]
        if isinstance(page, str) and page.isdigit():
            variants.append(int(page))
        elif isinstance(page, int):
            variants.append(str(page))
        for pv in variants:
            conds = [
                {"session_id": clean_id},
                {"source": source},
                {"page": pv}
            ]
            res = collection.get(where={"$and": conds})
            if res and res.get("documents"):
                return list(res["documents"])
        return []

    def get_full_document_text(self, session_id: str, source: str) -> str:
        """Recupera el contenido íntegro de un documento específico."""
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return ""
        
        try:
            res = collection.get(
                where={"$and": [{"session_id": clean_id}, {"source": source}]}
            )
            if not res or not res["documents"]:
                return ""
            
            # Reconstrucción inteligente por página y orden
            docs = res["documents"]
            metas = res["metadatas"]
            
            # Agrupar y ordenar para asegurar integridad estructural
            combined = sorted(
                zip(docs, metas), 
                key=lambda x: (int(x[1].get("page", 0)), int(x[1].get("chunk_index", 0)))
            )
            
            reconstructed = []
            current_page = -1
            for doc, meta in combined:
                pg = int(meta.get("page", 0))
                if pg != current_page:
                    reconstructed.append(f"\n--- PÁGINA {pg} ({source}) ---\n")
                    current_page = pg
                reconstructed.append(doc)
            
            return "\n".join(reconstructed)
        except Exception as e:
            print(f"ERROR get_full_document_text: {e}")
            return ""

    def query_by_page_range(self, session_id: str, source: str, start_page: int, end_page: int) -> str:
        """Barrido secuencial de un rango de páginas."""
        pages = list(range(start_page, end_page + 1))
        return self.get_full_pages(session_id, source, pages)

    def get_sources(self, session_id: str) -> List[str]:
        """Devuelve la lista de nombres de archivo únicos indexados."""
        clean_id = self._sanitize_name(session_id)
        collection = self.get_or_create_collection(clean_id)
        if not collection:
            return []
        try:
            print(f"[VectorDB] get_sources for session '{clean_id}'")
            res = collection.get(include=["metadatas"], limit=500)
            all_metas = res.get("metadatas", [])
            sources = list({m.get("source", "") for m in all_metas if m.get("source")})
            
            # CORRECCIÓN: Eliminado cross-collection search
            # ANTES: Si la colección propia estaba vacía, buscaba en otras colecciones
            # AHORA: Solo retorna fuentes de la colección de la sesión actual
            #
            # El siguiente código fue eliminado para prevenir mezcla de datos:
            # if not sources and self.client:
            #     print(f"[VectorDB] Colección propia vacía, buscando cross-collection...")
            #     for coll in self.client.list_collections():
            #         ...
            
            return sources
        except Exception as e:
            print(f"ERROR get_sources: {e}")
            return []

    def scan_session_chunks(
        self,
        session_id: str,
        *,
        source_filter: Optional[str] = None,
        max_chunks: int = 4000,
    ) -> List[tuple[str, Dict[str, Any]]]:
        """Barrido determinista de chunks indexados (fallback cuando falla la búsqueda semántica)."""
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return []
        try:
            if source_filter:
                where: Dict[str, Any] = {
                    "$and": [
                        {"session_id": clean_id},
                        {"source": source_filter},
                    ]
                }
            else:
                where = {"session_id": clean_id}
            res = collection.get(
                where=where,
                include=["documents", "metadatas"],
                limit=max_chunks,
            )
            docs = list(res.get("documents") or [])
            metas = list(res.get("metadatas") or [])
            return [
                (str(doc or ""), meta if isinstance(meta, dict) else {})
                for doc, meta in zip(docs, metas)
                if doc
            ]
        except Exception as e:
            print(f"ERROR scan_session_chunks: {e}")
            return []

    def count_session_chunks(self, session_id: str) -> int:
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return 0
        try:
            res = collection.get(where={"session_id": clean_id}, include=[], limit=1)
            ids = res.get("ids") or []
            if not ids:
                return 0
            full = collection.get(where={"session_id": clean_id}, include=["metadatas"])
            return len(full.get("ids") or [])
        except Exception:
            return 0

    def query_texts_filtered(self, session_id: str, query: str, source_filter: str, n_results: int = 20) -> Dict[str, Any]:
        """Búsqueda semántica restringida a un documento específico."""
        clean_id = self._sanitize_name(session_id)
        collection, _ = self._pick_vector_collection(clean_id)
        if not collection:
            return {"documents": [], "metadatas": [], "distances": []}

        where_clause: Dict[str, Any] = {
            "$and": [
                {"session_id": clean_id},
                {"source": source_filter}
            ]
        }

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

    def warmup_embedding_runtime(self) -> bool:
        """
        Precarga el runtime ONNX de embeddings de Chroma (MiniLM-L6-v2) en arranque.

        La primera ``query_texts`` en un contenedor nuevo puede descargar ~80 MB y
        bloquear el worker varios minutos; conviene hacerlo al startup, no en el chat.
        """
        if not self.client:
            return False
        try:
            coll = self.client.get_or_create_collection(name="licitai_embedding_warmup")
            coll.query(query_texts=["licitai embedding warmup"], n_results=1)
            print("[VectorDB] warmup_embedding_runtime: OK")
            return True
        except Exception as e:
            print(f"[VectorDB] warmup_embedding_runtime failed: {e}")
            return False
