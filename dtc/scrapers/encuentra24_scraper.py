"""
Agente de scraping para Encuentra24 (www.encuentra24.com).
Portal de clasificados; usamos la categoría Autos Usados de Costa Rica.

Notas técnicas:
- El sitio es una SPA Next.js. La paginación que SÍ funciona en el listado
  es ?page=N (NO ?o= ni ?p=). Cada página devuelve ~20 anuncios.
- Las páginas de detalle traen un <script type="application/ld+json"> con
  schema.org/Car que contiene marca, transmisión, combustible y precio.
- Los demás specs (año, kilometraje, estilo, tracción, color, ubicación,
  modelo) salen en un bloque "label/valor" del innerText. Cada etiqueta
  está en su propia línea seguida del valor en la línea siguiente.
- Las fotos viven en photos.encuentra24.com/.../cr/<id-prefix>/<id>/<id>_<hash>;
  el ID externo del anuncio aparece literal en cada URL de foto, lo que
  permite filtrar duplicados/iconos UI sin frágiles selectores CSS.
"""

import re
import json
import asyncio
import logging
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from dtc.scrapers.base_scraper import BaseScraper
from dtc.normalizer.equivalences import BRAND_MAP

logger = logging.getLogger(__name__)

BASE_URL = "https://www.encuentra24.com"
LISTING_PATH = "/costa-rica-es/autos-usados"

# Solo nos interesan anuncios de la sub-categoría autos-usados (no motos).
LISTING_HREF_RE = re.compile(
    r"^/costa-rica-es/autos-usados/[^/]+/(\d{6,})/?$"
)

# Marcas multi-palabra ordenadas por longitud descendente para greedy match.
_MULTI_WORD_BRANDS = sorted(
    (k for k in BRAND_MAP if " " in k),
    key=len,
    reverse=True,
)


class Encuentra24Scraper(BaseScraper):
    """Scraper para Encuentra24 (Autos Usados, Costa Rica)."""

    def __init__(self, limit: Optional[int] = None):
        super().__init__(source_name="Encuentra24", limit=limit)

    # ─── Listado ─────────────────────────────────────────────────────────────

    def build_search_url(self, page_number: int) -> str:
        """Construye URL de búsqueda paginada."""
        if page_number <= 1:
            return f"{BASE_URL}{LISTING_PATH}"
        return f"{BASE_URL}{LISTING_PATH}?page={page_number}"

    async def _wait_for_listings(self) -> None:
        """Espera a que el SPA inyecte los anchors de detalle."""
        try:
            await self.page.wait_for_selector(
                'a[href*="/costa-rica-es/autos-usados/"]', timeout=10000
            )
        except Exception:
            # No hay anchors aún: probable bloqueo o página sin resultados.
            pass

    async def get_listing_urls(self) -> list[str]:
        """
        Recorre el índice de E24 y devuelve un manifiesto liviano de URLs.

        Las ausencias solo pueden aplicarse cuando el final del índice se detecta
        naturalmente. Si el scan termina por timeout, limit o max_pages se marca
        parcial y Source Collector V2 no genera bajas.
        """
        seen: set[str] = set()
        urls: list[str] = []
        max_pages = self.config.encuentra24_max_pages
        empty_pages_in_a_row = 0
        target = self.limit if self.limit else None
        ended_naturally = False

        for page_num in range(1, max_pages + 1):
            search_url = self.build_search_url(page_num)
            logger.info(f"Procesando página {page_num}: {search_url}")
            try:
                await self.page.goto(search_url, wait_until="domcontentloaded")
                await self._wait_for_listings()
                for _ in range(3):
                    await self.page.mouse.wheel(0, 1500)
                    await asyncio.sleep(0.3)
                await asyncio.sleep(self.config.delay_between_requests)
                hrefs: list[str] = await self.page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]'))"
                    ".map(a => a.getAttribute('href'))"
                )
            except Exception as e:
                self.stats["errors"] += 1
                self.discovery_complete = False
                self.discovery_stop_reason = f"page_error:{page_num}"
                logger.warning(
                    f"Timeout/error en pág {page_num}: {e}. Detengo discovery parcial."
                )
                try:
                    await self.page.evaluate("window.stop()")
                except Exception:
                    pass
                break

            self.stats["total_pages"] += 1

            new_in_page = 0
            for href in hrefs:
                if not href or not LISTING_HREF_RE.match(href):
                    continue
                full_url = urljoin(BASE_URL, href)
                if full_url in seen:
                    continue
                seen.add(full_url)
                urls.append(full_url)
                new_in_page += 1
                if target is not None and len(urls) >= target:
                    break

            logger.info(f"  → {new_in_page} URLs nuevas (acumulado: {len(urls)})")

            if target is not None and len(urls) >= target:
                self.discovery_complete = False
                self.discovery_stop_reason = "test_limit"
                logger.info(f"Cupo de {target} alcanzado; scan parcial de prueba.")
                break

            if new_in_page == 0:
                empty_pages_in_a_row += 1
                if empty_pages_in_a_row >= 2:
                    ended_naturally = True
                    self.discovery_stop_reason = "natural_end"
                    logger.info("Fin natural: 2 páginas consecutivas sin URLs nuevas.")
                    break
            else:
                empty_pages_in_a_row = 0

            await asyncio.sleep(self.config.delay_between_pages)
        else:
            self.discovery_complete = False
            self.discovery_stop_reason = "max_pages_reached"

        if ended_naturally:
            self.discovery_complete = True
        elif self.discovery_stop_reason is None:
            self.discovery_complete = False
            self.discovery_stop_reason = "unknown_partial_stop"

        logger.info(
            "Total URLs E24=%s complete=%s reason=%s",
            len(urls),
            self.discovery_complete,
            self.discovery_stop_reason,
        )
        return urls

    # ─── Detalle ─────────────────────────────────────────────────────────────

    async def parse_listing(self, url: str) -> Optional[dict]:
        """Extrae datos de un anuncio individual de Encuentra24."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            try:
                await self.page.wait_for_selector("h1", timeout=8000)
            except Exception:
                pass
            try:
                await self.page.wait_for_selector(
                    'script[type="application/ld+json"]', timeout=4000
                )
            except Exception:
                pass
            await asyncio.sleep(self.config.delay_between_requests)

            html = await self.page.content()
            body_text: str = await self.page.evaluate(
                "() => document.body.innerText"
            )
            soup = BeautifulSoup(html, "html.parser")

            external_id = self._extract_external_id(url)
            ld = self._extract_ld_car(soup)
            specs = self._extract_specs_from_text(body_text)

            data: dict = {
                "url": url,
                "external_id": external_id,
            }

            # ── Marca / modelo / año ────────────────────────────────────────
            h1 = soup.find("h1")
            h1_text = h1.get_text(strip=True) if h1 else ""

            brand_from_ld = (ld.get("manufacturer") or "").strip() or None
            brand, model, year_from_h1 = self._parse_h1(h1_text, brand_from_ld)

            data["raw_brand"] = brand or brand_from_ld
            # Preferimos modelo del bloque "Detalles adicionales" cuando existe
            data["raw_model"] = specs.get("modelo") or model

            data["raw_year"] = self._parse_int(specs.get("año")) or year_from_h1

            # ── Kilometraje ─────────────────────────────────────────────────
            data["raw_km"] = self._parse_int(specs.get("kilometraje"))

            # ── Precio / moneda ─────────────────────────────────────────────
            offers = ld.get("offers") or {}
            ld_price = offers.get("price")
            ld_currency = offers.get("priceCurrency")
            if ld_price is not None:
                data["raw_price"] = self._parse_int(ld_price)
                data["raw_currency"] = (ld_currency or "").upper() or None
            else:
                price_val, currency = self._extract_price_from_text(body_text)
                data["raw_price"] = price_val
                data["raw_currency"] = currency

            # ── Otros campos ────────────────────────────────────────────────
            data["raw_body_style"] = (
                specs.get("estilo")
                or specs.get("tipo")
                or ld.get("bodyType")
            )
            data["raw_drivetrain"] = (
                specs.get("tracción") or specs.get("traccion")
            )
            data["raw_transmission"] = (
                ld.get("vehicleTransmission") or specs.get("transmisión")
            )

            # JSON-LD pone fuel dentro de vehicleEngine[].fuelType
            fuel_from_ld = None
            engine = ld.get("vehicleEngine")
            if isinstance(engine, list):
                for item in engine:
                    if isinstance(item, dict) and item.get("fuelType"):
                        fuel_from_ld = item["fuelType"]
                        break
            elif isinstance(engine, dict):
                fuel_from_ld = engine.get("fuelType")
            data["raw_fuel"] = fuel_from_ld or specs.get("combustible")

            data["raw_seller_type"] = self._detect_seller_type(body_text)
            data["raw_exterior_color"] = (
                specs.get("color exterior") or specs.get("color")
            )
            data["raw_interior_color"] = specs.get("color interior")
            data["raw_trim"] = (
                specs.get("versión") or specs.get("version")
                or specs.get("equipamiento")
            )
            data["raw_description"] = self._extract_description(soup, body_text)
            data["raw_photos"] = self._extract_photos(soup, external_id)

            return data

        except Exception as e:
            logger.error(f"Error parseando anuncio E24 {url}: {e}")
            return None

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_external_id(url: str) -> Optional[str]:
        """Extrae el ID externo del anuncio del último segmento de la URL."""
        m = re.search(r"/(\d{6,})(?:/|\?|$)", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_ld_car(soup: BeautifulSoup) -> dict:
        """Devuelve el dict del primer JSON-LD con @type=Car/Vehicle/Product."""
        for script in soup.find_all("script", type="application/ld+json"):
            payload = script.string or script.get_text() or ""
            payload = payload.strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            candidates = obj if isinstance(obj, list) else [obj]
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                t = c.get("@type")
                if t in ("Car", "Vehicle", "Product"):
                    return c
        return {}

    # Etiquetas que aparecen en el bloque label/valor del innerText.
    _SPEC_LABELS = {
        "año", "kilometraje", "combustible", "transmisión", "transmision",
        "estilo", "tracción", "traccion", "modelo", "marca",
        "tamaño del motor", "tamano del motor",
        "color", "color exterior", "color interior",
        "versión", "version", "equipamiento", "ubicación", "ubicacion",
        "tipo", "carrocería", "carroceria",
    }

    @classmethod
    def _extract_specs_from_text(cls, body_text: str) -> dict:
        """
        Parsea el bloque label/valor del innerText. Cada label conocida
        ocupa una línea propia y el valor está en la siguiente línea
        no vacía. Solo registramos la PRIMERA aparición de cada label,
        para evitar capturar valores de cards de "anuncios similares"
        que aparecen más abajo.
        """
        if not body_text:
            return {}
        lines = [ln.strip() for ln in body_text.splitlines()]
        specs: dict = {}
        i = 0
        n = len(lines)
        while i < n:
            label = lines[i].lower().rstrip(":")
            if label in cls._SPEC_LABELS:
                # Buscar el siguiente line no vacío como valor
                j = i + 1
                while j < n and not lines[j]:
                    j += 1
                if j < n:
                    value = lines[j]
                    # Si el "valor" es a su vez otra label, lo descartamos.
                    if value.lower().rstrip(":") not in cls._SPEC_LABELS:
                        specs.setdefault(label, value)
                    i = j
            i += 1
        return specs

    @staticmethod
    def _parse_int(value) -> Optional[int]:
        """Extrae un entero a partir de int/float/str con separadores."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        cleaned = re.sub(r"[^\d]", "", str(value))
        return int(cleaned) if cleaned else None

    def _parse_h1(
        self, h1: str, brand_hint: Optional[str]
    ) -> tuple[Optional[str], Optional[str], Optional[int]]:
        """
        Extrae (marca, modelo, año) del H1 al estilo "Hyundai Accent 2016".
        Si `brand_hint` (típicamente JSON-LD manufacturer) coincide, lo usa
        para no equivocarse con marcas multi-palabra.
        """
        if not h1:
            return None, None, None

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", h1)
        year = int(year_match.group(1)) if year_match else None

        cleaned = re.sub(r"\b(19\d{2}|20\d{2})\b", "", h1, count=1).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)

        # Si tenemos hint de marca y el H1 empieza con esa marca, úsala.
        if brand_hint:
            hint_lc = brand_hint.lower()
            if cleaned.lower().startswith(hint_lc + " "):
                model = cleaned[len(brand_hint):].strip()
                return brand_hint, (model or None), year
            if cleaned.lower() == hint_lc:
                return brand_hint, None, year

        # Marcas multi-palabra (Land Rover, Mercedes-Benz, ...).
        lowered = cleaned.lower()
        for brand_key in _MULTI_WORD_BRANDS:
            if lowered == brand_key or lowered.startswith(brand_key + " "):
                n_tokens = len(brand_key.split())
                tokens = cleaned.split(None, n_tokens)
                brand = " ".join(tokens[:n_tokens])
                model = tokens[n_tokens] if len(tokens) > n_tokens else None
                return brand, model, year

        parts = cleaned.split(None, 1)
        if len(parts) >= 2:
            return parts[0], parts[1], year
        if len(parts) == 1:
            return parts[0], None, year
        return None, None, year

    @staticmethod
    def _extract_price_from_text(body_text: str) -> tuple[Optional[int], Optional[str]]:
        """Fallback: busca el primer precio (₡ o $) en el innerText."""
        if not body_text:
            return None, None
        m = re.search(r"([₡¢])\s*([\d.,]+)", body_text)
        if m:
            return int(re.sub(r"[^\d]", "", m.group(2))), "CRC"
        m = re.search(r"\$\s*([\d.,]+)", body_text)
        if m:
            return int(re.sub(r"[^\d]", "", m.group(1))), "USD"
        return None, None

    @staticmethod
    def _detect_seller_type(body_text: str) -> Optional[str]:
        """Detecta tipo de vendedor a partir del badge en el detalle."""
        if not body_text:
            return None
        # E24 muestra una etiqueta "PROFESIONAL" o "PARTICULAR" en mayúsculas
        # justo encima del bloque de contacto del vendedor.
        if re.search(r"\bPROFESIONAL\b", body_text):
            return "agencia"
        if re.search(r"\bPARTICULAR\b", body_text, re.I):
            return "particular"
        return None

    @staticmethod
    def _extract_description(soup: BeautifulSoup, body_text: str) -> Optional[str]:
        """Saca la descripción del meta tag (más limpio que el innerText)."""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"][:5000]
        meta = soup.find("meta", attrs={"property": "og:description"})
        if meta and meta.get("content"):
            return meta["content"][:5000]
        # Fallback al cuerpo: la sección "Descripción" va seguida del texto.
        if body_text:
            m = re.search(
                r"Descripci[oó]n\s*\n+(.+?)(?:\n{2,}|Publicado por)",
                body_text,
                re.DOTALL,
            )
            if m:
                return m.group(1).strip()[:5000]
        return None

    @staticmethod
    def _extract_photos(
        soup: BeautifulSoup, external_id: Optional[str]
    ) -> Optional[list]:
        """
        Las fotos siguen el patrón
            https://photos.encuentra24.com/.../cr/<a>/<b>/<c>/<d>/<id>_<hash>
        donde <id> es el external_id del anuncio. Filtramos por ese ID
        y deduplicamos por el hash final para descartar miniaturas repetidas.
        """
        if not external_id:
            return None
        pattern = re.compile(
            r"https?://photos\.encuentra24\.com/[^\s\"']*?/"
            + re.escape(external_id)
            + r"_([A-Za-z0-9]+)"
        )
        seen_hashes: dict[str, str] = {}
        order: list[str] = []
        for img in soup.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or ""
            )
            srcs = [src]
            srcset = img.get("srcset") or ""
            if srcset:
                # srcset trae varias URLs separadas por comas + espacios+ancho
                srcs.extend(
                    p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()
                )
            for s in srcs:
                m = pattern.search(s)
                if not m:
                    continue
                h = m.group(1)
                if h in seen_hashes:
                    continue
                # Quedarnos con la URL original sin el width-suffix del srcset.
                full_url = m.group(0)
                seen_hashes[h] = full_url
                order.append(h)
        photos = [seen_hashes[h] for h in order]
        return photos if photos else None
