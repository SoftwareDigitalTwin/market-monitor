"""
BaseScraper V2.

Separa explícitamente:
- discovery/presence: recorrer índices y obtener referencias livianas;
- detail scrape: abrir únicamente anuncios nuevos o que reaparecen;
- lifecycle de fuente: reconciliar presencia con guardas de seguridad.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from types import SimpleNamespace
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, async_playwright

from dtc.collector.service import (
    bootstrap_source_listings_from_raw,
    mark_detail_scraped,
    reconcile_manifest,
    update_scan_detail_count,
)
from dtc.collector.types import ListingRef
from dtc.config.settings import PROCESSED_DIR, config
from dtc.db.database import SessionLocal, get_session
from dtc.db.models import ScrapingRun
from dtc.db.repository import (
    acquire_source_lock,
    build_listing_key,
    ensure_data_source,
    finish_scraping_run,
    mark_abandoned_runs,
    release_source_lock,
    start_scraping_run,
    upsert_raw_listing_record,
)
from dtc.normalizer.normalizer import normalize_listing

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Clase base para cualquier fuente de anuncios automotrices."""

    def __init__(self, source_name: str, limit: Optional[int] = None):
        self.source_name = source_name
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.scraping_run_id: Optional[int] = None
        self.lock_acquired = False
        self.lock_session = None
        self.config = config.scraper
        self.limit = limit
        self.listings: list[dict] = []
        self.error_messages: list[str] = []

        # Las implementaciones de discovery deben cambiar estos valores cuando
        # terminan por timeout, límite o max_pages, para impedir falsas salidas.
        self.discovery_complete = True
        self.discovery_stop_reason: str | None = None

        self.stats = {
            "total_pages": 0,
            "total_listings": 0,
            "new_listings": 0,
            "reappeared_listings": 0,
            "missing_suspected": 0,
            "inactive_confirmed": 0,
            "detail_scraped": 0,
            "errors": 0,
        }

    async def start_browser(self):
        if self.playwright or self.browser or self.page:
            await self.close_browser()
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
        logger.info("Navegador iniciado para %s", self.source_name)

    async def close_browser(self):
        if self.browser:
            try:
                if self.browser.is_connected():
                    await self.browser.close()
            except Exception as exc:
                logger.debug("No se pudo cerrar browser limpio: %s", exc)
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as exc:
                logger.debug("No se pudo detener Playwright limpio: %s", exc)
        self.page = None
        self.browser = None
        self.playwright = None
        logger.info("Navegador cerrado para %s", self.source_name)

    def _browser_is_alive(self) -> bool:
        if not self.browser or not self.page:
            return False
        try:
            return self.browser.is_connected() and not self.page.is_closed()
        except Exception:
            return False

    async def ensure_browser_alive(self):
        if self._browser_is_alive():
            return
        logger.warning(
            "Navegador no disponible para %s; reiniciando.", self.source_name
        )
        await self.start_browser()

    def _start_run(self) -> int:
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
            bootstrap_source_listings_from_raw(session, source)
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
        logger.info("Corrida iniciada: ID=%s", run_id)
        return run_id

    def _finish_run(self, status: str = "completed", error_details: str = None):
        if not self.scraping_run_id:
            return
        with get_session() as session:
            run = session.get(ScrapingRun, self.scraping_run_id)
            if run:
                finish_scraping_run(session, run, self.stats, status, error_details)

        logger.info(
            "Corrida finalizada: %s | páginas=%s vistos=%s nuevos=%s "
            "reaparecidos=%s missing=%s inactivos=%s detalle=%s errores=%s",
            status,
            self.stats["total_pages"],
            self.stats["total_listings"],
            self.stats["new_listings"],
            self.stats["reappeared_listings"],
            self.stats["missing_suspected"],
            self.stats["inactive_confirmed"],
            self.stats["detail_scraped"],
            self.stats["errors"],
        )

    def _add_listing(self, listing_data: dict) -> dict:
        try:
            normalized = normalize_listing(SimpleNamespace(**listing_data))
        except Exception as exc:
            logger.error("Error normalizando anuncio: %s", exc)
            normalized = {}

        record = {**listing_data, **normalized}
        self.listings.append(record)
        return record

    def _persist_listing(self, listing_data: dict) -> bool:
        """Persiste el detalle y enlaza el snapshot con SourceListing."""
        with get_session() as session:
            source = ensure_data_source(session, self.source_name)
            raw_listing, inserted = upsert_raw_listing_record(
                session, source, listing_data
            )
            listing_key = build_listing_key(self.source_name, listing_data)
            mark_detail_scraped(
                session,
                source_id=source.id,
                listing_key=listing_key,
                raw_listing_id=raw_listing.id,
                scraped_date=date.today(),
            )
        return inserted

    def _record_error(self, message: str, exc: Exception = None):
        self.stats["errors"] += 1
        detail = f"{message}: {exc}" if exc else message
        self.error_messages.append(detail[:1000])

    def _save_to_json(self) -> str:
        """Backup solo de detalles procesados; no del manifiesto completo."""
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        filename = PROCESSED_DIR / f"{self.source_name.lower()}_{today}.json"
        payload = {
            "source": self.source_name,
            "capture_date": today,
            "stats": self.stats,
            "listings": self.listings,
        }
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
        logger.info("JSON guardado en %s (%s detalles)", filename, len(self.listings))
        return str(filename)

    async def get_page_soup(self, url: str) -> BeautifulSoup:
        await self.ensure_browser_alive()
        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(self.config.delay_between_requests)
        html = await self.page.content()
        return BeautifulSoup(html, "html.parser")

    def extract_external_id(self, url: str) -> str | None:
        """
        Hook genérico. Las fuentes actuales ya implementan _extract_external_id.
        Fuentes futuras pueden sobrescribir este método directamente.
        """
        extractor = getattr(self, "_extract_external_id", None)
        if callable(extractor):
            return extractor(url)
        return None

    def make_listing_ref(self, url: str) -> ListingRef:
        external_id = self.extract_external_id(url)
        key = build_listing_key(
            self.source_name,
            {"external_id": external_id, "url": url},
        )
        return ListingRef(listing_key=key, url=url, external_id=external_id)

    async def _process_listing_ref(self, ref: ListingRef) -> bool:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                await self.ensure_browser_alive()
                listing_data = await self.parse_listing(ref.url)
                if listing_data:
                    listing_data["source_name"] = self.source_name
                    listing_data["capture_date"] = date.today().isoformat()
                    listing_data["url"] = ref.url
                    listing_data["external_id"] = (
                        listing_data.get("external_id") or ref.external_id
                    )
                    record = self._add_listing(listing_data)
                    self._persist_listing(record)
                    self.stats["detail_scraped"] += 1
                    return True

                if not self._browser_is_alive() and attempt < self.config.max_retries:
                    continue
                self._record_error(f"No se pudo parsear {ref.url}")
                return False
            except Exception as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    logger.warning(
                        "Error procesando %s; reintento %s/%s: %s",
                        ref.url,
                        attempt + 1,
                        self.config.max_retries,
                        exc,
                    )
                    if not self._browser_is_alive():
                        await self.close_browser()
                    continue
                break

        self._record_error(f"Error procesando {ref.url}", last_error)
        return False

    @abstractmethod
    async def get_listing_urls(self) -> list[str]:
        """Obtiene referencias livianas de los anuncios visibles en la fuente."""
        raise NotImplementedError

    @abstractmethod
    async def parse_listing(self, url: str) -> Optional[dict]:
        """Extrae el detalle de un anuncio individual."""
        raise NotImplementedError

    @abstractmethod
    def build_search_url(self, page_number: int) -> str:
        raise NotImplementedError

    async def run(self):
        """
        Collector V2:
        1. index scan completo;
        2. reconciliación de presencia;
        3. detalle solo para nuevos y reaparecidos;
        4. ausencias solo si el scan es completo y supera safety guards.
        """
        self._start_run()

        try:
            await self.start_browser()
            logger.info("Discovery de %s...", self.source_name)
            listing_urls = await self.get_listing_urls()

            # Cualquier limit de prueba convierte el scan en parcial por definición.
            if self.limit is not None:
                listing_urls = listing_urls[: self.limit]
                self.discovery_complete = False
                self.discovery_stop_reason = "test_limit"

            refs = [self.make_listing_ref(url) for url in listing_urls]
            refs = list({ref.listing_key: ref for ref in refs}.values())
            self.stats["total_listings"] = len(refs)

            with get_session() as session:
                source = ensure_data_source(session, self.source_name)
                run = session.get(ScrapingRun, self.scraping_run_id)
                resolution = reconcile_manifest(
                    session,
                    source=source,
                    run=run,
                    refs=refs,
                    scan_date=date.today(),
                    discovery_complete=self.discovery_complete,
                    stop_reason=self.discovery_stop_reason,
                )

            self.stats["new_listings"] = len(resolution.new_refs)
            self.stats["reappeared_listings"] = len(resolution.reappeared_refs)
            self.stats["missing_suspected"] = resolution.missing_suspected_count
            self.stats["inactive_confirmed"] = resolution.inactive_confirmed_count

            all_detail_refs = resolution.detail_refs
            detail_cap = config.collector.max_detail_scrapes_per_run
            detail_refs = all_detail_refs[:detail_cap] if detail_cap > 0 else all_detail_refs
            logger.info(
                "%s: vistos=%s nuevos=%s reaparecidos=%s pendientes_detalle=%s "
                "detalle_esta_corrida=%s",
                self.source_name,
                resolution.seen_count,
                len(resolution.new_refs),
                len(resolution.reappeared_refs),
                len(all_detail_refs),
                len(detail_refs),
            )

            for index, ref in enumerate(detail_refs, 1):
                logger.info("[%s/%s] Detalle: %s", index, len(detail_refs), ref.url)
                await self._process_listing_ref(ref)
                await asyncio.sleep(self.config.delay_between_requests)

            with get_session() as session:
                update_scan_detail_count(
                    session,
                    self.scraping_run_id,
                    self.stats["detail_scraped"],
                )

            if config.save_json_backup and self.listings:
                self._save_to_json()

            status = "completed" if self.discovery_complete else "partial"
            error_details = "\n".join(self.error_messages[-10:]) or None
            if not self.discovery_complete:
                reason = self.discovery_stop_reason or "discovery_incomplete"
                error_details = f"Discovery parcial: {reason}" + (
                    f"\n{error_details}" if error_details else ""
                )
            if self.stats["errors"] and not refs:
                status = "failed"
                error_details = error_details or "La corrida terminó sin referencias y con errores."

            self._finish_run(status=status, error_details=error_details)

        except Exception as exc:
            self._record_error("Error fatal en collector", exc)
            self._finish_run(status="failed", error_details=str(exc))
            logger.error("Error fatal en %s: %s", self.source_name, exc)
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
