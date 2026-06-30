"""
Sistema de seguimiento del ciclo de vida del vehículo en el mercado.

Responsabilidades:
- Detectar vehículos que salieron del mercado (sin actividad por 5+ días)
- Calcular días en el mercado
- Actualizar estados de VMU y ListingHistory
- Generar estadísticas de rotación
"""

import logging
from datetime import date, timedelta

from sqlalchemy import and_
from sqlalchemy.orm import Session

from dtc.db.models import (
    VehicleMarketUnit, ListingHistory, VMUStatus, ListingStatus
)
from dtc.config.settings import config

logger = logging.getLogger(__name__)


class LifecycleTracker:
    """Gestiona el ciclo de vida de los vehículos en el mercado."""

    def __init__(self, session: Session):
        self.session = session
        self.exit_threshold = config.vmu.days_to_exit
        self.stats = {
            "listings_marked_missing": 0,
            "vmus_marked_sold": 0,
            "vmus_updated": 0,
        }

    def run_daily_check(self, check_date: date = None):
        """
        Ejecuta la verificación diaria del ciclo de vida.
        Debe correr después del scraping y matching.

        Pasos:
        1. Marcar como "desaparecido" los anuncios no detectados hoy
        2. Incrementar días consecutivos sin detección
        3. Marcar VMUs como vendidos si superan umbral
        4. Actualizar días en mercado
        """
        today = check_date or date.today()
        logger.info(f"Ejecutando verificación de ciclo de vida para {today}")

        self._update_missing_listings(today)
        self._check_vmu_exits(today)
        self._update_days_on_market(today)

        self.session.commit()

        logger.info(
            f"Ciclo de vida actualizado: "
            f"{self.stats['listings_marked_missing']} anuncios desaparecidos, "
            f"{self.stats['vmus_marked_sold']} VMUs salieron del mercado, "
            f"{self.stats['vmus_updated']} VMUs actualizados"
        )

    def _update_missing_listings(self, today: date):
        """
        Marca como desaparecidos los anuncios activos que no fueron
        detectados en el último scraping.
        """
        # Anuncios activos cuya última detección no es hoy
        missing_listings = self.session.query(ListingHistory).filter(
            and_(
                ListingHistory.status == ListingStatus.ACTIVO.value,
                ListingHistory.last_detected < today,
            )
        ).all()

        for listing in missing_listings:
            days_missing = (today - listing.last_detected).days
            listing.consecutive_missing_days = days_missing

            if days_missing >= self.exit_threshold:
                listing.status = ListingStatus.DESAPARECIDO.value
                self.stats["listings_marked_missing"] += 1
                logger.debug(
                    f"Anuncio {listing.id} marcado como desaparecido "
                    f"({days_missing} días sin detección)"
                )

    def _check_vmu_exits(self, today: date):
        """
        Verifica si algún VMU debe marcarse como vendido/salido del mercado.
        Un VMU sale del mercado cuando TODOS sus anuncios están desaparecidos.
        """
        # VMUs activos en el mercado
        active_vmus = self.session.query(VehicleMarketUnit).filter(
            VehicleMarketUnit.status == VMUStatus.EN_MERCADO.value
        ).all()

        for vmu in active_vmus:
            # Verificar si tiene al menos un anuncio activo
            active_listings = self.session.query(ListingHistory).filter(
                and_(
                    ListingHistory.vmu_id == vmu.id,
                    ListingHistory.status == ListingStatus.ACTIVO.value,
                )
            ).count()

            if active_listings == 0:
                # Verificar que todos los anuncios llevan suficientes días
                # sin detección
                all_listings = self.session.query(ListingHistory).filter(
                    ListingHistory.vmu_id == vmu.id
                ).all()

                all_missing_enough = all(
                    lh.consecutive_missing_days >= self.exit_threshold
                    for lh in all_listings
                )

                if all_missing_enough and all_listings:
                    vmu.status = VMUStatus.VENDIDO.value
                    vmu.market_exit_date = today - timedelta(days=self.exit_threshold)
                    vmu.days_on_market = (vmu.market_exit_date - vmu.market_entry_date).days
                    self.stats["vmus_marked_sold"] += 1
                    logger.info(
                        f"VMU {vmu.id} ({vmu.brand} {vmu.model} {vmu.year}) "
                        f"salió del mercado. Días en mercado: {vmu.days_on_market}"
                    )

    def _update_days_on_market(self, today: date):
        """Actualiza los días en mercado para VMUs activos."""
        active_vmus = self.session.query(VehicleMarketUnit).filter(
            VehicleMarketUnit.status == VMUStatus.EN_MERCADO.value
        ).all()

        for vmu in active_vmus:
            vmu.days_on_market = (today - vmu.market_entry_date).days
            self.stats["vmus_updated"] += 1

    def get_market_summary(self) -> dict:
        """Genera un resumen del estado actual del mercado."""
        total_active = self.session.query(VehicleMarketUnit).filter(
            VehicleMarketUnit.status == VMUStatus.EN_MERCADO.value
        ).count()

        total_sold = self.session.query(VehicleMarketUnit).filter(
            VehicleMarketUnit.status == VMUStatus.VENDIDO.value
        ).count()

        # Promedio de días en mercado para vendidos
        from sqlalchemy import func
        avg_days = self.session.query(func.avg(VehicleMarketUnit.days_on_market)).filter(
            VehicleMarketUnit.status == VMUStatus.VENDIDO.value
        ).scalar()

        # Top marcas activas
        top_brands = self.session.query(
            VehicleMarketUnit.brand,
            func.count(VehicleMarketUnit.id).label("count")
        ).filter(
            VehicleMarketUnit.status == VMUStatus.EN_MERCADO.value
        ).group_by(
            VehicleMarketUnit.brand
        ).order_by(
            func.count(VehicleMarketUnit.id).desc()
        ).limit(10).all()

        # Precio promedio por marca
        avg_price_by_brand = self.session.query(
            VehicleMarketUnit.brand,
            func.avg(VehicleMarketUnit.last_price_usd).label("avg_price")
        ).filter(
            and_(
                VehicleMarketUnit.status == VMUStatus.EN_MERCADO.value,
                VehicleMarketUnit.last_price_usd.isnot(None),
            )
        ).group_by(
            VehicleMarketUnit.brand
        ).order_by(
            func.avg(VehicleMarketUnit.last_price_usd).desc()
        ).limit(10).all()

        return {
            "total_active_vmus": total_active,
            "total_sold_vmus": total_sold,
            "avg_days_on_market": round(avg_days, 1) if avg_days else None,
            "top_brands": [(b, c) for b, c in top_brands],
            "avg_price_by_brand": [(b, round(p, 2)) for b, p in avg_price_by_brand if p],
        }
