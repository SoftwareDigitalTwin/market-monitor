from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from dtc.collector.types import ListingRef, ManifestResolution
from dtc.config.settings import config
from dtc.db.models import (
    DataSource,
    RawListing,
    ScrapingRun,
    SourceListing,
    SourceListingEvent,
    SourceListingEventType,
    SourceListingStatus,
    SourceScanMetric,
)

logger = logging.getLogger(__name__)


def _chunks(values: list[str], size: int = 1500) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _event(
    session: Session,
    source_listing_id: int,
    run_id: int | None,
    event_type: str,
    detected_date: date,
    event_data: dict | None = None,
) -> None:
    session.add(
        SourceListingEvent(
            source_listing_id=source_listing_id,
            run_id=run_id,
            event_type=event_type,
            detected_date=detected_date,
            event_data=event_data,
        )
    )


def _view_history_with_scan(
    view_history: dict | None,
    scan_date: date,
    seen_count: int,
) -> dict:
    history = dict(view_history or {})
    date_key = scan_date.isoformat()
    history[date_key] = int(history.get(date_key, 0) or 0) + int(seen_count)
    return history


def bootstrap_source_listings_from_raw(
    session: Session,
    source: DataSource,
) -> int:
    """
    Crea el baseline de SourceListing usando la data existente.

    Se ejecuta una sola vez por fuente: si ya existe al menos un SourceListing,
    no hace nada. Esto evita que el primer Collector V2 vuelva a abrir el detalle
    de todos los anuncios que ya fueron capturados por el sistema anterior.
    """
    existing_count = (
        session.query(func.count(SourceListing.id))
        .filter(SourceListing.source_id == source.id)
        .scalar()
        or 0
    )
    if existing_count:
        return 0

    rows = (
        session.query(RawListing)
        .filter(RawListing.source_id == source.id)
        .order_by(RawListing.capture_date.asc(), RawListing.id.asc())
        .yield_per(2000)
    )

    by_key: dict[str, dict] = {}
    for row in rows:
        current = by_key.get(row.listing_key)
        if current is None:
            by_key[row.listing_key] = {
                "external_id": row.external_id,
                "canonical_url": row.url,
                "first_seen_date": row.capture_date,
                "last_seen_date": row.capture_date,
                "view_history": {row.capture_date.isoformat(): 1},
                "latest_raw_listing_id": row.id,
                "detail_last_scraped_date": row.capture_date,
            }
            continue

        current["view_history"] = _view_history_with_scan(
            current.get("view_history"),
            row.capture_date,
            1,
        )
        if row.capture_date < current["first_seen_date"]:
            current["first_seen_date"] = row.capture_date
        if row.capture_date >= current["last_seen_date"]:
            current["last_seen_date"] = row.capture_date
            current["external_id"] = row.external_id
            current["canonical_url"] = row.url
            current["latest_raw_listing_id"] = row.id
            current["detail_last_scraped_date"] = row.capture_date

    if not by_key:
        return 0

    objects = [
        SourceListing(
            source_id=source.id,
            listing_key=listing_key,
            external_id=data["external_id"],
            canonical_url=data["canonical_url"],
            status=SourceListingStatus.ACTIVE.value,
            missing_streak=0,
            reappearance_count=0,
            first_seen_date=data["first_seen_date"],
            last_seen_date=data["last_seen_date"],
            view_history=data["view_history"],
            latest_raw_listing_id=data["latest_raw_listing_id"],
            detail_last_scraped_date=data["detail_last_scraped_date"],
        )
        for listing_key, data in by_key.items()
    ]
    session.bulk_save_objects(objects)
    session.flush()
    logger.info(
        "Bootstrap Source Collector V2 para %s: %s anuncios importados",
        source.name,
        len(objects),
    )
    return len(objects)


def reconcile_manifest(
    session: Session,
    *,
    source: DataSource,
    run: ScrapingRun,
    refs: list[ListingRef],
    scan_date: date,
    discovery_complete: bool,
    stop_reason: str | None,
) -> ManifestResolution:
    """
    Reconcilia el conjunto de anuncios vistos con el estado persistente.

    La función hace cuatro cosas:
    1. Marca como vistos los anuncios ya conocidos.
    2. Crea SourceListing para anuncios nuevos.
    3. Reactiva anuncios que reaparecieron.
    4. Solo si el scan es completo y pasa la guarda de cobertura, incrementa
       ausencias y confirma inactividad.
    """
    view_counts_by_key: dict[str, int] = {}
    unique_by_key: dict[str, ListingRef] = {}
    for ref in refs:
        view_counts_by_key[ref.listing_key] = view_counts_by_key.get(ref.listing_key, 0) + 1
        unique_by_key[ref.listing_key] = ref
    refs = list(unique_by_key.values())
    result = ManifestResolution(seen_count=len(refs))

    active_states = [
        SourceListingStatus.ACTIVE.value,
        SourceListingStatus.MISSING_SUSPECTED.value,
    ]
    result.baseline_active = (
        session.query(func.count(SourceListing.id))
        .filter(
            SourceListing.source_id == source.id,
            SourceListing.status.in_(active_states),
        )
        .scalar()
        or 0
    )

    existing_by_key: dict[str, SourceListing] = {}
    keys = list(unique_by_key)
    for chunk in _chunks(keys):
        rows = (
            session.query(SourceListing)
            .filter(
                SourceListing.source_id == source.id,
                SourceListing.listing_key.in_(chunk),
            )
            .all()
        )
        existing_by_key.update({row.listing_key: row for row in rows})

    new_rows_for_events: list[SourceListing] = []

    for ref in refs:
        row = existing_by_key.get(ref.listing_key)
        if row is None:
            row = SourceListing(
                source_id=source.id,
                listing_key=ref.listing_key,
                external_id=ref.external_id,
                canonical_url=ref.url,
                status=SourceListingStatus.ACTIVE.value,
                missing_streak=0,
                reappearance_count=0,
                first_seen_date=scan_date,
                last_seen_date=scan_date,
                view_history={
                    scan_date.isoformat(): view_counts_by_key.get(ref.listing_key, 1)
                },
                last_seen_run_id=run.id,
            )
            session.add(row)
            new_rows_for_events.append(row)
            result.new_refs.append(ref)
            continue

        old_url = row.canonical_url
        row.last_seen_date = scan_date
        row.last_seen_run_id = run.id
        row.external_id = ref.external_id or row.external_id
        row.canonical_url = ref.url
        row.view_history = _view_history_with_scan(
            row.view_history,
            scan_date,
            view_counts_by_key.get(ref.listing_key, 1),
        )

        if old_url != ref.url:
            _event(
                session,
                row.id,
                run.id,
                SourceListingEventType.URL_CHANGED.value,
                scan_date,
                {"old_url": old_url, "new_url": ref.url},
            )

        if row.status != SourceListingStatus.ACTIVE.value:
            previous_status = row.status
            row.status = SourceListingStatus.ACTIVE.value
            row.missing_streak = 0
            row.inactive_at = None
            row.detail_last_scraped_date = None
            row.reappearance_count = (row.reappearance_count or 0) + 1
            _event(
                session,
                row.id,
                run.id,
                SourceListingEventType.REAPPEARED.value,
                scan_date,
                {"previous_status": previous_status},
            )
            result.reappeared_refs.append(ref)
        else:
            row.missing_streak = 0
            if row.detail_last_scraped_date is None:
                result.pending_detail_refs.append(ref)

    if new_rows_for_events:
        session.flush()
        for row in new_rows_for_events:
            _event(
                session,
                row.id,
                run.id,
                SourceListingEventType.FIRST_SEEN.value,
                scan_date,
            )

    collector_cfg = config.collector
    baseline = result.baseline_active
    coverage_ratio = (len(refs) / baseline) if baseline else 1.0
    enough_coverage = (
        baseline < collector_cfg.safety_min_baseline
        or coverage_ratio >= collector_cfg.min_coverage_ratio
    )
    result.safety_passed = bool(discovery_complete and enough_coverage)

    if result.safety_passed:
        missing_rows = (
            session.query(SourceListing)
            .filter(
                SourceListing.source_id == source.id,
                SourceListing.status.in_(active_states),
                (
                    SourceListing.last_seen_run_id.is_(None)
                    | (SourceListing.last_seen_run_id != run.id)
                ),
            )
            .all()
        )

        for row in missing_rows:
            row.missing_streak = (row.missing_streak or 0) + 1

            if row.missing_streak >= collector_cfg.inactive_confirm_scans:
                if row.status != SourceListingStatus.INACTIVE_CONFIRMED.value:
                    row.status = SourceListingStatus.INACTIVE_CONFIRMED.value
                    row.inactive_at = scan_date
                    _event(
                        session,
                        row.id,
                        run.id,
                        SourceListingEventType.INACTIVE_CONFIRMED.value,
                        scan_date,
                        {"missing_streak": row.missing_streak},
                    )
                    result.inactive_confirmed_count += 1
            elif row.status == SourceListingStatus.ACTIVE.value:
                row.status = SourceListingStatus.MISSING_SUSPECTED.value
                _event(
                    session,
                    row.id,
                    run.id,
                    SourceListingEventType.MISSING_SUSPECTED.value,
                    scan_date,
                    {"missing_streak": row.missing_streak},
                )
                result.missing_suspected_count += 1
    else:
        logger.warning(
            "No se aplican ausencias para %s. complete=%s baseline=%s seen=%s "
            "coverage=%.3f min=%.3f stop_reason=%s",
            source.name,
            discovery_complete,
            baseline,
            len(refs),
            coverage_ratio,
            collector_cfg.min_coverage_ratio,
            stop_reason,
        )

    metric = SourceScanMetric(
        run_id=run.id,
        source_id=source.id,
        scan_date=scan_date,
        discovery_complete=discovery_complete,
        safety_passed=result.safety_passed,
        stop_reason=stop_reason,
        baseline_active=result.baseline_active,
        seen_count=result.seen_count,
        new_count=len(result.new_refs),
        reappeared_count=len(result.reappeared_refs),
        missing_suspected_count=result.missing_suspected_count,
        inactive_confirmed_count=result.inactive_confirmed_count,
        detail_scraped_count=0,
    )
    session.add(metric)
    session.flush()

    return result


def update_scan_detail_count(session: Session, run_id: int, detail_count: int) -> None:
    metric = session.query(SourceScanMetric).filter_by(run_id=run_id).first()
    if metric:
        metric.detail_scraped_count = detail_count


def mark_detail_scraped(
    session: Session,
    *,
    source_id: int,
    listing_key: str,
    raw_listing_id: int,
    scraped_date: date,
) -> None:
    row = (
        session.query(SourceListing)
        .filter(
            SourceListing.source_id == source_id,
            SourceListing.listing_key == listing_key,
        )
        .first()
    )
    if not row:
        return
    row.latest_raw_listing_id = raw_listing_id
    row.detail_last_scraped_date = scraped_date
