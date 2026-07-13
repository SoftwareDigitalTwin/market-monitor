from __future__ import annotations

import importlib
import inspect

from dtc.db.database import get_session
from dtc.db.models import DataSource
from dtc.scrapers.base_scraper import BaseScraper


def load_scraper_class(module_path: str) -> type[BaseScraper]:
    """Carga dinámicamente la única subclase BaseScraper definida en un módulo."""
    module = importlib.import_module(module_path)
    candidates: list[type[BaseScraper]] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            obj is not BaseScraper
            and issubclass(obj, BaseScraper)
            and obj.__module__ == module.__name__
        ):
            candidates.append(obj)

    if len(candidates) != 1:
        raise RuntimeError(
            f"El módulo {module_path} debe definir exactamente una subclase "
            f"BaseScraper; encontradas={len(candidates)}"
        )
    return candidates[0]


def get_active_scraper_classes(
    source_name: str | None = None,
) -> list[tuple[str, type[BaseScraper]]]:
    """
    Descubre fuentes activas desde data_sources.

    Para agregar una nueva fuente no se modifica main.py: se crea su módulo scraper,
    se registra DataSource.scraper_module y se marca is_active=True.
    """
    with get_session() as session:
        query = session.query(DataSource).filter(DataSource.is_active.is_(True))
        if source_name:
            query = query.filter(DataSource.name.ilike(source_name))
        sources = query.order_by(DataSource.id).all()

        if source_name and not sources:
            # Permite alias case-insensitive como "crautos".
            sources = (
                session.query(DataSource)
                .filter(DataSource.is_active.is_(True))
                .all()
            )
            sources = [s for s in sources if s.name.lower() == source_name.lower()]

        specs = [(source.name, source.scraper_module) for source in sources]

    if source_name and not specs:
        raise ValueError(f"Fuente activa no encontrada: {source_name}")

    return [(name, load_scraper_class(module)) for name, module in specs]
