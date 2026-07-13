# DTC Market Monitor - Docker Setup

Esta versión levanta todo con Docker:

- MySQL 8 con volumen persistente.
- API FastAPI autenticada con `X-API-Key`.
- Scheduler diario para correr `python main.py pipeline`.
- Source Collector V2 para monitorear presencia por fuente.
- Persistencia de datos del anuncio y URLs originales de fotos. No descarga ni guarda imágenes.

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
DTC_MAX_DETAIL_SCRAPES_PER_RUN=1000
```

Las fotos no se descargan. El sistema conserva las URLs originales del sitio solo en `raw_photos`.

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

Si estás actualizando una base existente, `python main.py init` también crea las tablas nuevas del collector. Si prefieres migración SQL explícita:

```bash
mysql -u <user> -p <database> < scripts/migrate_source_collector_v2.sql
```

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
- `GET /collector/summary`
- `GET /collector/listings?source=CRAutos&status=active`
- `GET /collector/runs`
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

También puedes correr una fuente específica sin afectar el scheduler:

```bash
docker compose run --rm scheduler python main.py collect CRAutos
docker compose run --rm scheduler python main.py collect Encuentra24
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

La DB evita duplicados diarios de detalle en `raw_listings` con:

- `source_id + listing_key + capture_date`
- `source_id + external_id + capture_date`
- `source_id + url + capture_date`

El collector mantiene una identidad persistente por anuncio en `source_listings` con:

- `source_id + listing_key`

Las imágenes no se descargan ni se guardan en una tabla separada.
