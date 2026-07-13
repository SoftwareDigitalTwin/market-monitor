#!/usr/bin/env python3
"""
DTC Market Monitor - Source Collector V2.

Uso:
    python main.py init
    python main.py collect
    python main.py collect CRAutos
    python main.py collect Encuentra24
    python main.py collect CRAutos --limit 20
    python main.py pipeline
    python main.py summary

"scrape" se mantiene como alias de "collect" para compatibilidad operativa.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date

from dtc.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def cmd_init() -> None:
    from dtc.db.database import init_db, seed_data_sources

    logger.info("Inicializando base de datos...")
    init_db()
    seed_data_sources()
    logger.info("Inicialización completada.")


def cmd_summary() -> None:
    from sqlalchemy import func

    from dtc.db.database import get_session
    from dtc.db.models import (
        DataSource,
        RawListing,
        ScrapingRun,
        SourceListing,
        SourceScanMetric,
    )

    with get_session() as session:
        total_raw = session.query(RawListing).count()
        latest_date = session.query(func.max(RawListing.capture_date)).scalar()

        by_source = (
            session.query(DataSource.name, func.count(SourceListing.id))
            .outerjoin(SourceListing)
            .group_by(DataSource.id, DataSource.name)
            .order_by(DataSource.id)
            .all()
        )

        by_status = (
            session.query(
                DataSource.name,
                SourceListing.status,
                func.count(SourceListing.id),
            )
            .join(SourceListing, SourceListing.source_id == DataSource.id)
            .group_by(DataSource.name, SourceListing.status)
            .order_by(DataSource.name, SourceListing.status)
            .all()
        )

        latest_runs = (
            session.query(ScrapingRun, DataSource.name, SourceScanMetric)
            .join(DataSource, ScrapingRun.source_id == DataSource.id)
            .outerjoin(SourceScanMetric, SourceScanMetric.run_id == ScrapingRun.id)
            .order_by(ScrapingRun.started_at.desc())
            .limit(10)
            .all()
        )

        print(f"Raw listings: {total_raw}")
        print(f"Última captura de detalle: {latest_date}")
        print("\nSource listings por fuente:")
        for source_name, count in by_source:
            print(f"  - {source_name}: {count}")

        print("\nEstados de presencia:")
        for source_name, status, count in by_status:
            print(f"  - {source_name} / {status}: {count}")

        print("\nÚltimas corridas:")
        for run, source_name, metric in latest_runs:
            suffix = ""
            if metric:
                suffix = (
                    f" seen={metric.seen_count} new={metric.new_count} "
                    f"reappeared={metric.reappeared_count} "
                    f"missing={metric.missing_suspected_count} "
                    f"inactive={metric.inactive_confirmed_count} "
                    f"safety={metric.safety_passed}"
                )
            print(
                f"  - run={run.id} {source_name} {run.run_date} "
                f"status={run.status}{suffix}"
            )


def cmd_collect(source_name: str | None = None, limit: int | None = None) -> None:
    from dtc.scrapers.registry import get_active_scraper_classes

    specs = get_active_scraper_classes(source_name)
    if not specs:
        logger.warning("No hay fuentes activas configuradas.")
        return

    for configured_name, scraper_class in specs:
        logger.info(
            "Iniciando Source Collector V2 para %s%s",
            configured_name,
            f" (limit={limit})" if limit else "",
        )
        scraper = scraper_class(limit=limit) if limit is not None else scraper_class()
        asyncio.run(scraper.run())


def cmd_pipeline() -> None:
    logger.info("=" * 70)
    logger.info("PIPELINE DIARIO SOURCE COLLECTOR V2 - %s", date.today())
    logger.info("=" * 70)
    cmd_collect()
    logger.info("PIPELINE FINALIZADO")


def _parse_cli(argv: list[str]) -> tuple[str, str | None, int | None]:
    if len(argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    command = argv[1].lower()
    args = argv[2:]
    limit: int | None = None

    if "--limit" in args:
        index = args.index("--limit")
        try:
            limit = int(args[index + 1])
        except (IndexError, ValueError):
            print("--limit requiere un entero")
            raise SystemExit(1)
        args = args[:index] + args[index + 2 :]

    source_name = args[0] if args else None
    return command, source_name, limit


def main() -> None:
    setup_logging()
    command, source_name, limit = _parse_cli(sys.argv)

    commands = {
        "init": cmd_init,
        "collect": lambda: cmd_collect(source_name, limit),
        "scrape": lambda: cmd_collect(source_name, limit),
        "pipeline": cmd_pipeline,
        "summary": cmd_summary,
    }

    if command not in commands:
        print(f"Comando desconocido: {command}")
        print(f"Disponibles: {', '.join(commands)}")
        raise SystemExit(1)

    try:
        commands[command]()
    except KeyboardInterrupt:
        logger.info("Proceso interrumpido por el usuario.")
        raise SystemExit(0)
    except Exception as exc:
        logger.error("Error fatal: %s", exc, exc_info=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
