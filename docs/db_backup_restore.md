# Procedimiento de Backup y Restore - LicitAI (PostgreSQL)

Este documento detalla el procedimiento validado para realizar copias de seguridad y restauraciones del volumen de datos de PostgreSQL en entornos tipo-producción (Docker).

## 1. Crear un Backup (Exportación Segura)

Se ejecuta sin apagar el contenedor de la base de datos, asegurando que los datos en memoria se vuelquen correctamente al `.sql`.

```bash
# Variables
BACKUP_DATE=$(date +"%Y%m%d_%H%M%S")
DB_CONTAINER="licitaciones-ai-database-1" # Nombre del contenedor dictado por docker-compose

# Ejecutar pg_dump dentro del contenedor
docker exec -t $DB_CONTAINER pg_dump -U postgres -d licitaciones -F c -f /tmp/backup_${BACKUP_DATE}.dump

# Extraer el archivo de backup al host local
docker cp ${DB_CONTAINER}:/tmp/backup_${BACKUP_DATE}.dump ./data/backups/
```

## 2. Restaurar un Backup (Cold Restore)

Para validar que el backup es funcional, se debe probar en un ambiente limpio (staging) o en caso de desastre total.

**Importante:** Se recomienda detener los contenedores del `backend` para evitar escrituras concurrentes durante el proceso de restauración.

```bash
# 2.1 Destruir y recrear el volumen (Opcional, simulación de limpieza total)
docker-compose stop database backend
docker volume rm licitaciones-ai_postgres_data
docker-compose up -d database

# Esperar unos segundos a que la BD inicie en limpio y ejecute init-db.sql
sleep 15

# 2.2 Copiar el dump al contenedor
LATEST_BACKUP=$(ls -t ./data/backups/backup_*.dump | head -1)
docker cp $LATEST_BACKUP ${DB_CONTAINER}:/tmp/restore.dump

# 2.3 Limpiar estructura actual y restaurar
docker exec -it $DB_CONTAINER pg_restore -U postgres -d licitaciones -1 -c /tmp/restore.dump

# 2.4 Reiniciar infraestructura
docker-compose restart database
docker-compose start backend
```

## 3. Checklist de Verificación (Tras Restore)
1. **Frontend**: Hacer login o carga de dashboard. ¿Aparecen las transacciones/empresas históricas?
2. **Backend**: Lanzar GET `/api/v1/health` o consultar sesión conocida.
3. **Persistencia de sesión**: Intentar la funcionalidad principal ("Reanudar desde una sesión") sobre uno de los IDs de sesión listados en el log.
