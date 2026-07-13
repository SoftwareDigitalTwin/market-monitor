# Source Collector V2 — Auto Risk

## Objetivo

Convertir el pipeline actual de scraping en un monitor de mercado por presencia:

1. recorrer índices/listados;
2. construir un manifiesto liviano de anuncios visibles;
3. comparar contra el estado persistente;
4. abrir detalle únicamente para anuncios nuevos, reaparecidos o pendientes por error;
5. detectar desapariciones con múltiples scans consecutivos;
6. impedir falsas bajas cuando un scan es parcial o anómalo.

El VMU Engine no se modifica en esta fase. Primero se estabiliza la evidencia temporal por fuente.

## Escala y nuevas fuentes

El diseño es source-agnostic. Cada fuente mantiene su propio scraper, pero hereda la reconciliación común desde `BaseScraper`.

Para agregar una fuente futura:

1. crear un módulo con una única subclase de `BaseScraper`;
2. implementar `get_listing_urls`, `parse_listing` y `build_search_url`;
3. insertar una fila en `data_sources` con `scraper_module` apuntando al módulo;
4. dejar `is_active = 1`.

`main.py` descubre dinámicamente las fuentes activas; no requiere agregar nuevos `if source == ...`.

## Flujo diario

```text
SOURCE INDEX
    ↓
LIGHTWEIGHT MANIFEST
    ↓
RECONCILE PRESENCE
    ├── NEW → DETAIL SCRAPE
    ├── SEEN → last_seen_date
    ├── REAPPEARED → DETAIL SCRAPE
    ├── PENDING DETAIL → RETRY
    └── ABSENT → missing streak
                     ↓
              confirmed inactive
```

## Estados de SourceListing

- `active`
- `missing_suspected`
- `inactive_confirmed`

No se usa `sold` a nivel de fuente. Una desaparición de un anuncio no prueba una venta.

## Guardas de seguridad

Una corrida no puede crear ausencias si:

- terminó por timeout/error;
- fue ejecutada con `--limit`;
- alcanzó `max_pages` antes de encontrar el final natural;
- el número de anuncios vistos cae por debajo del porcentaje mínimo de cobertura respecto al baseline activo.

Defaults:

```text
DTC_INACTIVE_CONFIRM_SCANS=3
DTC_MIN_COVERAGE_RATIO=0.85
DTC_SAFETY_MIN_BASELINE=100
DTC_MAX_DETAIL_SCRAPES_PER_RUN=1000
DTC_CRAUTOS_MAX_PAGES=5000
DTC_ENCUENTRA24_MAX_PAGES=5000
```

Los máximos de páginas son techos de seguridad, no objetivos. El scan termina antes cuando detecta el final natural.

`DTC_MAX_DETAIL_SCRAPES_PER_RUN` permite incorporar inventarios grandes por lotes. El manifiesto completo se registra desde el primer scan, pero el deep scrape de anuncios que todavía no tienen detalle se procesa gradualmente y se reintenta en corridas posteriores.

## Fotos

Esta fase no descarga imágenes, no genera embeddings y no agrega almacenamiento fotográfico.

La comparación visual debe implementarse después como fallback de matching VMU:

```text
structured score ambiguous
    ↓
download temporary images
    ↓
compare
    ↓
keep only compact signatures if useful
    ↓
delete temporary files
```

## Deploy recomendado

1. Crear branch desde el `main` actual.
2. Copiar los archivos completos de este paquete sobre las rutas equivalentes.
3. Ejecutar la migración:

```bash
mysql -u <user> -p <database> < scripts/migrate_source_collector_v2.sql
```

Alternativamente, después de reemplazar `models.py`, `python main.py init` crea las tablas nuevas con SQLAlchemy.

4. Ejecutar pruebas:

```bash
PYTHONPATH=. pytest -q tests/test_collector_service.py
```

5. Probar sin riesgo de bajas, usando limit:

```bash
python main.py collect CRAutos --limit 20
python main.py collect Encuentra24 --limit 20
```

Esas corridas quedan como `partial` y nunca incrementan `missing_streak`.

6. Ejecutar una fuente completa:

```bash
python main.py collect CRAutos
```

7. Revisar:

```bash
python main.py summary
```

8. Revisar API:

```text
GET /collector/summary
GET /collector/listings
GET /collector/runs
```

9. Después de validar una fuente, habilitar la otra.

## Qué no resuelve todavía esta fase

- matching VMU definitivo;
- price-change monitoring eficiente;
- seller entity / agencia específica;
- image fallback matching;
- marts analíticos y dashboard.

La siguiente fase debe diseñar la actualización de atributos sin volver al deep scrape de todo el inventario. La opción preferida es extraer precio y otras señales directamente desde cards/listados cuando cada fuente lo permita; como alternativa, usar refresh dirigido por riesgo o muestreo escalonado.
