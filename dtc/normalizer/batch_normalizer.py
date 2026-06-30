"""
Normalizador por lotes.
Procesa todos los RawListings que no han sido normalizados.
"""

import logging
from sqlalchemy.orm import Session

from dtc.db.models import RawListing
from dtc.normalizer.normalizer import normalize_listing

logger = logging.getLogger(__name__)


def normalize_all_pending(session: Session) -> dict:
    """
    Normaliza todos los anuncios pendientes.

    Returns:
        dict con estadísticas del proceso.
    """
    stats = {"processed": 0, "errors": 0}

    pending = session.query(RawListing).filter(
        RawListing.is_normalized == False
    ).all()

    logger.info(f"Normalizando {len(pending)} anuncios pendientes...")

    for listing in pending:
        try:
            normalized = normalize_listing(listing)

            # Aplicar valores normalizados
            for key, value in normalized.items():
                setattr(listing, key, value)

            listing.is_normalized = True
            stats["processed"] += 1

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Error normalizando listing {listing.id}: {e}")

    session.commit()

    logger.info(
        f"Normalización completada: "
        f"{stats['processed']} procesados, {stats['errors']} errores"
    )
    return stats
