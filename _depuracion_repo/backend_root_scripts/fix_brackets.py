import os
from pathlib import Path

path = Path(r"c:\LicitAI_Multi_Agent\licitaciones-ai\backend\app\memory\adapters\postgres_adapter.py")
text = path.read_text(encoding="utf-8")

old_text = """                    "name": s.id.replace("_", " ").title() # Fallback name
                for s in sessions"""

new_text = """                    "name": s.id.replace("_", " ").title() # Fallback name
                }
                for s in sessions"""

text = text.replace(old_text, new_text)
path.write_text(text, encoding="utf-8")
