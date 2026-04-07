"""
Elimina restos de licitaciones tras borrar sesiones en la UI u otro canal.

- ChromaDB: borra todas las colecciones (vectores RAG + experience_cases).
  Se recrean automáticamente al subir documentos o al indexar experiencia.
- Redis: borra claves job:* (estado de /agents/process).
- No toca Postgres (sessions, documents, etc.); ejecutar solo si ya están limpias
  o usar primero DELETE de sesiones en API.

Uso en Docker (desde host):
  docker exec licitaciones-ai-backend-1 python /app/scripts/prune_licitacion_traces.py

Variables opcionales:
  PRUNE_SKIP_CHROMA=1   — no tocar Chroma
  PRUNE_SKIP_REDIS=1    — no tocar Redis
"""
from __future__ import annotations

import os
import sys


def _prune_chroma() -> int:
    import chromadb

    url = os.getenv("VECTOR_DB_URL", "http://vector-db:8000")
    host = url.replace("http://", "").split(":")[0]
    port = int(url.split(":")[-1])
    client = chromadb.HttpClient(host=host, port=port)
    cols = list(client.list_collections())
    n = 0
    for col in cols:
        try:
            client.delete_collection(name=col.name)
            print(f"[chroma] eliminada colección: {col.name}")
            n += 1
        except Exception as e:
            print(f"[chroma] error {col.name}: {e}", file=sys.stderr)
    return n


def _prune_redis_jobs() -> int:
    import redis
    from app.config.settings import settings

    host = os.getenv("REDIS_HOST", settings.REDIS_HOST)
    port = int(os.getenv("REDIS_PORT", settings.REDIS_PORT))
    r = redis.Redis(host=host, port=port, decode_responses=True)
    deleted = 0
    for key in r.scan_iter(match="job:*"):
        r.delete(key)
        deleted += 1
    print(f"[redis] claves job:* eliminadas: {deleted}")
    return deleted


def main() -> int:
    if os.getenv("PRUNE_SKIP_CHROMA", "").lower() in ("1", "true", "yes"):
        print("[chroma] omitido (PRUNE_SKIP_CHROMA)")
    else:
        _prune_chroma()

    if os.getenv("PRUNE_SKIP_REDIS", "").lower() in ("1", "true", "yes"):
        print("[redis] omitido (PRUNE_SKIP_REDIS)")
    else:
        _prune_redis_jobs()

    print("Listo.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    raise SystemExit(main())
