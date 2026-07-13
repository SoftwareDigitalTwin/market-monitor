from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dtc.collector.service import reconcile_manifest
from dtc.collector.types import ListingRef
from dtc.config.settings import config
from dtc.db.models import (
    Base,
    DataSource,
    ScrapingRun,
    SourceListing,
    SourceListingStatus,
)


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _source_and_run(session, day: date):
    source = session.query(DataSource).first()
    if source is None:
        source = DataSource(
            name="TestSource",
            base_url="https://example.com",
            scraper_module="tests.fake_scraper",
            is_active=True,
        )
        session.add(source)
        session.flush()

    run = ScrapingRun(
        source_id=source.id,
        run_date=day,
        started_at=datetime.now(),
        status="running",
    )
    session.add(run)
    session.flush()
    return source, run


def _ref(key: str) -> ListingRef:
    return ListingRef(
        listing_key=key,
        external_id=key,
        url=f"https://example.com/car/{key}",
    )


def test_new_missing_inactive_and_reappeared():
    session = _session()
    old_threshold = config.collector.inactive_confirm_scans
    config.collector.inactive_confirm_scans = 2

    try:
        day1 = date(2026, 7, 8)
        source, run1 = _source_and_run(session, day1)
        first = reconcile_manifest(
            session,
            source=source,
            run=run1,
            refs=[_ref("A"), _ref("B")],
            scan_date=day1,
            discovery_complete=True,
            stop_reason="natural_end",
        )
        session.commit()
        assert len(first.new_refs) == 2
        assert first.safety_passed is True

        day2 = day1 + timedelta(days=1)
        source, run2 = _source_and_run(session, day2)
        second = reconcile_manifest(
            session,
            source=source,
            run=run2,
            refs=[_ref("A")],
            scan_date=day2,
            discovery_complete=True,
            stop_reason="natural_end",
        )
        session.commit()
        assert second.missing_suspected_count == 1
        row_b = session.query(SourceListing).filter_by(listing_key="B").one()
        assert row_b.status == SourceListingStatus.MISSING_SUSPECTED.value
        assert row_b.missing_streak == 1

        day3 = day2 + timedelta(days=1)
        source, run3 = _source_and_run(session, day3)
        third = reconcile_manifest(
            session,
            source=source,
            run=run3,
            refs=[_ref("A")],
            scan_date=day3,
            discovery_complete=True,
            stop_reason="natural_end",
        )
        session.commit()
        assert third.inactive_confirmed_count == 1
        session.refresh(row_b)
        assert row_b.status == SourceListingStatus.INACTIVE_CONFIRMED.value

        day4 = day3 + timedelta(days=1)
        source, run4 = _source_and_run(session, day4)
        fourth = reconcile_manifest(
            session,
            source=source,
            run=run4,
            refs=[_ref("A"), _ref("B")],
            scan_date=day4,
            discovery_complete=True,
            stop_reason="natural_end",
        )
        session.commit()
        assert len(fourth.reappeared_refs) == 1
        session.refresh(row_b)
        assert row_b.status == SourceListingStatus.ACTIVE.value
        assert row_b.missing_streak == 0
        assert row_b.reappearance_count == 1
    finally:
        config.collector.inactive_confirm_scans = old_threshold
        session.close()


def test_partial_scan_never_creates_missing_transition():
    session = _session()
    day1 = date(2026, 7, 8)
    source, run1 = _source_and_run(session, day1)
    reconcile_manifest(
        session,
        source=source,
        run=run1,
        refs=[_ref("A"), _ref("B")],
        scan_date=day1,
        discovery_complete=True,
        stop_reason="natural_end",
    )
    session.commit()

    day2 = day1 + timedelta(days=1)
    source, run2 = _source_and_run(session, day2)
    result = reconcile_manifest(
        session,
        source=source,
        run=run2,
        refs=[_ref("A")],
        scan_date=day2,
        discovery_complete=False,
        stop_reason="page_error:17",
    )
    session.commit()

    row_b = session.query(SourceListing).filter_by(listing_key="B").one()
    assert result.safety_passed is False
    assert row_b.status == SourceListingStatus.ACTIVE.value
    assert row_b.missing_streak == 0
    session.close()
