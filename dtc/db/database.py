"""Conexión y sesión de base de datos MySQL."""

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from dtc.config.settings import config
from dtc.db.models import Base


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
    print("✓ Tablas creadas correctamente en la base de datos.")


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
