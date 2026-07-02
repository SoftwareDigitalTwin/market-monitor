#!/usr/bin/env python3
"""
DTC - Sistema de Monitoreo del Mercado de Vehículos Usados (Costa Rica)

Script principal (CLI) para ejecutar los scrapers.

La persistencia usa MySQL. Las fotos no se descargan; se guardan las URLs
originales del sitio junto con los metadatos del anuncio. Los scrapers también
pueden generar JSON normalizado en data/processed/ como respaldo local.

Uso:
    python main.py scrape                    # Ejecuta scraping de todas las fuentes
    python main.py scrape crautos            # Solo CRAutos
    python main.py scrape crautos --limit 5  # Solo los primeros 5 anuncios
    python main.py scrape encuentra24        # Solo Encuentra24
    python main.py pipeline                  # Ejecución diaria recomendada
    python main.py init                      # Crea tablas y fuentes iniciales
    python main.py summary                   # Resumen básico de datos
"""

import sys
import asyncio
import logging
from datetime import date

from dtc.utils.logger import setup_logging
from dtc.config.settings import config

logger = logging.getLogger(__name__)


def cmd_init():
    """Inicializa la base de datos y las fuentes de datos."""
    from dtc.db.database import init_db, seed_data_sources
    logger.info("Inicializando base de datos...")
    init_db()
    seed_data_sources()
    logger.info("Inicialización completada.")


def cmd_summary():
    """Muestra un resumen básico del mercado capturado."""
    from sqlalchemy import func
    from dtc.db.database import get_session
    from dtc.db.models import DataSource, RawListing, ScrapingRun

    with get_session() as session:
        total = session.query(RawListing).count()
        latest_date = session.query(func.max(RawListing.capture_date)).scalar()
        by_source = (
            session.query(DataSource.name, func.count(RawListing.id))
            .join(RawListing)
            .group_by(DataSource.name)
            .all()
        )
        latest_runs = (
            session.query(ScrapingRun, DataSource.name)
            .join(DataSource)
            .order_by(ScrapingRun.started_at.desc())
            .limit(5)
            .all()
        )

    print(f"Total anuncios: {total}")
    print(f"Última captura: {latest_date}")
    print("Por fuente:")
    for source, count in by_source:
        print(f"  - {source}: {count}")
    print("Últimas corridas:")
    for run, source in latest_runs:
        print(
            f"  - {run.id} {source} {run.run_date} "
            f"{run.status} nuevos={run.new_listings} errores={run.errors}"
        )


def cmd_scrape(source_name: str = None, limit: int = None):
    """Ejecuta el scraping de una o todas las fuentes y vuelca a JSON."""

    async def _run_scraper(scraper_class):
        scraper = scraper_class(limit=limit) if limit else scraper_class()
        await scraper.run()

    if source_name is None or source_name.lower() == "crautos":
        from dtc.scrapers.crautos_scraper import CRAutosScraper
        logger.info(
            f"Iniciando scraping de CRAutos"
            + (f" (limit={limit})..." if limit else "...")
        )
        asyncio.run(_run_scraper(CRAutosScraper))

    if source_name is None or source_name.lower() == "encuentra24":
        from dtc.scrapers.encuentra24_scraper import Encuentra24Scraper
        logger.info(
            f"Iniciando scraping de Encuentra24"
            + (f" (limit={limit})..." if limit else "...")
        )
        asyncio.run(_run_scraper(Encuentra24Scraper))


def cmd_pipeline():
    """Pipeline diario: scraping + normalización + persistencia."""
    logger.info("=" * 60)
    logger.info(f"PIPELINE DIARIO - {date.today()}")
    logger.info("=" * 60)

    try:
        cmd_scrape()
        logger.info("Scraping y persistencia completados.")
    except Exception as e:
        logger.error(f"Error en pipeline: {e}")

    logger.info("=" * 60)
    logger.info("PIPELINE FINALIZADO")
    logger.info("=" * 60)


def main():
    """Punto de entrada principal."""
    setup_logging()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    args = sys.argv[2:] if len(sys.argv) > 2 else []

    # Soporte simple para --limit N en cualquier posición de los args
    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        try:
            limit = int(args[idx + 1])
        except (IndexError, ValueError):
            print("--limit requiere un entero")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    source_arg = args[0] if args else None

    commands = {
        "init": cmd_init,
        "scrape": lambda: cmd_scrape(source_arg, limit=limit),
        "pipeline": cmd_pipeline,
        "summary": cmd_summary,
    }

    if command not in commands:
        print(f"Comando desconocido: '{command}'")
        print(f"Comandos disponibles: {', '.join(commands.keys())}")
        sys.exit(1)

    try:
        commands[command]()
    except KeyboardInterrupt:
        logger.info("\nProceso interrumpido por el usuario.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error fatal: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
