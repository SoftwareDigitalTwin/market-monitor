"""
Modelos de base de datos para el sistema DTC.

Entidades principales:
- DataSource: fuente de datos (CRAutos, Encuentra24, etc.)
- RawListing: anuncio crudo capturado del scraping
- VehicleMarketUnit (VMU): vehículo único identificado en el mercado
- ListingHistory: historial de anuncios asociados a un VMU
- NormalizationMap: tablas de equivalencias para normalización
"""

from datetime import datetime, date
from typing import Optional
import uuid

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date,
    Text, ForeignKey, UniqueConstraint, Index, Enum, JSON,
    create_engine
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.sql import func
import enum


class Base(DeclarativeBase):
    pass


# ─── Enums ───────────────────────────────────────────────────────────────────

class FuelType(str, enum.Enum):
    GASOLINA = "gasolina"
    DIESEL = "diesel"
    ELECTRICO = "electrico"
    HIBRIDO = "hibrido"
    GAS_LP = "gas_lp"
    OTRO = "otro"


class TransmissionType(str, enum.Enum):
    AUTOMATICA = "automatica"
    MANUAL = "manual"
    CVT = "cvt"
    OTRO = "otro"


class DrivetrainType(str, enum.Enum):
    FWD = "fwd"       # Tracción delantera
    RWD = "rwd"       # Tracción trasera
    AWD = "awd"       # All wheel drive
    FOUR_WD = "4wd"   # 4x4
    OTRO = "otro"


class BodyStyle(str, enum.Enum):
    SEDAN = "sedan"
    SUV = "suv"
    PICKUP = "pickup"
    HATCHBACK = "hatchback"
    COUPE = "coupe"
    CONVERTIBLE = "convertible"
    VAN = "van"
    WAGON = "wagon"
    CROSSOVER = "crossover"
    MINIVAN = "minivan"
    OTRO = "otro"


class SellerType(str, enum.Enum):
    PARTICULAR = "particular"
    AGENCIA = "agencia"
    COMERCIALIZADOR = "comercializador"
    OTRO = "otro"


class ListingStatus(str, enum.Enum):
    ACTIVO = "activo"
    DESAPARECIDO = "desaparecido"


class VMUStatus(str, enum.Enum):
    EN_MERCADO = "en_mercado"
    VENDIDO = "vendido"  # salió del mercado


# ─── DataSource ──────────────────────────────────────────────────────────────

class DataSource(Base):
    """Fuente de datos (portal de venta de vehículos)."""
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    search_url_template: Mapped[Optional[str]] = mapped_column(String(1000))
    scraper_module: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones
    raw_listings = relationship("RawListing", back_populates="source")
    listing_histories = relationship("ListingHistory", back_populates="source")
    scraping_runs = relationship("ScrapingRun", back_populates="source")


# ─── RawListing ──────────────────────────────────────────────────────────────

class RawListing(Base):
    """Anuncio crudo capturado directamente del scraping."""
    __tablename__ = "raw_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_sources.id"), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(200))  # ID del anuncio en la fuente
    url: Mapped[str] = mapped_column(String(700), nullable=False)

    # Datos del vehículo (tal como vienen de la fuente)
    raw_brand: Mapped[Optional[str]] = mapped_column(String(200))
    raw_model: Mapped[Optional[str]] = mapped_column(String(200))
    raw_year: Mapped[Optional[int]] = mapped_column(Integer)
    raw_km: Mapped[Optional[int]] = mapped_column(Integer)
    raw_price: Mapped[Optional[float]] = mapped_column(Float)
    raw_currency: Mapped[Optional[str]] = mapped_column(String(10))  # CRC, USD
    raw_body_style: Mapped[Optional[str]] = mapped_column(String(100))
    raw_drivetrain: Mapped[Optional[str]] = mapped_column(String(100))
    raw_transmission: Mapped[Optional[str]] = mapped_column(String(100))
    raw_fuel: Mapped[Optional[str]] = mapped_column(String(100))
    raw_seller_type: Mapped[Optional[str]] = mapped_column(String(100))
    raw_exterior_color: Mapped[Optional[str]] = mapped_column(String(100))
    raw_interior_color: Mapped[Optional[str]] = mapped_column(String(100))
    raw_trim: Mapped[Optional[str]] = mapped_column(String(200))
    raw_description: Mapped[Optional[str]] = mapped_column(Text)
    raw_photos: Mapped[Optional[list]] = mapped_column(JSON)  # lista de URLs de fotos

    # Datos normalizados (se llenan después)
    norm_brand: Mapped[Optional[str]] = mapped_column(String(100))
    norm_model: Mapped[Optional[str]] = mapped_column(String(100))
    norm_year: Mapped[Optional[int]] = mapped_column(Integer)
    norm_km: Mapped[Optional[int]] = mapped_column(Integer)
    norm_price_usd: Mapped[Optional[float]] = mapped_column(Float)
    norm_body_style: Mapped[Optional[str]] = mapped_column(String(50))
    norm_drivetrain: Mapped[Optional[str]] = mapped_column(String(20))
    norm_transmission: Mapped[Optional[str]] = mapped_column(String(20))
    norm_fuel: Mapped[Optional[str]] = mapped_column(String(20))
    norm_seller_type: Mapped[Optional[str]] = mapped_column(String(30))
    norm_exterior_color: Mapped[Optional[str]] = mapped_column(String(50))
    norm_trim: Mapped[Optional[str]] = mapped_column(String(200))

    # Metadata
    is_normalized: Mapped[bool] = mapped_column(Boolean, default=False)
    is_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    vmu_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vehicle_market_units.id"))
    capture_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relaciones
    source = relationship("DataSource", back_populates="raw_listings")
    vmu = relationship("VehicleMarketUnit", back_populates="raw_listings")
    listing_images = relationship("ListingImage", back_populates="listing")

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", "capture_date", name="uq_source_listing_date"),
        UniqueConstraint("source_id", "url", "capture_date", name="uq_source_url_date"),
        Index("ix_raw_listings_capture_date", "capture_date"),
        Index("ix_raw_listings_norm_brand_model", "norm_brand", "norm_model"),
        Index("ix_raw_listings_not_matched", "is_matched"),
    )


# ─── Vehicle Market Unit (VMU) ──────────────────────────────────────────────

class VehicleMarketUnit(Base):
    """
    Vehículo único identificado en el mercado.
    Cada VMU representa un vehículo específico, independiente de en cuántos
    portales esté publicado.
    """
    __tablename__ = "vehicle_market_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )

    # Datos canónicos del vehículo
    brand: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    km: Mapped[Optional[int]] = mapped_column(Integer)
    body_style: Mapped[Optional[str]] = mapped_column(String(50))
    drivetrain: Mapped[Optional[str]] = mapped_column(String(20))
    transmission: Mapped[Optional[str]] = mapped_column(String(20))
    fuel: Mapped[Optional[str]] = mapped_column(String(20))
    exterior_color: Mapped[Optional[str]] = mapped_column(String(50))
    interior_color: Mapped[Optional[str]] = mapped_column(String(50))
    trim: Mapped[Optional[str]] = mapped_column(String(200))

    # Ciclo de vida
    status: Mapped[str] = mapped_column(
        String(20), default=VMUStatus.EN_MERCADO.value
    )
    market_entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    market_exit_date: Mapped[Optional[date]] = mapped_column(Date)
    last_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_on_market: Mapped[Optional[int]] = mapped_column(Integer)

    # Precio
    first_price_usd: Mapped[Optional[float]] = mapped_column(Float)
    last_price_usd: Mapped[Optional[float]] = mapped_column(Float)
    min_price_usd: Mapped[Optional[float]] = mapped_column(Float)
    max_price_usd: Mapped[Optional[float]] = mapped_column(Float)

    # Metadata
    sources_count: Mapped[int] = mapped_column(Integer, default=1)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    photo_hashes: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones
    raw_listings = relationship("RawListing", back_populates="vmu")
    listing_histories = relationship("ListingHistory", back_populates="vmu")

    __table_args__ = (
        Index("ix_vmu_brand_model_year", "brand", "model", "year"),
        Index("ix_vmu_status", "status"),
        Index("ix_vmu_entry_date", "market_entry_date"),
    )


# ─── Listing History ────────────────────────────────────────────────────────

class ListingHistory(Base):
    """
    Historial de anuncios asociados a un VMU.
    Registra la presencia del vehículo en cada portal y su evolución.
    """
    __tablename__ = "listing_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vmu_id: Mapped[int] = mapped_column(Integer, ForeignKey("vehicle_market_units.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(200))

    # Datos del anuncio en este momento
    price_usd: Mapped[Optional[float]] = mapped_column(Float)
    km_reported: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), default=ListingStatus.ACTIVO.value
    )

    # Fechas
    first_detected: Mapped[date] = mapped_column(Date, nullable=False)
    last_detected: Mapped[date] = mapped_column(Date, nullable=False)
    consecutive_missing_days: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones
    vmu = relationship("VehicleMarketUnit", back_populates="listing_histories")
    source = relationship("DataSource", back_populates="listing_histories")

    __table_args__ = (
        Index("ix_listing_history_vmu", "vmu_id"),
        Index("ix_listing_history_status", "status"),
    )


# ─── Listing Images ────────────────────────────────────────────────────────

class ListingImage(Base):
    """Imagen asociada a un anuncio y, opcionalmente, subida a GCS."""
    __tablename__ = "listing_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_listing_id: Mapped[int] = mapped_column(Integer, ForeignKey("raw_listings.id"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(700), nullable=False)
    storage_url: Mapped[Optional[str]] = mapped_column(String(1500))
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000))
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    image_order: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    listing = relationship("RawListing", back_populates="listing_images")

    __table_args__ = (
        UniqueConstraint("raw_listing_id", "source_url", name="uq_listing_image_source"),
        Index("ix_listing_images_listing", "raw_listing_id"),
    )


# ─── Normalization Map ──────────────────────────────────────────────────────

class NormalizationMap(Base):
    """
    Tabla de equivalencias para normalización de datos.
    Mapea valores crudos a valores normalizados.
    """
    __tablename__ = "normalization_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # brand, model, fuel, etc.
    raw_value: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(200), nullable=False)
    source_name: Mapped[Optional[str]] = mapped_column(String(100))  # fuente específica o NULL para global
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("category", "raw_value", "source_name", name="uq_norm_map"),
        Index("ix_norm_map_category", "category"),
    )


# ─── Scraping Run Log ───────────────────────────────────────────────────────

class ScrapingRun(Base):
    """Registro de cada ejecución del scraping."""
    __tablename__ = "scraping_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_sources.id"), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, completed, failed
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_listings: Mapped[int] = mapped_column(Integer, default=0)
    new_listings: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_details: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    source = relationship("DataSource", back_populates="scraping_runs")
