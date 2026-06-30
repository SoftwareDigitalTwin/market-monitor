# DTC Market Monitor - Docker Setup

Esta versión levanta todo con Docker:

- MySQL 8 con volumen persistente.
- API FastAPI autenticada con `X-API-Key`.
- Scheduler diario para correr `python main.py pipeline`.
- Storage local de fotos en volumen Docker, o GCS si lo activas.

## 1. Configuración

```bash
cp .env.example .env
```

Cambia al menos estos valores:

```bash
DTC_DB_PASSWORD=un_password_seguro
DTC_DB_ROOT_PASSWORD=otro_password_seguro
DTC_API_KEYS=una_clave_larga_y_secreta
DTC_DAILY_RUN_AT=03:15
```

Por defecto las fotos se guardan localmente en el volumen `app_data`:

```bash
DTC_STORAGE_BACKEND=local
DTC_LOCAL_STORAGE_DIR=/app/data/images
DTC_LOCAL_STORAGE_PUBLIC_BASE_URL=/media
```

Para usar GCP Storage:

```bash
DTC_STORAGE_BACKEND=gcs
DTC_STORAGE_ENABLED=true
DTC_GCS_BUCKET=tu-bucket
DTC_GCS_PREFIX=market-monitor
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/service-account.json
```

Si usas GCS en Docker, monta el JSON de credenciales como volumen o usa credenciales del entorno del servidor.

## 2. Levantar el stack

```bash
docker compose up -d --build
```

El servicio `mysql` crea la base `dtc_market` y el usuario configurado. Los servicios `api` y `scheduler` esperan a MySQL y luego ejecutan `python main.py init`, que crea las tablas y fuentes iniciales de forma idempotente.

## 3. Consumir el API

Healthcheck sin autenticación:

```bash
curl http://localhost:8000/health
```

Endpoints protegidos:

```bash
curl -H "X-API-Key: una_clave_larga_y_secreta" \
  "http://localhost:8000/listings?limit=20"
```

Endpoints principales:

- `GET /auth/check`
- `GET /sources`
- `GET /listings?source=Encuentra24&brand=Toyota&limit=100`
- `GET /listings/{id}`
- `GET /runs`
- `GET /analytics/summary`
- `GET /media/{path}` para fotos locales, también protegido con `X-API-Key`

## 4. Scheduler diario

El servicio `scheduler` corre una vez al día a la hora `DTC_DAILY_RUN_AT` en horario del servidor/contenedor.

Para ejecutar scraping inmediatamente al iniciar el contenedor:

```bash
DTC_RUN_ON_STARTUP=true
```

Para correrlo manualmente:

```bash
docker compose run --rm scheduler python main.py pipeline
```

## 5. Ver logs

```bash
docker compose logs -f api
docker compose logs -f scheduler
docker compose logs -f mysql
```

## 6. Persistencia

Los datos quedan en volúmenes Docker:

- `mysql_data`: base MySQL.
- `app_data`: logs, JSON de respaldo y fotos locales.

No borres esos volúmenes si quieres conservar histórico.

## Deduplicación

La DB evita duplicados diarios con:

- `source_id + external_id + capture_date`
- `source_id + url + capture_date`

Las imágenes se deduplican por:

- `raw_listing_id + source_url`
