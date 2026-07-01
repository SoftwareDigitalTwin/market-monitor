# DTC Market Monitor - Docker Setup

Esta versión levanta todo con Docker:

- MySQL 8 con volumen persistente.
- API FastAPI autenticada con `X-API-Key`.
- Scheduler diario para correr `python main.py pipeline`.
- Persistencia de metadatos y URLs originales de fotos. No descarga ni guarda imágenes.

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

Las fotos no se descargan. El sistema conserva las URLs originales del sitio en `raw_photos` y en `listing_images.source_url`.

## 2. Levantar el stack

Desarrollo/local:

```bash
docker compose up -d --build
```

Producción en servidor:

```bash
sudo mkdir -p /opt/market-monitor
sudo mkdir -p /etc/market-monitor
sudo mkdir -p /var/lib/market-monitor/mysql
sudo mkdir -p /var/lib/market-monitor/data
```

Copia el proyecto a `/opt/market-monitor` y la configuración a `/etc/market-monitor/.env`. Luego levanta con:

```bash
cd /opt/market-monitor
docker compose --env-file /etc/market-monitor/.env \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build
```

El servicio `mysql` crea la base `dtc_market` y el usuario configurado. El servicio `api` espera a MySQL y ejecuta `python main.py init`, que crea las tablas y fuentes iniciales de forma idempotente. El `scheduler` espera a que el API esté saludable antes de empezar.

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

En desarrollo los datos quedan en volúmenes Docker:

- `mysql_data`: base MySQL.
- `app_data`: logs y JSON de respaldo.

En producción con `docker-compose.prod.yml` quedan en rutas explícitas:

- `/var/lib/market-monitor/mysql`: base MySQL.
- `/var/lib/market-monitor/data`: logs internos y JSON de respaldo.

No borres esos volúmenes o carpetas si quieres conservar histórico.

## Deduplicación

La DB evita duplicados diarios con:

- `source_id + external_id + capture_date`
- `source_id + url + capture_date`

Las imágenes se deduplican por:

- `raw_listing_id + source_url`
