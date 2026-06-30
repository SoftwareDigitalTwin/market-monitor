"""
Motor de normalización de datos de anuncios vehiculares.
Toma los datos crudos de un RawListing y los estandariza.
"""

import re
import unicodedata
from typing import Optional

from dtc.normalizer.equivalences import (
    BRAND_MAP,
    MODEL_NORMALIZATION,
    FUEL_MAP,
    TRANSMISSION_MAP,
    DRIVETRAIN_MAP,
    BODY_STYLE_MAP,
    SELLER_TYPE_MAP,
    COLOR_MAP,
)


def _clean_text(text: Optional[str]) -> str:
    """Limpia y normaliza texto base."""
    if not text:
        return ""
    # Normalizar unicode
    text = unicodedata.normalize("NFKD", text)
    # Minúsculas y trim
    text = text.strip().lower()
    # Remover caracteres especiales excepto guiones y espacios
    text = re.sub(r"[^\w\s\-]", "", text)
    # Colapsar espacios múltiples
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_brand(raw_brand: Optional[str]) -> Optional[str]:
    """Normaliza la marca del vehículo."""
    if not raw_brand:
        return None
    cleaned = _clean_text(raw_brand)
    # Buscar en mapa de equivalencias
    if cleaned in BRAND_MAP:
        return BRAND_MAP[cleaned]
    # Si no está en el mapa, capitalizar
    return raw_brand.strip().title()


def normalize_model(raw_model: Optional[str], brand: Optional[str] = None) -> Optional[str]:
    """Normaliza el modelo del vehículo."""
    if not raw_model:
        return None
    cleaned = _clean_text(raw_model)
    # Buscar en mapa de normalización
    if cleaned in MODEL_NORMALIZATION:
        return MODEL_NORMALIZATION[cleaned]
    # Si no está en el mapa, capitalizar
    return raw_model.strip().title()


def normalize_year(raw_year) -> Optional[int]:
    """Normaliza el año del vehículo."""
    if raw_year is None:
        return None
    try:
        year = int(raw_year)
        if 1980 <= year <= 2027:
            return year
        return None
    except (ValueError, TypeError):
        # Intentar extraer año de un string
        match = re.search(r"(19|20)\d{2}", str(raw_year))
        if match:
            year = int(match.group())
            if 1980 <= year <= 2027:
                return year
        return None


def normalize_km(raw_km) -> Optional[int]:
    """Normaliza el kilometraje."""
    if raw_km is None:
        return None
    try:
        # Si es string, limpiar
        if isinstance(raw_km, str):
            raw_km = re.sub(r"[^\d]", "", raw_km)
        km = int(float(raw_km))
        # Validar rango razonable
        if 0 <= km <= 1_000_000:
            return km
        return None
    except (ValueError, TypeError):
        return None


def normalize_price(raw_price, raw_currency: Optional[str] = None) -> Optional[float]:
    """
    Normaliza el precio a USD.
    Tipo de cambio aproximado CRC/USD. En producción usar API de tipo de cambio.
    """
    CRC_TO_USD = 530  # tipo de cambio aproximado

    if raw_price is None:
        return None
    try:
        if isinstance(raw_price, str):
            raw_price = re.sub(r"[^\d.]", "", raw_price)
        price = float(raw_price)
        if price <= 0:
            return None

        # Determinar moneda
        currency = (raw_currency or "").strip().upper()
        if currency in ("CRC", "₡", "COLONES"):
            price = price / CRC_TO_USD
        elif currency in ("USD", "$", "US$", "DOLARES"):
            pass  # ya en USD
        else:
            # Heurística: si el precio es > 50000, probablemente es CRC
            if price > 50000:
                price = price / CRC_TO_USD

        # Redondear
        return round(price, 2)
    except (ValueError, TypeError):
        return None


def _lookup_with_substring(value: str, mapping: dict) -> Optional[str]:
    """
    Busca primero match exacto; si no, hace substring match
    (clave del mapa contenida en el valor limpio o viceversa).
    Útil para entradas como 'Automática/Dual' → 'automatica'.
    """
    if value in mapping:
        return mapping[value]
    for key, normalized in mapping.items():
        if key in value or value in key:
            return normalized
    return None


def normalize_fuel(raw_fuel: Optional[str]) -> Optional[str]:
    """Normaliza el tipo de combustible."""
    if not raw_fuel:
        return None
    return _lookup_with_substring(_clean_text(raw_fuel), FUEL_MAP)


def normalize_transmission(raw_transmission: Optional[str]) -> Optional[str]:
    """Normaliza el tipo de transmisión."""
    if not raw_transmission:
        return None
    return _lookup_with_substring(_clean_text(raw_transmission), TRANSMISSION_MAP)


def normalize_drivetrain(raw_drivetrain: Optional[str]) -> Optional[str]:
    """Normaliza el tipo de tracción."""
    if not raw_drivetrain:
        return None
    return _lookup_with_substring(_clean_text(raw_drivetrain), DRIVETRAIN_MAP)


def normalize_body_style(raw_body_style: Optional[str]) -> Optional[str]:
    """Normaliza el estilo de carrocería."""
    if not raw_body_style:
        return None
    return _lookup_with_substring(_clean_text(raw_body_style), BODY_STYLE_MAP)


def normalize_seller_type(raw_seller_type: Optional[str]) -> Optional[str]:
    """Normaliza el tipo de vendedor."""
    if not raw_seller_type:
        return None
    return _lookup_with_substring(_clean_text(raw_seller_type), SELLER_TYPE_MAP)


def normalize_color(raw_color: Optional[str]) -> Optional[str]:
    """Normaliza el color."""
    if not raw_color:
        return None
    cleaned = _clean_text(raw_color)
    return COLOR_MAP.get(cleaned, raw_color.strip().title())


def normalize_listing(listing) -> dict:
    """
    Normaliza todos los campos de un RawListing.
    Retorna un diccionario con los campos normalizados.
    """
    return {
        "norm_brand": normalize_brand(listing.raw_brand),
        "norm_model": normalize_model(listing.raw_model, listing.raw_brand),
        "norm_year": normalize_year(listing.raw_year),
        "norm_km": normalize_km(listing.raw_km),
        "norm_price_usd": normalize_price(listing.raw_price, listing.raw_currency),
        "norm_body_style": normalize_body_style(listing.raw_body_style),
        "norm_drivetrain": normalize_drivetrain(listing.raw_drivetrain),
        "norm_transmission": normalize_transmission(listing.raw_transmission),
        "norm_fuel": normalize_fuel(listing.raw_fuel),
        "norm_seller_type": normalize_seller_type(listing.raw_seller_type),
        "norm_exterior_color": normalize_color(listing.raw_exterior_color),
        "norm_trim": listing.raw_trim.strip() if listing.raw_trim else None,
    }
