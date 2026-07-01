"""Operaciones de escritura idempotente para datos de scraping."""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from dtc.db.models import DataSource, ListingImage, RawListing, ScrapingRun

if TYPE_CHECKING:
    from dtc.storage.gcs import GCSImageStorage

logger = logging.getLogger(__name__)


@dataclass
class StoredImageFallback:
    source_url: str
    storage_url: str
    storage_path: Optional[str]
    content_type: Optional[str]
    checksum: Optional[str]


RAW_FIELDS = {
    "external_id",
    "listing_key",
    "url",
    "raw_brand",
    "raw_model",
    "raw_year",
    "raw_km",
    "raw_price",
    "raw_currency",
    "raw_body_style",
    "raw_drivetrain",
    "raw_transmission",
    "raw_fuel",
    "raw_seller_type",
    "raw_exterior_color",
    "raw_interior_color",
    "raw_trim",
    "raw_description",
    "raw_photos",
    "norm_brand",
    "norm_model",
    "norm_year",
    "norm_km",
    "norm_price_usd",
    "norm_body_style",
    "norm_drivetrain",
    "norm_transmission",
    "norm_fuel",
    "norm_seller_type",
    "norm_exterior_color",
    "norm_trim",
}


def ensure_data_source(session: Session, source_name: str) -> DataSource:
    source = session.query(DataSource).filter_by(name=source_name).first()
    if source:
        return source

    source = DataSource(
        name=source_name,
        base_url=_default_base_url(source_name),
        search_url_template="",
        scraper_module=f"dtc.scrapers.{source_name.lower()}_scraper",
        is_active=True,
    )
    session.add(source)
    session.flush()
    return source


def start_scraping_run(session: Session, source: DataSource) -> ScrapingRun:
    run = ScrapingRun(
        source_id=source.id,
        run_date=date.today(),
        started_at=datetime.now(),
        status="running",
    )
    session.add(run)
    session.flush()
    return run


def mark_abandoned_runs(session: Session, source: DataSource) -> int:
    abandoned = (
        session.query(ScrapingRun)
        .filter(
            ScrapingRun.source_id == source.id,
            ScrapingRun.status == "running",
        )
        .all()
    )
    for run in abandoned:
        run.finished_at = datetime.now()
        run.status = "failed"
        run.error_details = (
            "Corrida marcada como abandonada al iniciar una nueva corrida. "
            "Probablemente el proceso anterior fue terminado antes de finalizar."
        )
    return len(abandoned)


def finish_scraping_run(
    session: Session,
    run: ScrapingRun,
    stats: dict,
    status: str,
    error_details: Optional[str] = None,
) -> None:
    run.finished_at = datetime.now()
    run.status = status
    run.total_pages = stats.get("total_pages", 0)
    run.total_listings = stats.get("total_listings", 0)
    run.new_listings = stats.get("new_listings", 0)
    run.errors = stats.get("errors", 0)
    run.error_details = error_details


def acquire_source_lock(session: Session, source_name: str, timeout_seconds: int = 1) -> bool:
    lock_name = f"market-monitor:{source_name.lower()}"
    acquired = session.execute(
        text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
        {"lock_name": lock_name, "timeout_seconds": timeout_seconds},
    ).scalar()
    return acquired == 1


def release_source_lock(session: Session, source_name: str) -> None:
    lock_name = f"market-monitor:{source_name.lower()}"
    session.execute(
        text("SELECT RELEASE_LOCK(:lock_name)"),
        {"lock_name": lock_name},
    )


def upsert_raw_listing(
    session: Session,
    source: DataSource,
    listing_data: dict,
    storage: "GCSImageStorage",
) -> bool:
    capture_date = _parse_capture_date(listing_data["capture_date"])
    listing_key = build_listing_key(source.name, listing_data)

    query = session.query(RawListing).filter(
        RawListing.source_id == source.id,
        RawListing.listing_key == listing_key,
        RawListing.capture_date == capture_date,
    )

    existing = query.first()
    payload = {
        key: listing_data.get(key)
        for key in RAW_FIELDS
        if key in listing_data
    }
    payload["source_id"] = source.id
    payload["capture_date"] = capture_date
    payload["listing_key"] = listing_key
    payload["is_normalized"] = bool(listing_data.get("norm_brand") or listing_data.get("norm_model"))

    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        listing = existing
        inserted = False
    else:
        listing = RawListing(**payload)
        session.add(listing)
        session.flush()
        inserted = True

    _upsert_listing_images(session, listing, listing_data, storage)
    return inserted


def _upsert_listing_images(
    session: Session,
    listing: RawListing,
    listing_data: dict,
    storage: "GCSImageStorage",
) -> None:
    photos = listing_data.get("raw_photos") or []
    external_id = listing_data.get("external_id") or str(listing.id)
    capture_date = str(listing_data["capture_date"])

    for idx, image_url in enumerate(photos):
        exists = session.query(ListingImage).filter_by(
            raw_listing_id=listing.id,
            source_url=image_url,
        ).first()
        if exists:
            continue

        try:
            stored = storage.store_listing_image(
                source_name=listing_data["source_name"],
                external_id=external_id,
                capture_date=capture_date,
                image_url=image_url,
                image_order=idx,
            )
        except Exception as exc:
            logger.warning("No se pudo subir imagen %s: %s", image_url, exc)
            stored = StoredImageFallback(
                source_url=image_url,
                storage_url=image_url,
                storage_path=None,
                content_type=None,
                checksum=None,
            )

        session.add(ListingImage(
            raw_listing_id=listing.id,
            source_url=stored.source_url,
            storage_url=stored.storage_url,
            storage_path=stored.storage_path,
            content_type=stored.content_type,
            image_order=idx,
            checksum=stored.checksum,
        ))


def _parse_capture_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def build_listing_key(source_name: str, listing_data: dict) -> str:
    """
    Crea una llave estable y no nula para deduplicar un anuncio por fuente.
    Preferimos external_id; si falta, usamos URL canónica sin parámetros de tracking.
    """
    external_id = (listing_data.get("external_id") or "").strip()
    if external_id:
        raw_key = f"{source_name.lower()}|external|{external_id}"
    else:
        raw_key = f"{source_name.lower()}|url|{canonicalize_listing_url(listing_data['url'])}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def canonicalize_listing_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query_params = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "msclkid"}
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        urlencode(sorted(query_params)),
        "",
    ))


def _default_base_url(source_name: str) -> str:
    return {
        "CRAutos": "https://www.crautos.com",
        "Encuentra24": "https://www.encuentra24.com",
    }.get(source_name, "")
