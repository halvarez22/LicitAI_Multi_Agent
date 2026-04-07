import json
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from app.memory.repository import MemoryRepository
from app.models.session import Session
from app.models.document import Document
from app.models.agent_state import AgentState
from app.models.company import Company
from app.models.feedback import ExtractionFeedback
from app.models.outcome import LicitacionOutcome
from app.models.session_line_item import SessionLineItem
from app.models.base import Base
from sqlalchemy import delete

class PostgresMemoryAdapter(MemoryRepository):
    """Implementación de Memoria usando PostgreSQL + SQLAlchemy Async"""
    
    def __init__(self, connection_string: str, encryption_key: Optional[str] = None):
        # Convertir URI postgresql:// a postgresql+asyncpg://
        async_uri = connection_string.replace("postgresql://", "postgresql+asyncpg://") if connection_string else None
        self.connection_string = async_uri
        self.encryption_key = encryption_key
        self.engine = None
        self.async_session = None
        self._tables_created = False

    async def connect(self) -> bool:
        try:
            if not self.engine:
                self.engine = create_async_engine(self.connection_string, echo=False)
                self.async_session = sessionmaker(
                    self.engine, class_=AsyncSession, expire_on_commit=False
                )
                
                # Crear las tablas solo una vez en el ciclo de vida del adaptador
                if not self._tables_created:
                    async with self.engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                    self._tables_created = True
            return True
        except Exception as e:
            print(f"Error conectando a Postgres: {e}")
            return False

    async def disconnect(self) -> bool:
        # No desconectamos para mantener el pool caliente en el Singleton.
        return True

    async def save_session(self, session_id: str, data: Dict) -> bool:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Session).filter_by(id=session_id))
            db_obj = result.scalars().first()
            if not db_obj:
                db_obj = Session(id=session_id, user_id=data.get('user_id', 'system'))
            
            db_obj.state_data = data
            db_session.add(db_obj)
            await db_session.commit()
            return True

    async def get_session(self, session_id: str) -> Optional[Dict]:
         async with self.async_session() as db_session:
            result = await db_session.execute(select(Session).filter_by(id=session_id))
            db_obj = result.scalars().first()
            return db_obj.state_data if db_obj else None

    async def save_document(self, doc_id: str, session_id: str, content: Dict, metadata: Dict) -> bool:
        async with self.async_session() as db_session:
            # Buscar si el documento ya existe para hacer UPSERT
            result = await db_session.execute(select(Document).filter_by(id=doc_id))
            doc = result.scalars().first()
            
            if not doc:
                doc = Document(id=doc_id)
                db_session.add(doc)
            
            doc.session_id = session_id
            doc.filename = metadata.get("filename", "unknown")
            doc.content = content
            doc.metadata_info = metadata
            doc.document_type = metadata.get("type", "unknown")
            
            await db_session.commit()
            return True

    async def get_documents(self, session_id: str) -> List[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Document).filter_by(session_id=session_id))
            docs = result.scalars().all()
            return [{"id": d.id, "content": d.content, "metadata": d.metadata_info} for d in docs]

    async def get_document(self, doc_id: str) -> Optional[Dict]:
        """Recupera un documento específico por su UUID."""
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Document).filter_by(id=doc_id))
            d = result.scalars().first()
            if d:
                return {"id": d.id, "content": d.content, "metadata": d.metadata_info}
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """Elimina un documento por su UUID."""
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Document).filter_by(id=doc_id))
            doc = result.scalars().first()
            if doc:
                await db_session.delete(doc)
                await db_session.commit()
                return True
        return False

    async def save_conversation(self, session_id: str, messages: List[Dict]) -> bool:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Session).filter_by(id=session_id))
            db_obj = result.scalars().first()
            if db_obj:
                # Merge old and new messages or overwrite as needed
                db_obj.conversation_history = messages
                db_session.add(db_obj)
                await db_session.commit()
                return True
        return False

    async def get_conversation(self, session_id: str, limit: int = 50) -> List[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Session).filter_by(id=session_id))
            db_obj = result.scalars().first()
            if db_obj and db_obj.conversation_history:
                return db_obj.conversation_history[-limit:]
            return []

    async def save_agent_state(self, agent_id: str, session_id: str, state: Dict) -> bool:
        async with self.async_session() as db_session:
            # Upsert
            result = await db_session.execute(
                select(AgentState).filter_by(session_id=session_id, agent_id=agent_id)
            )
            db_obj = result.scalars().first()
            
            if not db_obj:
                db_obj = AgentState(
                    id=str(uuid.uuid4()), 
                    session_id=session_id, 
                    agent_id=agent_id
                )
            
            db_obj.state_data = state
            db_session.add(db_obj)
            await db_session.commit()
            return True

    async def get_agent_state(self, agent_id: str, session_id: str) -> Optional[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(
                select(AgentState).filter_by(session_id=session_id, agent_id=agent_id)
            )
            db_obj = result.scalars().first()
            return db_obj.state_data if db_obj else None

    async def delete_session(self, session_id: str) -> bool:
        async with self.async_session() as db_session:
            # 1. Limpieza manual de tablas con FK (por si el CASCADE no está aplicado en BD)
            # Borrar outcomes
            await db_session.execute(delete(LicitacionOutcome).where(LicitacionOutcome.session_id == session_id))
            
            # Borrar feedback
            await db_session.execute(delete(ExtractionFeedback).where(ExtractionFeedback.session_id == session_id))
            
            # 2. Localizar y borrar la sesión principal
            result = await db_session.execute(select(Session).filter_by(id=session_id))
            db_obj = result.scalars().first()
            if db_obj:
                await db_session.delete(db_obj)
                await db_session.commit()
                return True
        return False

    async def backup(self, destination: str) -> bool:
        # Not implemented yet, logic to pg_dump
        return False

    async def health_check(self) -> Dict:
        try:
             async with self.engine.connect() as conn:
                 await conn.execute(select(1))
             return {"status": "ok", "backend": "postgres"}
        except Exception as e:
             return {"status": "error", "error": str(e)}

    async def list_sessions(self) -> List[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Session).order_by(Session.updated_at.desc()))
            sessions = result.scalars().all()
            out = []
            for s in sessions:
                sd = s.state_data if isinstance(s.state_data, dict) else {}
                # Nombre real guardado al crear la licitación (coherente con carpetas /data/outputs si aún está en estado).
                # Si el orquestador reemplazó el estado y ya no hay "name", mostramos el id (misma clave que usan los agentes como carpeta).
                display_name = sd.get("name") or s.id.replace("_", " ").title()
                out.append(
                    {
                        "id": s.id,
                        "user_id": s.user_id,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                        "name": display_name,
                    }
                )
            return out

    async def save_company(self, company_id: str, data: Dict) -> bool:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Company).filter_by(id=company_id))
            db_obj = result.scalars().first()
            if not db_obj:
                db_obj = Company(
                    id=company_id,
                    name=data.get('name', 'Unknown'),
                    type=data.get('type', 'moral')
                )
            else:
                db_obj.name = data.get('name', db_obj.name)
                db_obj.type = data.get('type', db_obj.type)
            
            db_obj.docs = data.get('docs') or data.get('docs_metadata') or db_obj.docs or {}
            db_obj.master_profile = data.get('master_profile', db_obj.master_profile)
            
            # Hito 1: Gestión de catálogo (no sobrescribir si no viene en el payload)
            if 'catalog' in data:
                db_obj.catalog = data.get('catalog') if data.get('catalog') is not None else []
            
            db_session.add(db_obj)
            await db_session.commit()
            return True

    async def get_companies(self) -> List[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Company).order_by(Company.updated_at.desc()))
            companies = result.scalars().all()
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "type": c.type,
                    "docs": c.docs,
                    "master_profile": c.master_profile,
                    "catalog": c.catalog if c.catalog is not None else [],
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None
                }
                for c in companies
            ]

    async def get_company(self, company_id: str) -> Optional[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Company).filter_by(id=company_id))
            c = result.scalars().first()
            if c:
                return {
                    "id": c.id,
                    "name": c.name,
                    "type": c.type,
                    "docs": c.docs,
                    "master_profile": c.master_profile,
                    "catalog": c.catalog if c.catalog is not None else [],
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None
                }
            return None

    async def delete_company(self, company_id: str) -> bool:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(Company).filter_by(id=company_id))
            db_obj = result.scalars().first()
            if db_obj:
                await db_session.delete(db_obj)
                await db_session.commit()
                return True
        return False

    async def replace_line_items_for_document(
        self, session_id: str, document_id: str, line_items: List[Dict]
    ) -> bool:
        async with self.async_session() as db_session:
            await db_session.execute(
                delete(SessionLineItem).where(SessionLineItem.document_id == document_id)
            )
            for row in line_items:
                li = SessionLineItem(
                    id=str(row.get("id") or uuid.uuid4()),
                    session_id=session_id,
                    document_id=document_id,
                    source_type=row.get("source_type") or "document_tabular",
                    concepto_raw=row["concepto_raw"],
                    concepto_norm=row["concepto_norm"],
                    unidad=row.get("unidad"),
                    cantidad=row.get("cantidad"),
                    precio_unitario=float(row["precio_unitario"]),
                    moneda=row.get("moneda") or "MXN",
                    sheet_name=row.get("sheet_name"),
                    row_index=row.get("row_index"),
                    extra=row.get("extra") if isinstance(row.get("extra"), dict) else {},
                    extraction_version=str(row.get("extraction_version") or "1"),
                )
                db_session.add(li)
            await db_session.commit()
        return True

    async def get_line_items_for_session(self, session_id: str) -> List[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(
                select(SessionLineItem)
                .where(SessionLineItem.session_id == session_id)
                .order_by(SessionLineItem.sheet_name, SessionLineItem.row_index)
            )
            rows = result.scalars().all()
            return [
                {
                    "id": x.id,
                    "document_id": x.document_id,
                    "source_type": x.source_type,
                    "concepto_raw": x.concepto_raw,
                    "concepto_norm": x.concepto_norm,
                    "unidad": x.unidad,
                    "cantidad": x.cantidad,
                    "precio_unitario": x.precio_unitario,
                    "moneda": x.moneda,
                    "sheet_name": x.sheet_name,
                    "row_index": x.row_index,
                    "extra": x.extra or {},
                    "extraction_version": x.extraction_version,
                }
                for x in rows
            ]

    async def save_feedback(self, data: Dict) -> bool:
        async with self.async_session() as db_session:
            db_obj = ExtractionFeedback(
                id=uuid.uuid4(),
                session_id=data.get('session_id'),
                company_id=data.get('company_id'),
                agent_id=data.get('agent_id'),
                pipeline_stage=data.get('pipeline_stage'),
                entity_type=data.get('entity_type'),
                entity_ref=data.get('entity_ref'),
                field_path=data.get('field_path'),
                extracted_value=data.get('extracted_value'),
                user_correction=data.get('user_correction'),
                was_correct=data.get('was_correct'),
                correction_type=data.get('correction_type'),
                user_comment=data.get('user_comment'),
                prompt_version=data.get('prompt_version'),
                agent_version=data.get('agent_version')
            )
            db_session.add(db_obj)
            await db_session.commit()
            return True

    async def get_feedback(self, session_id: str = None, company_id: str = None) -> List[Dict]:
        async with self.async_session() as db_session:
            query = select(ExtractionFeedback)
            if session_id:
                query = query.filter_by(session_id=session_id)
            if company_id:
                query = query.filter_by(company_id=company_id)
            
            query = query.order_by(ExtractionFeedback.created_at.desc())
            result = await db_session.execute(query)
            items = result.scalars().all()
            
            return [
                {
                    "id": str(i.id),
                    "session_id": i.session_id,
                    "company_id": i.company_id,
                    "agent_id": i.agent_id,
                    "pipeline_stage": i.pipeline_stage,
                    "entity_type": i.entity_type,
                    "entity_ref": i.entity_ref,
                    "field_path": i.field_path,
                    "extracted_value": i.extracted_value,
                    "user_correction": i.user_correction,
                    "was_correct": i.was_correct,
                    "correction_type": i.correction_type,
                    "user_comment": i.user_comment,
                    "created_at": i.created_at.isoformat() if i.created_at else None
                }
                for i in items
            ]

    async def save_outcome(self, session_id: str, data: Dict) -> bool:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(LicitacionOutcome).filter_by(session_id=session_id))
            obj = result.scalars().first()
            
            if not obj:
                obj = LicitacionOutcome(id=uuid.uuid4(), session_id=session_id)
                db_session.add(obj)
            
            obj.company_id = data.get('company_id', obj.company_id)
            obj.sector = data.get('sector', obj.sector)
            obj.tipo_licitacion = data.get('tipo_licitacion', obj.tipo_licitacion)
            obj.resultado = data.get('resultado', obj.resultado)
            obj.notas = data.get('notas', obj.notas)
            obj.requirements_fingerprint = data.get('fingerprint', obj.requirements_fingerprint)
            
            await db_session.commit()
            return True

    async def get_outcome(self, session_id: str) -> Optional[Dict]:
        async with self.async_session() as db_session:
            result = await db_session.execute(select(LicitacionOutcome).filter_by(session_id=session_id))
            obj = result.scalars().first()
            if obj:
                return {
                    "id": str(obj.id),
                    "session_id": obj.session_id,
                    "company_id": obj.company_id,
                    "sector": obj.sector,
                    "tipo_licitacion": obj.tipo_licitacion,
                    "resultado": obj.resultado,
                    "notas": obj.notas,
                    "fingerprint": obj.requirements_fingerprint
                }
            return None
