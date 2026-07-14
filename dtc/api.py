"""API de lectura para consumir datos del monitor de mercado."""

from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from dtc.config.settings import config
from dtc.db.database import get_session
from dtc.db.models import (
    DataSource,
    RawListing,
    ScrapingRun,
    SourceListing,
    SourceScanMetric,
)

app = FastAPI(title="DTC Market Monitor API", version="1.0.0")


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    api_keys = config.api.api_keys
    if not api_keys:
        raise HTTPException(
            status_code=503,
            detail="API authentication is not configured. Set DTC_API_KEYS.",
        )
    if x_api_key not in api_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/check", dependencies=[Depends(require_api_key)])
def auth_check():
    return {"authenticated": True}


@app.get("/sources", dependencies=[Depends(require_api_key)])
def list_sources():
    with get_session() as session:
        sources = session.query(DataSource).order_by(DataSource.name).all()
        return [
            {
                "id": source.id,
                "name": source.name,
                "base_url": source.base_url,
                "is_active": source.is_active,
            }
            for source in sources
        ]


@app.get("/listings", dependencies=[Depends(require_api_key)])
def list_listings(
    source: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    latest_only: bool = True,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        query = _filtered_raw_listing_query(
            session,
            source=source,
            brand=brand,
            model=model,
            year=year,
            date_from=date_from,
            date_to=date_to,
        )

        if latest_only:
            latest_ids = (
                query.with_entities(func.max(RawListing.id).label("id"))
                .group_by(RawListing.source_id, RawListing.listing_key)
                .subquery()
            )
            query = (
                session.query(RawListing)
                .join(DataSource)
                .options(selectinload(RawListing.source))
                .filter(RawListing.id.in_(select(latest_ids.c.id)))
            )

        query = query.order_by(RawListing.capture_date.desc(), RawListing.id.desc())

        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "latest_only": latest_only,
            "items": [_listing_summary(row) for row in rows],
        }


def _filtered_raw_listing_query(
    session,
    *,
    source: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    query = (
        session.query(RawListing)
        .join(DataSource)
        .options(selectinload(RawListing.source))
    )
    if source:
        query = query.filter(DataSource.name == source)
    if brand:
        query = query.filter(RawListing.norm_brand == brand)
    if model:
        query = query.filter(RawListing.norm_model == model)
    if year:
        query = query.filter(RawListing.norm_year == year)
    if date_from:
        query = query.filter(RawListing.capture_date >= date_from)
    if date_to:
        query = query.filter(RawListing.capture_date <= date_to)
    return query


@app.get("/listings/{listing_id}", dependencies=[Depends(require_api_key)])
def get_listing(listing_id: int):
    with get_session() as session:
        listing = (
            session.query(RawListing)
            .options(selectinload(RawListing.source))
            .filter(RawListing.id == listing_id)
            .first()
        )
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found")
        data = _listing_summary(listing)
        data.update({
            "raw": {
                "brand": listing.raw_brand,
                "model": listing.raw_model,
                "year": listing.raw_year,
                "km": listing.raw_km,
                "price": listing.raw_price,
                "currency": listing.raw_currency,
                "body_style": listing.raw_body_style,
                "drivetrain": listing.raw_drivetrain,
                "transmission": listing.raw_transmission,
                "fuel": listing.raw_fuel,
                "seller_type": listing.raw_seller_type,
                "exterior_color": listing.raw_exterior_color,
                "interior_color": listing.raw_interior_color,
                "trim": listing.raw_trim,
                "description": listing.raw_description,
                "photos": listing.raw_photos,
            }
        })
        return data


@app.get("/runs", dependencies=[Depends(require_api_key)])
def list_runs(limit: int = Query(50, ge=1, le=200)):
    with get_session() as session:
        runs = (
            session.query(ScrapingRun)
            .join(DataSource)
            .options(selectinload(ScrapingRun.source))
            .order_by(ScrapingRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": run.id,
                "source": run.source.name,
                "run_date": run.run_date,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "status": run.status,
                "total_pages": run.total_pages,
                "total_listings": run.total_listings,
                "new_listings": run.new_listings,
                "errors": run.errors,
                "error_details": run.error_details,
            }
            for run in runs
        ]


@app.get("/collector/summary", dependencies=[Depends(require_api_key)])
def collector_summary():
    with get_session() as session:
        rows = (
            session.query(
                DataSource.name.label("source"),
                SourceListing.status.label("status"),
                func.count(SourceListing.id).label("count"),
            )
            .join(SourceListing, SourceListing.source_id == DataSource.id)
            .group_by(DataSource.name, SourceListing.status)
            .order_by(DataSource.name, SourceListing.status)
            .all()
        )
        return {
            "by_source_status": [
                {"source": row.source, "status": row.status, "count": int(row.count)}
                for row in rows
            ]
        }


@app.get("/collector/listings", dependencies=[Depends(require_api_key)])
def collector_listings(
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        query = (
            session.query(SourceListing, DataSource.name)
            .join(DataSource, SourceListing.source_id == DataSource.id)
            .order_by(SourceListing.last_seen_date.desc(), SourceListing.id.desc())
        )
        if source:
            query = query.filter(DataSource.name == source)
        if status:
            query = query.filter(SourceListing.status == status)
        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": listing.id,
                    "source": source_name,
                    "external_id": listing.external_id,
                    "url": listing.canonical_url,
                    "status": listing.status,
                    "missing_streak": listing.missing_streak,
                    "first_seen_date": listing.first_seen_date,
                    "last_seen_date": listing.last_seen_date,
                    "view_history": listing.view_history or {},
                    "total_views": sum((listing.view_history or {}).values()),
                    "inactive_at": listing.inactive_at,
                    "reappearance_count": listing.reappearance_count,
                    "detail_last_scraped_date": listing.detail_last_scraped_date,
                }
                for listing, source_name in rows
            ],
        }


@app.get("/inventory/summary", dependencies=[Depends(require_api_key)])
def inventory_summary():
    """Resumen del inventario único por fuente y estado de presencia."""
    with get_session() as session:
        rows = (
            session.query(
                DataSource.name.label("source"),
                SourceListing.status.label("status"),
                func.count(SourceListing.id).label("count"),
            )
            .join(DataSource, SourceListing.source_id == DataSource.id)
            .group_by(DataSource.name, SourceListing.status)
            .order_by(DataSource.name, SourceListing.status)
            .all()
        )
        totals = (
            session.query(
                DataSource.name.label("source"),
                func.count(SourceListing.id).label("unique_listings"),
            )
            .join(DataSource, SourceListing.source_id == DataSource.id)
            .group_by(DataSource.name)
            .order_by(DataSource.name)
            .all()
        )
        return {
            "totals": [
                {"source": row.source, "unique_listings": int(row.unique_listings)}
                for row in totals
            ],
            "by_source_status": [
                {"source": row.source, "status": row.status, "count": int(row.count)}
                for row in rows
            ],
        }


@app.get("/inventory/listings", dependencies=[Depends(require_api_key)])
def inventory_listings(
    source: Optional[str] = None,
    status: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Inventario canónico: una fila por anuncio único.

    `raw_listings` conserva evidencia histórica; este endpoint consume
    `source_listings` y adjunta el último snapshot disponible.
    """
    with get_session() as session:
        query = (
            session.query(SourceListing, DataSource.name, RawListing)
            .join(DataSource, SourceListing.source_id == DataSource.id)
            .outerjoin(RawListing, SourceListing.latest_raw_listing_id == RawListing.id)
            .order_by(SourceListing.last_seen_date.desc(), SourceListing.id.desc())
        )
        if source:
            query = query.filter(DataSource.name == source)
        if status:
            query = query.filter(SourceListing.status == status)
        if brand:
            query = query.filter(RawListing.norm_brand == brand)
        if model:
            query = query.filter(RawListing.norm_model == model)
        if year:
            query = query.filter(RawListing.norm_year == year)

        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                _inventory_payload(listing, source_name, latest_detail)
                for listing, source_name, latest_detail in rows
            ],
        }


@app.get("/collector/runs", dependencies=[Depends(require_api_key)])
def collector_runs(limit: int = Query(50, ge=1, le=200)):
    with get_session() as session:
        rows = (
            session.query(SourceScanMetric, ScrapingRun, DataSource.name)
            .join(ScrapingRun, SourceScanMetric.run_id == ScrapingRun.id)
            .join(DataSource, SourceScanMetric.source_id == DataSource.id)
            .order_by(ScrapingRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "run_id": run.id,
                "source": source_name,
                "scan_date": metric.scan_date,
                "run_status": run.status,
                "discovery_complete": metric.discovery_complete,
                "safety_passed": metric.safety_passed,
                "stop_reason": metric.stop_reason,
                "baseline_active": metric.baseline_active,
                "seen_count": metric.seen_count,
                "new_count": metric.new_count,
                "reappeared_count": metric.reappeared_count,
                "missing_suspected_count": metric.missing_suspected_count,
                "inactive_confirmed_count": metric.inactive_confirmed_count,
                "detail_scraped_count": metric.detail_scraped_count,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
            for metric, run, source_name in rows
        ]


@app.get("/analytics/summary", dependencies=[Depends(require_api_key)])
def analytics_summary(capture_date: Optional[date] = None):
    with get_session() as session:
        query = session.query(RawListing)
        if capture_date:
            query = query.filter(RawListing.capture_date == capture_date)

        by_brand = (
            query.with_entities(
                RawListing.norm_brand.label("brand"),
                func.count(RawListing.id).label("count"),
                func.avg(RawListing.norm_price_usd).label("avg_price_usd"),
            )
            .filter(RawListing.norm_brand.isnot(None))
            .group_by(RawListing.norm_brand)
            .order_by(func.count(RawListing.id).desc())
            .limit(25)
            .all()
        )
        return {
            "capture_date": capture_date,
            "total_listings": query.count(),
            "by_brand": [
                {
                    "brand": row.brand,
                    "count": int(row.count),
                    "avg_price_usd": round(float(row.avg_price_usd), 2)
                    if row.avg_price_usd is not None else None,
                }
                for row in by_brand
            ],
        }


def _listing_summary(listing: RawListing) -> dict:
    return {
        "id": listing.id,
        "source": listing.source.name,
        "external_id": listing.external_id,
        "listing_key": listing.listing_key,
        "url": listing.url,
        "capture_date": listing.capture_date,
        "brand": listing.norm_brand,
        "model": listing.norm_model,
        "year": listing.norm_year,
        "km": listing.norm_km,
        "price_usd": listing.norm_price_usd,
        "body_style": listing.norm_body_style,
        "drivetrain": listing.norm_drivetrain,
        "transmission": listing.norm_transmission,
        "fuel": listing.norm_fuel,
        "seller_type": listing.norm_seller_type,
        "exterior_color": listing.norm_exterior_color,
        "trim": listing.norm_trim,
        "photos": listing.raw_photos or [],
        "created_at": listing.created_at,
    }


def _inventory_payload(
    listing: SourceListing,
    source_name: str,
    latest_detail: Optional[RawListing],
) -> dict:
    payload = {
        "id": listing.id,
        "source": source_name,
        "listing_key": listing.listing_key,
        "external_id": listing.external_id,
        "url": listing.canonical_url,
        "status": listing.status,
        "missing_streak": listing.missing_streak,
        "first_seen_date": listing.first_seen_date,
        "last_seen_date": listing.last_seen_date,
        "view_history": listing.view_history or {},
        "total_views": sum((listing.view_history or {}).values()),
        "inactive_at": listing.inactive_at,
        "reappearance_count": listing.reappearance_count,
        "detail_last_scraped_date": listing.detail_last_scraped_date,
        "latest_raw_listing_id": listing.latest_raw_listing_id,
        "latest_detail": None,
    }
    if latest_detail:
        payload["latest_detail"] = {
            "capture_date": latest_detail.capture_date,
            "brand": latest_detail.norm_brand,
            "model": latest_detail.norm_model,
            "year": latest_detail.norm_year,
            "km": latest_detail.norm_km,
            "price_usd": latest_detail.norm_price_usd,
            "body_style": latest_detail.norm_body_style,
            "drivetrain": latest_detail.norm_drivetrain,
            "transmission": latest_detail.norm_transmission,
            "fuel": latest_detail.norm_fuel,
            "seller_type": latest_detail.norm_seller_type,
            "exterior_color": latest_detail.norm_exterior_color,
            "trim": latest_detail.norm_trim,
            "photos": latest_detail.raw_photos or [],
        }
    return payload
