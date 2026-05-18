import os
import re
from typing import Dict, Any, List, Optional
from openpyxl import load_workbook
from app.core.logging_config import get_logger

logger = get_logger(__name__)

class EconomicDataIngestor:
    """
    Ingestor y Parser de Plantillas Excel para captura de datos económicos.
    Valida encabezados de columnas, extrae parámetros de nómina e inyecta
    directamente en el perfil corporativo y/o estado de la sesión.
    """
    
    @staticmethod
    def parse_economic_excel(file_path: str) -> Dict[str, Any]:
        """
        Lee el archivo Excel, busca hojas y extrae los datos clave.
        Soporta columnas:
        - Parametro / Concepto / Concept / Campo
        - Valor / Monto / Precio / Value / Price
        """
        results = {
            "labor_compliance": {},
            "concept_prices": {},
            "errors": []
        }
        
        if not os.path.exists(file_path):
            results["errors"].append("El archivo temporal de Excel no existe.")
            return results
            
        wb = None
        try:
            wb = load_workbook(file_path, data_only=True)
            ws = wb.active # Toma la hoja activa por defecto
            
            # Buscar fila de encabezados
            header_row = 1
            concept_col = None
            value_col = None
            
            # Escanear las primeras 5 filas para encontrar encabezados
            found_headers = False
            for r in range(1, 6):
                row_vals = [str(ws.cell(row=r, column=c).value or "").strip().lower() for c in range(1, 10)]
                for idx, val in enumerate(row_vals, 1):
                    if val in ("concepto", "parametro", "concepto / parametro", "concept", "campo", "variable"):
                        concept_col = idx
                    if val in ("valor", "monto", "precio", "value", "price", "tasa", "costo"):
                        value_col = idx
                if concept_col and value_col:
                    header_row = r
                    found_headers = True
                    break
                    
            if not found_headers:
                # Fallback: asumimos columna 1 es Concepto y columna 2 es Valor
                concept_col = 1
                value_col = 2
                logger.warning("[EconomicIngestor] Encabezados no detectados. Usando fallback (Col 1: Concepto, Col 2: Valor).")
            
            # Leer filas de datos
            max_row = ws.max_row
            for r in range(header_row + 1, max_row + 1):
                concept_val = ws.cell(row=r, column=concept_col).value
                value_val = ws.cell(row=r, column=value_col).value
                
                if concept_val is None:
                    continue
                    
                concept_str = str(concept_val).strip()
                concept_lower = concept_str.lower().strip()
                
                # Protocolo Anti-Envenenamiento: Bloquear impuestos y cuotas explícitas
                poison_keywords = (
                    "cuota", "imss", "i.m.s.s", "sar", "s.a.r", "infonavit", 
                    "impuesto sobre", "impuestos", "cesantia", "cesantía", "retiro", 
                    "guarderia", "guardería", "invalidez", "vida", "prestaciones",
                    "carga patronal", "cuotas obrero patronales", "c.o.p.", "cop",
                    "seguro social", "carga impositiva"
                )
                
                # Excepciones permitidas para el perfil: "clase de riesgo imss" (pues es un parámetro, no una cuota)
                is_poison = False
                if not any(x in concept_lower for x in ("clase de riesgo", "clase riesgo", "prima de riesgo")):
                    if any(x in concept_lower for x in poison_keywords):
                        is_poison = True
                        
                if is_poison:
                    logger.debug(f"[EconomicIngestor] Protocolo Anti-Envenenamiento bloqueó la celda: {concept_str}")
                    continue

                # Expansor Ontológico para Salario Base
                salary_ontology = (
                    "salario:", "salario", "salario mensual", "sueldo", 
                    "sbc", "s.b.c.", "s.b.c", "diario", "salario base", 
                    "salario base diario", "sueldo base", "base_salary_per_day", 
                    "salario_diario", "sueldo bruto"
                )
                
                if concept_lower in salary_ontology or any(concept_lower.startswith(x) for x in salary_ontology):
                    try:
                        val_num = float(str(value_val).replace(",", "").replace("$", ""))
                        results["labor_compliance"]["base_salary_per_day"] = val_num
                    except Exception:
                        results["errors"].append(f"Fila {r}: Valor inválido para Salario Base ({value_val})")
                        
                elif any(x in concept_lower for x in ("clase de riesgo", "clase riesgo", "imss_risk_class", "riesgo imss", "prima de riesgo")):
                    risk_str = str(value_val).strip().upper()
                    results["labor_compliance"]["imss_risk_class"] = risk_str
                        
                elif any(x in concept_lower for x in ("fsr", "factor de salario real", "daily_fsr", "factor salario real")):
                    try:
                        val_num = float(str(value_val).replace(",", "").replace("$", ""))
                        results["labor_compliance"]["daily_fsr"] = val_num
                    except Exception:
                        results["errors"].append(f"Fila {r}: Valor inválido para FSR ({value_val})")
                
                # Para cualquier otra fila, asumimos que es un precio unitario de concepto/partida
                else:
                    if value_val is not None:
                        try:
                            val_num = float(str(value_val).replace(",", "").replace("$", ""))
                            results["concept_prices"][concept_str] = val_num
                        except Exception:
                            pass
                            
            # Validar si extrajo algo
            if not results["labor_compliance"] and not results["concept_prices"]:
                results["errors"].append("No se pudieron extraer datos o variables económicas del archivo. Verifica el formato.")
                
        except Exception as e:
            logger.error(f"[EconomicIngestor] Error procesando Excel: {e}")
            results["errors"].append(f"Error crítico al leer el archivo Excel: {str(e)}")
        finally:
            if wb is not None:
                try:
                    wb.close()
                except Exception:
                    pass
            
        return results

    @classmethod
    async def ingest_and_save_data(cls, memory: Any, session_id: str, company_id: str, file_path: str) -> Dict[str, Any]:
        """
        Ejecuta el análisis del Excel y guarda los parámetros en la base de datos (Master Profile + Session State).
        """
        parse_results = cls.parse_economic_excel(file_path)
        
        if parse_results["errors"] and not parse_results["labor_compliance"] and not parse_results["concept_prices"]:
            return {
                "success": False,
                "message": "Fallo al procesar el Excel.",
                "errors": parse_results["errors"]
            }
            
        # 1. Persistir variables de nómina en el master_profile de la empresa
        labor_data = parse_results["labor_compliance"]
        if labor_data and company_id:
            company = await memory.get_company(company_id)
            if company:
                profile = company.get("master_profile", {})
                current_labor = profile.get("labor_compliance", {})
                if not isinstance(current_labor, dict):
                    current_labor = {}
                
                # Combinar datos nuevos con existentes
                for k, v in labor_data.items():
                    current_labor[k] = v
                
                # Proveer un valor por defecto seguro para ISN si no existe, ya que bloqueamos su lectura del Excel
                if current_labor.get("isn_rate") is None:
                    current_labor["isn_rate"] = 0.03
                
                # Si todos los campos requeridos existen, cambiar estatus a VALIDATED
                required_fields = ["base_salary_per_day", "imss_risk_class", "daily_fsr"]
                if all(current_labor.get(f) is not None for f in required_fields):
                    current_labor["status"] = "VALIDATED"
                else:
                    current_labor["status"] = "PENDING_INPUT"
                    
                profile["labor_compliance"] = current_labor
                company["master_profile"] = profile
                await memory.save_company(company_id, company)
                logger.info(f"[EconomicIngestor] Labor compliance actualizado para {company_id}: {current_labor}")
                
        # 2. Persistir precios en el economic_user_inputs de la sesión
        concept_prices = parse_results["concept_prices"]
        session = await memory.get_session(session_id)
        if session and (concept_prices or labor_data):
            inputs = session.get("economic_user_inputs", {})
            current_prices = inputs.get("concept_prices", {})
            if not isinstance(current_prices, dict):
                current_prices = {}
                
            # Mapear precios de conceptos
            for concept, price in concept_prices.items():
                # Encontrar el ID de concepto más cercano o indexar directamente
                current_prices[concept] = price
                
            inputs["concept_prices"] = current_prices
            
            # Sincronizar parámetros de nómina al user_inputs también para que el FSR se beneficie
            for k, v in labor_data.items():
                inputs[k] = v
                
            session["economic_user_inputs"] = inputs
            
            # Guardar la sesión
            await memory.save_session(session_id, session)
            logger.info(f"[EconomicIngestor] Precios y parámetros económicos inyectados en la sesión: {inputs}")
            
            # Re-correr cálculos económicos
            from app.economic_validation.service import refresh_economic_validations_for_session
            try:
                result = await refresh_economic_validations_for_session(memory, session_id)
                # Paso 3: Log de consistencia y blindaje de recalculo nativo
                if hasattr(result, "engine_output") and result.engine_output:
                    vat_amount = getattr(result.engine_output, "total_vat", "N/A")
                    subtotal = getattr(result.engine_output, "subtotal", "N/A")
                    logger.info(f"[EconomicIngestor] CONSISTENCIA LEGAL: El motor 'EconomicCalculatorEngine' ha recalcuado exitosamente todos los impuestos. IVA (16%) nativo generado = ${vat_amount} sobre subtotal de ${subtotal}.")
            except Exception as e:
                logger.error(f"[EconomicIngestor] Error al recalcular validaciones económicas: {e}")
                
        return {
            "success": True,
            "message": "Datos económicos y de nómina importados con éxito desde la plantilla Excel.",
            "data": parse_results
        }
