"""
Motor de identificación de Vehicle Market Units (VMU).

Este módulo implementa la lógica probabilística para determinar si un anuncio
nuevo corresponde a un vehículo que ya existe en la base de datos o si se trata
de un vehículo nuevo.

Reglas de coincidencia:
1. Campos exactos: marca, modelo, año (deben coincidir)
2. Kilometraje similar: diferencia máxima ±2000 km
3. Al menos una condición adicional:
   - Coincidencia en color exterior
   - Coincidencia de fotos (hash visual)
   - Coincidencia en versión/trim
"""

import logging
from datetime import date
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from dtc.db.models import VehicleMarketUnit, RawListing, ListingHistory, VMUStatus, ListingStatus
from dtc.config.settings import config

logger = logging.getLogger(__name__)


class VMUEngine:
    """Motor de matching para identificación de vehículos únicos."""

    def __init__(self, session: Session):
        self.session = session
        self.km_tolerance = config.vmu.km_tolerance
        self.stats = {
            "matched": 0,
            "created": 0,
            "errors": 0,
        }

    def process_listing(self, listing: RawListing) -> Optional[VehicleMarketUnit]:
        """
        Procesa un anuncio normalizado y lo asocia a un VMU existente
        o crea uno nuevo.

        Args:
            listing: RawListing con datos normalizados.

        Returns:
            VehicleMarketUnit asociado.
        """
        if not listing.norm_brand or not listing.norm_model or not listing.norm_year:
            logger.warning(f"Listing {listing.id} sin datos básicos normalizados. Omitido.")
            return None

        # Buscar candidatos VMU
        candidates = self._find_candidates(listing)

        if candidates:
            # Evaluar cada candidato
            best_match = None
            best_score = 0.0

            for vmu in candidates:
                score = self._calculate_match_score(listing, vmu)
                if score > best_score:
                    best_score = score
                    best_match = vmu

            if best_match and best_score >= config.vmu.min_confidence_score:
                # Match encontrado
                self._link_listing_to_vmu(listing, best_match)
                self.stats["matched"] += 1
                logger.info(
                    f"Listing {listing.id} → VMU {best_match.id} "
                    f"(score: {best_score:.2f})"
                )
                return best_match

        # No hay match, crear nuevo VMU
        vmu = self._create_vmu(listing)
        self.stats["created"] += 1
        logger.info(f"Listing {listing.id} → Nuevo VMU {vmu.id}")
        return vmu

    def _find_candidates(self, listing: RawListing) -> list[VehicleMarketUnit]:
        """
        Busca VMUs candidatos que coincidan en marca, modelo y año.
        Solo retorna VMUs que estén actualmente en el mercado.
        """
        candidates = self.session.query(VehicleMarketUnit).filter(
            and_(
                VehicleMarketUnit.brand == listing.norm_brand,
                VehicleMarketUnit.model == listing.norm_model,
                VehicleMarketUnit.year == listing.norm_year,
                VehicleMarketUnit.status == VMUStatus.EN_MERCADO.value,
            )
        ).all()

        return candidates

    def _calculate_match_score(self, listing: RawListing, vmu: VehicleMarketUnit) -> float:
        """
        Calcula un score de coincidencia entre un anuncio y un VMU.

        Score base: 0.5 (por coincidencia exacta de marca/modelo/año)
        Bonus por:
        - Kilometraje similar: +0.2
        - Color exterior coincide: +0.15
        - Trim/versión coincide: +0.15
        - Fotos similares: +0.2 (futuro)

        Penalty:
        - Kilometraje muy diferente: -0.3
        """
        score = 0.5  # Base por marca/modelo/año

        # Evaluar kilometraje
        if listing.norm_km is not None and vmu.km is not None:
            km_diff = abs(listing.norm_km - vmu.km)
            if km_diff <= self.km_tolerance:
                score += 0.2
            elif km_diff <= self.km_tolerance * 2:
                score += 0.05
            else:
                score -= 0.3  # Muy diferente, probablemente otro vehículo
        # Si falta km en alguno, no sumamos ni restamos

        # Evaluar color exterior
        if (listing.norm_exterior_color and vmu.exterior_color
                and listing.norm_exterior_color == vmu.exterior_color):
            score += 0.15

        # Evaluar trim/versión
        if (listing.norm_trim and vmu.trim
                and self._fuzzy_trim_match(listing.norm_trim, vmu.trim)):
            score += 0.15

        # TODO: Implementar comparación de fotos por hash visual
        # if listing.raw_photos and vmu.photo_hashes:
        #     photo_score = self._compare_photo_hashes(listing.raw_photos, vmu.photo_hashes)
        #     score += photo_score * 0.2

        return min(score, 1.0)

    def _fuzzy_trim_match(self, trim1: str, trim2: str) -> bool:
        """Comparación fuzzy de trim/versión."""
        t1 = trim1.strip().lower()
        t2 = trim2.strip().lower()
        return t1 == t2 or t1 in t2 or t2 in t1

    def _create_vmu(self, listing: RawListing) -> VehicleMarketUnit:
        """Crea un nuevo VMU a partir de un anuncio."""
        today = date.today()

        vmu = VehicleMarketUnit(
            brand=listing.norm_brand,
            model=listing.norm_model,
            year=listing.norm_year,
            km=listing.norm_km,
            body_style=listing.norm_body_style,
            drivetrain=listing.norm_drivetrain,
            transmission=listing.norm_transmission,
            fuel=listing.norm_fuel,
            exterior_color=listing.norm_exterior_color,
            trim=listing.norm_trim,
            status=VMUStatus.EN_MERCADO.value,
            market_entry_date=listing.capture_date or today,
            last_seen_date=listing.capture_date or today,
            first_price_usd=listing.norm_price_usd,
            last_price_usd=listing.norm_price_usd,
            min_price_usd=listing.norm_price_usd,
            max_price_usd=listing.norm_price_usd,
            sources_count=1,
        )

        self.session.add(vmu)
        self.session.flush()  # Para obtener el ID

        # Vincular listing al VMU
        listing.vmu_id = vmu.id
        listing.is_matched = True

        # Crear entrada en historial
        self._create_listing_history(listing, vmu)

        return vmu

    def _link_listing_to_vmu(self, listing: RawListing, vmu: VehicleMarketUnit):
        """Asocia un anuncio a un VMU existente y actualiza datos."""
        listing.vmu_id = vmu.id
        listing.is_matched = True

        # Actualizar VMU con datos más recientes
        vmu.last_seen_date = listing.capture_date or date.today()

        if listing.norm_km and (vmu.km is None or listing.norm_km > vmu.km):
            vmu.km = listing.norm_km

        if listing.norm_price_usd:
            vmu.last_price_usd = listing.norm_price_usd
            if vmu.min_price_usd is None or listing.norm_price_usd < vmu.min_price_usd:
                vmu.min_price_usd = listing.norm_price_usd
            if vmu.max_price_usd is None or listing.norm_price_usd > vmu.max_price_usd:
                vmu.max_price_usd = listing.norm_price_usd

        # Enriquecer datos faltantes
        if not vmu.body_style and listing.norm_body_style:
            vmu.body_style = listing.norm_body_style
        if not vmu.drivetrain and listing.norm_drivetrain:
            vmu.drivetrain = listing.norm_drivetrain
        if not vmu.transmission and listing.norm_transmission:
            vmu.transmission = listing.norm_transmission
        if not vmu.fuel and listing.norm_fuel:
            vmu.fuel = listing.norm_fuel
        if not vmu.exterior_color and listing.norm_exterior_color:
            vmu.exterior_color = listing.norm_exterior_color
        if not vmu.trim and listing.norm_trim:
            vmu.trim = listing.norm_trim

        # Crear o actualizar historial
        self._update_or_create_listing_history(listing, vmu)

    def _create_listing_history(self, listing: RawListing, vmu: VehicleMarketUnit):
        """Crea una nueva entrada en el historial de anuncios."""
        history = ListingHistory(
            vmu_id=vmu.id,
            source_id=listing.source_id,
            url=listing.url,
            external_id=listing.external_id,
            price_usd=listing.norm_price_usd,
            km_reported=listing.norm_km,
            status=ListingStatus.ACTIVO.value,
            first_detected=listing.capture_date or date.today(),
            last_detected=listing.capture_date or date.today(),
            consecutive_missing_days=0,
        )
        self.session.add(history)

    def _update_or_create_listing_history(self, listing: RawListing, vmu: VehicleMarketUnit):
        """Actualiza historial existente o crea uno nuevo."""
        # Buscar si ya existe un historial para esta fuente y URL
        existing = self.session.query(ListingHistory).filter(
            and_(
                ListingHistory.vmu_id == vmu.id,
                ListingHistory.source_id == listing.source_id,
                ListingHistory.external_id == listing.external_id,
            )
        ).first()

        if existing:
            # Actualizar
            existing.last_detected = listing.capture_date or date.today()
            existing.consecutive_missing_days = 0
            existing.status = ListingStatus.ACTIVO.value
            if listing.norm_price_usd:
                existing.price_usd = listing.norm_price_usd
            if listing.norm_km:
                existing.km_reported = listing.norm_km
        else:
            # Crear nuevo (nueva fuente o nuevo anuncio en la misma fuente)
            self._create_listing_history(listing, vmu)
            # Actualizar contador de fuentes
            sources = self.session.query(ListingHistory.source_id).filter(
                ListingHistory.vmu_id == vmu.id
            ).distinct().count()
            vmu.sources_count = sources

    def process_all_unmatched(self):
        """Procesa todos los anuncios normalizados que no han sido matcheados."""
        unmatched = self.session.query(RawListing).filter(
            and_(
                RawListing.is_normalized == True,
                RawListing.is_matched == False,
            )
        ).all()

        logger.info(f"Procesando {len(unmatched)} anuncios sin matchear...")

        for listing in unmatched:
            try:
                self.process_listing(listing)
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(f"Error procesando listing {listing.id}: {e}")

        self.session.commit()

        logger.info(
            f"Matching completado: "
            f"{self.stats['matched']} matcheados, "
            f"{self.stats['created']} nuevos VMU, "
            f"{self.stats['errors']} errores"
        )
