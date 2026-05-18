
import os
import openpyxl
from typing import List, Dict, Any
from app.core.observability import get_logger

logger = get_logger(__name__)

class ExcelFillingService:
    """
    Servicio 'Espejo' para Excel: 
    Inyecta datos confirmados en archivos .xlsx originales preservando el formato oficial.
    """

    def __init__(self, base_data_dir: str = "/data"):
        self.base_data_dir = base_data_dir

    def fill_proposal_excel(
        self, 
        session_id: str, 
        source_filename: str, 
        items_to_fill: List[Dict[str, Any]],
        output_filename: str = None
    ) -> str:
        """
        Toma el archivo original de inputs e inyecta los precios en un nuevo archivo en outputs.
        
        items_to_fill debe contener dicts con:
            - sheet_name
            - row_index (0-indexed desde pandas)
            - price_column_index
            - final_price
        """
        input_path = os.path.join(self.base_data_dir, "inputs", session_id, source_filename)
        output_dir = os.path.join(self.base_data_dir, "outputs", session_id, "economic_proposal")
        os.makedirs(output_dir, exist_ok=True)
        
        if not output_filename:
            output_filename = f"PROPUESTA_ECONOMICA_{source_filename}"
        
        output_path = os.path.join(output_dir, output_filename)

        if not os.path.exists(input_path):
            logger.error("excel_fill_input_not_found", path=input_path)
            raise FileNotFoundError(f"No se encontró el archivo original: {source_filename}")

        try:
            # Cargar el libro original preservando estilos
            wb = openpyxl.load_workbook(input_path, data_only=False)
            
            filled_count = 0
            for item in items_to_fill:
                sheet_name = item.get("sheet_name")
                row_idx = item.get("row_index")
                col_idx = item.get("price_column_index")
                price = item.get("final_price")

                if sheet_name not in wb.sheetnames:
                    logger.warning("excel_fill_sheet_not_found", sheet=sheet_name)
                    continue
                
                sheet = wb[sheet_name]
                
                # Ajuste de índices: 
                # pandas es 0-indexed y excluye el header si lo detectó.
                # openpyxl es 1-indexed.
                # Si pandas detectó headers, la fila 0 de pandas es la fila 2 de Excel.
                # Por seguridad, asumimos que row_index ya viene ajustado o lo ajustamos aquí + 2.
                # NOTA: En tabular_line_item_extract, el row_index es el índice del DataFrame.
                excel_row = int(row_idx) + 2 
                excel_col = int(col_idx) + 1
                
                try:
                    sheet.cell(row=excel_row, column=excel_col).value = price
                    filled_count += 1
                except Exception as e:
                    logger.error("excel_fill_cell_error", row=excel_row, col=excel_col, error=str(e))

            wb.save(output_path)
            logger.info("excel_fill_completed", session_id=session_id, filled_items=filled_count, output=output_path)
            return output_path

        except Exception as e:
            logger.error("excel_fill_critical_error", session_id=session_id, error=str(e))
            raise e
