"""Operaciones de escritura idempotente para datos de scraping."""

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from dtc.db.models import DataSource, ListingImage, RawListing, ScrapingRun
from dtc.storage.gcs import GCSImageStorage, StoredImage

logger = logging.getLogger(__name__)


RAW_FIELDS = {
    "external_id",
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


def upsert_raw_listing(
    session: Session,
    source: DataSource,
    listing_data: dict,
    storage: GCSImageStorage,
) -> bool:
    capture_date = _parse_capture_date(listing_data["capture_date"])
    external_id = listing_data.get("external_id")

    query = session.query(RawListing).filter(
        RawListing.source_id == source.id,
        RawListing.capture_date == capture_date,
    )
    if external_id:
        query = query.filter(RawListing.external_id == external_id)
    else:
        query = query.filter(RawListing.url == listing_data["url"])

    existing = query.first()
    payload = {
        key: listing_data.get(key)
        for key in RAW_FIELDS
        if key in listing_data
    }
    payload["source_id"] = source.id
    payload["capture_date"] = capture_date
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
    storage: GCSImageStorage,
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
            stored = StoredImage(
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


def _default_base_url(source_name: str) -> str:
    return {
        "CRAutos": "https://www.crautos.com",
        "Encuentra24": "https://www.encuentra24.com",
    }.get(source_name, "")
