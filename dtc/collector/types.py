from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ListingRef:
    """Referencia liviana encontrada en un índice/listado de una fuente."""

    listing_key: str
    url: str
    external_id: str | None = None


@dataclass
class ManifestResolution:
    """Resultado de reconciliar un manifiesto de anuncios vistos en una corrida."""

    seen_count: int = 0
    baseline_active: int = 0
    safety_passed: bool = False
    new_refs: list[ListingRef] = field(default_factory=list)
    reappeared_refs: list[ListingRef] = field(default_factory=list)
    pending_detail_refs: list[ListingRef] = field(default_factory=list)
    missing_suspected_count: int = 0
    inactive_confirmed_count: int = 0

    @property
    def detail_refs(self) -> list[ListingRef]:
        # Un anuncio nuevo necesita detalle. Uno reaparecido también, porque pudo
        # cambiar precio, kilometraje, vendedor o descripción durante la ausencia.
        refs = [*self.new_refs, *self.reappeared_refs, *self.pending_detail_refs]
        return list({ref.listing_key: ref for ref in refs}.values())
