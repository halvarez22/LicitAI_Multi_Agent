# Usa una imagen oficial ligera de Python
FROM python:3.11-slim

# Evita que Python escriba archivos .pyc en disco y asegura que el log salga directo a la consola
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instala dependencias del sistema necesarias para compilar o ejecutar paquetes base (ej. psycopg2-binary si llegara a instalarse, gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Configura y crea el directorio de trabajo
WORKDIR /app

# Copia los requerimientos
COPY requirements.txt .

# Instala las dependencias en cache del docker
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia el código fuente del backend
COPY ./app /app/app
COPY pytest.ini .

# Expone el puerto port
EXPOSE 8000

# Añade healthcheck explícito para orquestación en docker-compose
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Comando de arranque via Uvicorn (modo producción estable - 1 worker, sin reload)
# NOTA: workers=1 es CRÍTICO para que asyncio.Semaphore del GPU Lock funcione correctamente.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
