"""Conexión y sesión de base de datos MySQL."""

from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text, func
from sqlalchemy.orm import sessionmaker, Session

from dtc.config.settings import config
from dtc.db.models import Base, RawListing


# Motor de SQLAlchemy
engine = create_engine(
    config.db.url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

# Fábrica de sesiones
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    """Crea todas las tablas en la base de datos."""
    Base.metadata.create_all(bind=engine)
    ensure_listing_key_schema()
    print("✓ Tablas creadas correctamente en la base de datos.")


def ensure_listing_key_schema():
    """Agrega la llave canónica de deduplicación a instalaciones existentes."""
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("raw_listings")}

    with engine.begin() as connection:
        if "listing_key" not in columns:
            connection.execute(text(
                "ALTER TABLE raw_listings ADD COLUMN listing_key VARCHAR(64) NULL"
            ))

    with get_session() as session:
        from dtc.db.repository import build_listing_key

        rows = (
            session.query(RawListing)
            .filter((RawListing.listing_key.is_(None)) | (RawListing.listing_key == ""))
            .all()
        )
        for listing in rows:
            listing.listing_key = build_listing_key(listing.source.name, {
                "external_id": listing.external_id,
                "url": listing.url,
            })

    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE raw_listings MODIFY listing_key VARCHAR(64) NOT NULL"
        ))

    indexes = {index["name"] for index in inspect(engine).get_indexes("raw_listings")}
    if "uq_source_listing_key_date" not in indexes:
        with get_session() as session:
            duplicates = (
                session.query(
                    RawListing.source_id,
                    RawListing.listing_key,
                    RawListing.capture_date,
                    func.count(RawListing.id).label("count"),
                )
                .group_by(RawListing.source_id, RawListing.listing_key, RawListing.capture_date)
                .having(func.count(RawListing.id) > 1)
                .limit(5)
                .all()
            )
            if duplicates:
                sample = ", ".join(
                    f"source={row.source_id} key={row.listing_key} date={row.capture_date} count={row.count}"
                    for row in duplicates
                )
                raise RuntimeError(
                    "No se puede crear el índice anti-duplicados porque ya existen "
                    f"raw_listings duplicados. Muestra: {sample}"
                )
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE raw_listings "
                "ADD UNIQUE INDEX uq_source_listing_key_date "
                "(source_id, listing_key, capture_date)"
            ))


def drop_db():
    """Elimina todas las tablas (usar con precaución)."""
    Base.metadata.drop_all(bind=engine)
    print("✓ Tablas eliminadas.")


@contextmanager
def get_session() -> Session:
    """Context manager para obtener una sesión de base de datos."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def seed_data_sources():
    """Inserta las fuentes de datos iniciales."""
    from dtc.db.models import DataSource

    sources = [
        DataSource(
            name="CRAutos",
            base_url="https://www.crautos.com",
            search_url_template="https://www.crautos.com/autosusados/search.cfm",
            scraper_module="dtc.scrapers.crautos_scraper",
            is_active=True,
            notes="Principal portal de vehículos usados de Costa Rica."
        ),
        DataSource(
            name="Encuentra24",
            base_url="https://www.encuentra24.com",
            search_url_template="https://www.encuentra24.com/costa-rica-es/autos-usados",
            scraper_module="dtc.scrapers.encuentra24_scraper",
            is_active=True,
            notes="Portal de clasificados con sección de vehículos."
        ),
    ]

    with get_session() as session:
        for source in sources:
            existing = session.query(DataSource).filter_by(name=source.name).first()
            if not existing:
                session.add(source)
                print(f"  ✓ Fuente '{source.name}' agregada.")
            else:
                print(f"  → Fuente '{source.name}' ya existe.")

    print("✓ Fuentes de datos inicializadas.")
