
import asyncio
import os
import sys
import json
from dotenv import load_dotenv

# Add the backend to sys.path
backend_path = os.path.join(os.getcwd(), "backend")
load_dotenv(os.path.join(backend_path, ".env"))
sys.path.append(backend_path)

from app.config.settings import settings
from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
from app.models.normative_policy import NormativePolicy
from sqlalchemy.future import select

async def seed():
    print("--- SEEDING NORMATIVE POLICIES ---")
    adapter = PostgresMemoryAdapter(settings.DATABASE_URL)
    await adapter.connect()
    
    async with adapter.async_session() as session:
        # Definición de la matriz actual (Migración de tender_router_service.py)
        
        # Alias Map Universal
        universal_aliases = {
            "LEG_ACTA_CONSTITUTIVA": ["acta constitutiva", "constitucion de la sociedad", "escritura constitutiva"],
            "LEG_PODER_NOTARIAL": ["poder notarial", "apoderado legal", "facultades de representacion"],
            "LEG_IDENTIDAD_CANDIDATO": [
                "anexo iii", "anexo 3", "anexo ii", "anexo 2", "datos generales", 
                "datos generales del licitante", "identidad del licitante", "identificacion oficial"
            ],
            "FIS_SAT_OPINION": ["opinion de cumplimiento sat", "opinion sat", "32-d", "articulo 32-d", "cumplimiento fiscal federal"],
            "FIS_ESTATAL_OPINION": ["opinion de cumplimiento estatal", "opinion estatal", "cadpe", "secretaria de finanzas"],
            "DECL_MIPYME": ["mipyme", "estratificacion", "micro pequena mediana", "dc-03", "dc-04"],
            "DECL_INTEGRIDAD": ["declaracion de integridad", "manifiesto de integridad", "integridad"],
            "DECL_ART_50_51": ["articulo 50", "articulo 51", "impedimento legal", "no inhabilitado"],
            "DECL_NACIONALIDAD": ["nacionalidad mexicana", "licitante mexicano"],
            "ECO_PRECIOS_UNITARIOS": ["precios unitarios", "analisis de precios unitarios", "formato economico"],
            "TEC_PROPUESTA_DETALLADA": ["propuesta tecnica", "propuesta detallada", "especificaciones tecnicas"],
        }

        # Matriz por Ley/Categoría
        policies = [
            {
                "law": "LAASSP",
                "category": "BIENES",
                "mandatory_labels": [
                    "LEG_ACTA_CONSTITUTIVA", "LEG_PODER_NOTARIAL", "LEG_IDENTIDAD_CANDIDATO",
                    "FIS_SAT_OPINION", "DECL_ART_50_51", "DECL_INTEGRIDAD", "DECL_MIPYME", 
                    "DECL_NACIONALIDAD", "TEC_PROPUESTA_DETALLADA", "ECO_PRECIOS_UNITARIOS"
                ],
                "critical_rules": ["DECLARACION_MIPYME_OBLIGATORIA"],
            },
            {
                "law": "LAASSP",
                "category": "SERVICIOS",
                "mandatory_labels": [
                    "LEG_ACTA_CONSTITUTIVA", "LEG_PODER_NOTARIAL", "LEG_IDENTIDAD_CANDIDATO",
                    "FIS_SAT_OPINION", "FIS_IMSS_OPINION", "FIS_INFONAVIT_OPINION", 
                    "DECL_ART_50_51", "DECL_INTEGRIDAD", "DECL_MIPYME", "DECL_NACIONALIDAD", 
                    "TEC_PROPUESTA_DETALLADA", "ECO_PRECIOS_UNITARIOS", "REPSE_REGISTRO"
                ],
                "critical_rules": ["DECLARACION_MIPYME_OBLIGATORIA", "OPINION_IMSS_POSITIVA"],
            },
            {
                "law": "LOPSRM",
                "category": "OBRA",
                "mandatory_labels": [
                    "LEG_ACTA_CONSTITUTIVA", "FIS_SAT_OPINION", "TEC_EXPERIENCIA_CURRICULUM",
                    "TEC_PLANTILLA_TECNICA", "TEC_PROGRAMA_OBRA", "ECO_PRECIOS_UNITARIOS", "ECO_EXPLOSION_INSUMOS"
                ],
                "critical_rules": ["ANALISIS_PRECIOS_UNITARIOS_DETALLADO"],
            }
        ]

        # Agregar aliases faltantes específicos de Servicios
        universal_aliases["FIS_IMSS_OPINION"] = ["opinion imss", "cumplimiento imss", "seguridad social"]
        universal_aliases["FIS_INFONAVIT_OPINION"] = ["opinion infonavit", "cumplimiento infonavit"]
        universal_aliases["REPSE_REGISTRO"] = ["repse", "registro de servicios especializados", "articulo 15"]

        for p_data in policies:
            # Upsert
            stmt = select(NormativePolicy).filter_by(law=p_data["law"], category=p_data["category"])
            res = await session.execute(stmt)
            existing = res.scalars().first()
            
            if existing:
                existing.mandatory_labels = p_data["mandatory_labels"]
                existing.critical_rules = p_data["critical_rules"]
                existing.alias_map = {k: universal_aliases[k] for k in p_data["mandatory_labels"] if k in universal_aliases}
            else:
                new_p = NormativePolicy(
                    law=p_data["law"],
                    category=p_data["category"],
                    mandatory_labels=p_data["mandatory_labels"],
                    critical_rules=p_data["critical_rules"],
                    alias_map={k: universal_aliases[k] for k in p_data["mandatory_labels"] if k in universal_aliases}
                )
                session.add(new_p)
        
        await session.commit()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(seed())
