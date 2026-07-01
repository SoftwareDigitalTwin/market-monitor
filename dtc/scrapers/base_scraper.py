"""
Clase base para todos los agentes de scraping.
Define la interfaz común y funcionalidades compartidas.

Los scrapers acumulan los anuncios en memoria, los normalizan, los guardan en
MySQL de forma idempotente y opcionalmente escriben un JSON de respaldo.
"""

import json
import logging
import asyncio
from abc import ABC, abstractmethod
from datetime import date
from types import SimpleNamespace
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup

from dtc.config.settings import config, PROCESSED_DIR
from dtc.db.database import SessionLocal, get_session
from dtc.db.models import ScrapingRun
from dtc.db.repository import (
    acquire_source_lock,
    ensure_data_source,
    finish_scraping_run,
    mark_abandoned_runs,
    release_source_lock,
    start_scraping_run,
    upsert_raw_listing,
)
from dtc.normalizer.normalizer import normalize_listing
from dtc.storage.gcs import GCSImageStorage

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Clase base abstracta para scrapers de portales de vehículos."""

    def __init__(self, source_name: str, limit: Optional[int] = None):
        self.source_name = source_name
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.scraping_run_id: Optional[int] = None
        self.lock_acquired = False
        self.lock_session = None
        self.config = config.scraper
        self.limit = limit  # opcional: tope de anuncios a parsear
        self.listings: list[dict] = []
        self.error_messages: list[str] = []
        self.stats = {
            "total_pages": 0,
            "total_listings": 0,
            "new_listings": 0,
            "errors": 0,
        }

    async def start_browser(self):
        """Inicia el navegador Playwright."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.config.headless
        )
        context = await self.browser.new_context(
            user_agent=self.config.user_agent,
            viewport={"width": 1920, "height": 1080},
        )
        self.page = await context.new_page()
        self.page.set_default_timeout(self.config.timeout)
        logger.info(f"Navegador iniciado para {self.source_name}")

    async def close_browser(self):
        """Cierra el navegador."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info(f"Navegador cerrado para {self.source_name}")

    def _start_run(self) -> int:
        """Registra el inicio de una corrida de scraping."""
        self.lock_session = SessionLocal()
        if not acquire_source_lock(self.lock_session, self.source_name):
            self.lock_session.close()
            self.lock_session = None
            raise RuntimeError(
                f"Ya hay una corrida activa para {self.source_name}. "
                "Evito correr otra para no duplicar trabajo."
            )
        self.lock_acquired = True

        with get_session() as session:
            source = ensure_data_source(session, self.source_name)
            abandoned = mark_abandoned_runs(session, source)
            if abandoned:
                logger.warning(
                    "Se marcaron %s corridas anteriores como abandonadas para %s",
                    abandoned,
                    self.source_name,
                )
            run = start_scraping_run(session, source)
            run_id = run.id
        self.scraping_run_id = run_id
        logger.info(f"Corrida de scraping iniciada: ID={run_id}")
        return run_id

    def _finish_run(self, status: str = "completed", error_details: str = None):
        """Registra el fin de una corrida de scraping."""
        if not self.scraping_run_id:
            return
        with get_session() as session:
            run = session.get(ScrapingRun, self.scraping_run_id)
            if run:
                finish_scraping_run(session, run, self.stats, status, error_details)
        logger.info(
            f"Corrida finalizada: {status} | "
            f"Páginas: {self.stats['total_pages']} | "
            f"Anuncios: {self.stats['total_listings']} | "
            f"Nuevos: {self.stats['new_listings']} | "
            f"Errores: {self.stats['errors']}"
        )

    def _add_listing(self, listing_data: dict):
        """Normaliza un anuncio y lo acumula en memoria."""
        try:
            normalized = normalize_listing(SimpleNamespace(**listing_data))
        except Exception as e:
            logger.error(f"Error normalizando anuncio: {e}")
            normalized = {}

        record = {**listing_data, **normalized}
        self.listings.append(record)
        return record

    def _persist_listing(self, listing_data: dict) -> bool:
        """Guarda un anuncio inmediatamente para no perder progreso si el proceso muere."""
        storage = GCSImageStorage()
        with get_session() as session:
            source = ensure_data_source(session, self.source_name)
            inserted = upsert_raw_listing(session, source, listing_data, storage)
        if inserted:
            self.stats["new_listings"] += 1
        return inserted

    def _save_to_db(self) -> int:
        """Guarda anuncios acumulados en MySQL y evita duplicados diarios."""
        storage = GCSImageStorage()
        inserted = 0
        with get_session() as session:
            source = ensure_data_source(session, self.source_name)
            for listing in self.listings:
                if upsert_raw_listing(session, source, listing, storage):
                    inserted += 1
        self.stats["new_listings"] = inserted
        logger.info(
            "DB actualizada para %s: %s nuevos / %s procesados",
            self.source_name,
            inserted,
            len(self.listings),
        )
        return inserted

    def _record_error(self, message: str, exc: Exception = None):
        self.stats["errors"] += 1
        detail = f"{message}: {exc}" if exc else message
        self.error_messages.append(detail[:1000])

    def _save_to_json(self) -> str:
        """Escribe los anuncios acumulados en un archivo JSON."""
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        filename = PROCESSED_DIR / f"{self.source_name.lower()}_{today}.json"

        payload = {
            "source": self.source_name,
            "capture_date": today,
            "stats": self.stats,
            "listings": self.listings,
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

        logger.info(
            f"JSON guardado en {filename} ({len(self.listings)} anuncios)"
        )
        return str(filename)

    async def get_page_soup(self, url: str) -> BeautifulSoup:
        """Navega a una URL y retorna un BeautifulSoup del HTML."""
        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(self.config.delay_between_requests)
        html = await self.page.content()
        return BeautifulSoup(html, "html.parser")

    @abstractmethod
    async def get_listing_urls(self) -> list[str]:
        """Obtiene las URLs de todos los anuncios disponibles."""
        pass

    @abstractmethod
    async def parse_listing(self, url: str) -> Optional[dict]:
        """Extrae los datos de un anuncio individual."""
        pass

    @abstractmethod
    def build_search_url(self, page_number: int) -> str:
        """Construye la URL de búsqueda para una página específica."""
        pass

    async def run(self):
        """
        Ejecuta el proceso completo de scraping.
        1. Inicia navegador
        2. Recorre páginas de resultados
        3. Extrae datos de cada anuncio
        4. Normaliza, persiste en DB y opcionalmente vuelca a JSON
        """
        self._start_run()

        try:
            await self.start_browser()

            # Obtener todas las URLs de anuncios
            logger.info(f"Obteniendo listado de anuncios de {self.source_name}...")
            listing_urls = await self.get_listing_urls()
            if self.limit is not None:
                listing_urls = listing_urls[: self.limit]
                logger.info(f"Limitando a los primeros {self.limit} anuncios.")
            self.stats["total_listings"] = len(listing_urls)
            logger.info(f"Se encontraron {len(listing_urls)} anuncios.")

            # Procesar cada anuncio
            for i, url in enumerate(listing_urls, 1):
                try:
                    logger.info(f"[{i}/{len(listing_urls)}] Procesando: {url}")
                    listing_data = await self.parse_listing(url)

                    if listing_data:
                        listing_data["source_name"] = self.source_name
                        listing_data["capture_date"] = date.today().isoformat()
                        listing_data["url"] = url
                        record = self._add_listing(listing_data)
                        self._persist_listing(record)

                    await asyncio.sleep(self.config.delay_between_pages)

                except Exception as e:
                    self._record_error(f"Error procesando {url}", e)
                    logger.error(f"Error procesando {url}: {e}")
                    continue

            if config.save_json_backup:
                self._save_to_json()
            status = "completed"
            error_details = "\n".join(self.error_messages[-10:]) or None
            if self.stats["errors"] and not self.listings:
                status = "failed"
                error_details = error_details or "La corrida terminó sin anuncios y con errores."
            self._finish_run(status=status, error_details=error_details)
            logger.info(
                f"Scraping de {self.source_name} finalizado | "
                f"Páginas: {self.stats['total_pages']} | "
                f"Anuncios: {self.stats['total_listings']} | "
                f"Guardados: {self.stats['new_listings']} | "
                f"Errores: {self.stats['errors']}"
            )

        except Exception as e:
            self._record_error("Error fatal en scraping", e)
            self._finish_run(status="failed", error_details=str(e))
            logger.error(f"Error fatal en scraping de {self.source_name}: {e}")
            raise

        finally:
            try:
                await self.close_browser()
            finally:
                if self.lock_acquired:
                    release_source_lock(self.lock_session, self.source_name)
                    self.lock_session.close()
                    self.lock_session = None
                    self.lock_acquired = False
