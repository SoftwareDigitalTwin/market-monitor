"""
Agente de scraping para CRAutos (www.crautos.com).
Portal principal de vehículos usados en Costa Rica.

Estructura del sitio:
- Búsqueda: /autosusados/search.cfm
- Paginación: parámetro 'pg'
- Listado de resultados con links a páginas individuales
- Cada anuncio tiene datos estructurados en la página de detalle
"""

import re
import asyncio
import logging
from datetime import date
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from dtc.scrapers.base_scraper import BaseScraper
from dtc.normalizer.equivalences import BRAND_MAP

logger = logging.getLogger(__name__)

BASE_URL = "https://www.crautos.com"

# Marcas con nombre de varias palabras, ordenadas por longitud descendente
# para que el match sea greedy ("great wall motors" antes que "great wall").
_MULTI_WORD_BRANDS = sorted(
    (k for k in BRAND_MAP if " " in k),
    key=len,
    reverse=True,
)


class CRAutosScraper(BaseScraper):
    """Scraper para CRAutos."""

    def __init__(self, limit: Optional[int] = None):
        super().__init__(source_name="CRAutos", limit=limit)

    def build_search_url(self, page_number: int) -> str:
        """Construye URL de búsqueda paginada."""
        return f"{BASE_URL}/autosusados/index.cfm?pg={page_number}"

    async def get_listing_urls(self) -> list[str]:
        """
        Recorre páginas hasta que una no aporte IDs nuevos.
        CRAutos no expone el total de páginas en el HTML, así que iteramos
        incrementalmente con un tope de seguridad.
        """
        seen: set[str] = set()
        urls: list[str] = []
        max_pages = 30
        empty_pages_in_a_row = 0
        target = self.limit if self.limit else None

        for page_num in range(1, max_pages + 1):
            search_url = self.build_search_url(page_num)
            logger.info(f"Procesando página {page_num}: {search_url}")
            try:
                soup = await self.get_page_soup(search_url)
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning(f"Timeout/error en pg {page_num}: {e}. Detengo discovery.")
                # Abortar navegación pendiente para no contaminar el próximo goto
                try:
                    await self.page.evaluate("window.stop()")
                except Exception:
                    pass
                break

            self.stats["total_pages"] += 1
            listing_links = soup.find_all(
                "a", href=re.compile(r"cardetail\.cfm\?c=\d+", re.I)
            )

            new_in_page = 0
            for link in listing_links:
                href = link.get("href", "")
                if not href:
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
                logger.info(f"Cupo de {target} alcanzado, detengo discovery.")
                break

            if new_in_page == 0:
                empty_pages_in_a_row += 1
                if empty_pages_in_a_row >= 2:
                    logger.info("Sin URLs nuevas en 2 páginas seguidas. Detengo.")
                    break
            else:
                empty_pages_in_a_row = 0

            await asyncio.sleep(self.config.delay_between_pages)

        logger.info(f"Total de URLs de anuncios encontradas: {len(urls)}")
        return urls

    async def parse_listing(self, url: str) -> Optional[dict]:
        """Extrae datos de un anuncio individual de CRAutos."""
        try:
            # Cargar página y esperar a que la galería de fotos del vehículo
            # aparezca (se inyecta vía JS). Si no aparece en 5s asumimos que
            # el anuncio no tiene fotos y seguimos.
            await self.page.goto(url, wait_until="domcontentloaded")
            try:
                await self.page.wait_for_selector(
                    'img[src*="clasificados/usados"]', timeout=5000
                )
            except Exception:
                pass
            await asyncio.sleep(self.config.delay_between_requests)
            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            data = {
                "url": url,
                "external_id": self._extract_external_id(url),
            }

            # El <title> de CRAutos contiene marca, modelo, año y ambos precios:
            #   "crautos.com Hyundai I20 2020 ¢ 8,600,000 ($ 17,842)*"
            title_tag = soup.find("title")
            title_text = title_tag.get_text(" ", strip=True) if title_tag else ""

            # H1 también tiene "Hyundai I20 2020"
            h1 = soup.find("h1")
            h1_text = h1.get_text(strip=True) if h1 else ""

            brand, model, year_from_title = self._parse_title(h1_text or title_text)
            data["raw_brand"] = brand
            data["raw_model"] = model

            # Buscar campos en tablas de especificaciones
            specs = self._extract_specs(soup)

            data["raw_year"] = (
                year_from_title
                or specs.get("año") or specs.get("year") or specs.get("ano")
            )
            data["raw_km"] = self._parse_number(
                specs.get("kilometraje") or specs.get("km") or specs.get("recorrido")
            )

            # Precios: preferir los del <title> (CRC y USD); usar USD como canónico
            price_crc, price_usd = self._extract_prices_from_title(title_text)
            if price_usd:
                data["raw_price"] = price_usd
                data["raw_currency"] = "USD"
            elif price_crc:
                data["raw_price"] = price_crc
                data["raw_currency"] = "CRC"
            else:
                data["raw_price"] = self._extract_price(soup)
                data["raw_currency"] = self._extract_currency(soup)

            data["raw_body_style"] = specs.get("estilo") or specs.get("tipo") or specs.get("carrocería")
            data["raw_drivetrain"] = specs.get("tracción") or specs.get("traccion") or specs.get("drive")
            data["raw_transmission"] = specs.get("transmisión") or specs.get("transmision") or specs.get("caja")
            data["raw_fuel"] = specs.get("combustible") or specs.get("fuel")
            data["raw_seller_type"] = self._extract_seller_type(soup)
            data["raw_exterior_color"] = specs.get("color exterior") or specs.get("color")
            data["raw_interior_color"] = specs.get("color interior")
            data["raw_trim"] = specs.get("versión") or specs.get("version") or specs.get("trim")
            data["raw_description"] = self._extract_description(soup)
            data["raw_photos"] = self._extract_photos(soup)

            return data

        except Exception as e:
            logger.error(f"Error parseando anuncio {url}: {e}")
            return None

    @staticmethod
    def _extract_prices_from_title(title: str) -> tuple[Optional[int], Optional[int]]:
        """Extrae (CRC, USD) del título: '... ¢ 8,600,000 ($ 17,842)*'."""
        if not title:
            return None, None
        crc = re.search(r"[¢₡]\s*([\d.,]+)", title)
        usd = re.search(r"\$\s*([\d.,]+)", title)
        crc_val = int(re.sub(r"[^\d]", "", crc.group(1))) if crc else None
        usd_val = int(re.sub(r"[^\d]", "", usd.group(1))) if usd else None
        return crc_val, usd_val

    def _extract_external_id(self, url: str) -> Optional[str]:
        """Extrae el ID externo del anuncio de la URL (cardetail.cfm?c=NNN)."""
        match = re.search(r"[?&]c=(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"id=(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _parse_title(self, title: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
        """Extrae (marca, modelo, año) del título del anuncio."""
        if not title:
            return None, None, None

        # Capturar año (primer match de 19xx/20xx) antes de limpiarlo
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
        year = int(year_match.group(1)) if year_match else None

        cleaned = re.sub(r"\b(19\d{2}|20\d{2})\b", "", title, count=1).strip()
        cleaned = re.sub(
            r"(crautos\.com|usad[oa]s?|en venta|costa rica)",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        # Cortar el ruido de precio si quedó pegado
        cleaned = re.sub(r"[¢₡\$].*$", "", cleaned).strip()
        # CRAutos usa \xa0 (non-breaking space) entre palabras como "Land Rover".
        # Colapsamos todo whitespace Unicode a un espacio normal para que el
        # match contra _MULTI_WORD_BRANDS funcione.
        cleaned = re.sub(r"\s+", " ", cleaned)

        # Match contra marcas multi-palabra (Land Rover, Mercedes Benz, ...).
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
        elif len(parts) == 1:
            return parts[0], None, year
        return None, None, year

    def _extract_specs(self, soup: BeautifulSoup) -> dict:
        """Extrae especificaciones de la página de detalle."""
        specs = {}

        # Buscar en tablas
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True).lower().rstrip(":")
                    value = cells[1].get_text(strip=True)
                    if key and value:
                        specs[key] = value

        # Buscar en listas de definiciones (dl/dt/dd)
        for dl in soup.find_all("dl"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                key = dt.get_text(strip=True).lower().rstrip(":")
                value = dd.get_text(strip=True)
                if key and value:
                    specs[key] = value

        # Buscar en divs con patrón label/value
        for div in soup.find_all("div", class_=re.compile(r"spec|detail|info|feature", re.I)):
            label = div.find(class_=re.compile(r"label|key|name", re.I))
            value = div.find(class_=re.compile(r"value|data|info", re.I))
            if label and value:
                key = label.get_text(strip=True).lower().rstrip(":")
                val = value.get_text(strip=True)
                if key and val:
                    specs[key] = val

        return specs

    def _extract_price(self, soup: BeautifulSoup) -> Optional[float]:
        """Extrae el precio del anuncio."""
        # Buscar elementos con clase de precio
        price_el = soup.find(class_=re.compile(r"price|precio", re.I))
        if price_el:
            price_text = price_el.get_text(strip=True)
            return self._parse_number(price_text)

        # Buscar patrón de precio en todo el texto
        text = soup.get_text()
        match = re.search(r"[\$₡]\s*([\d,.]+)", text)
        if match:
            return self._parse_number(match.group(1))

        return None

    def _extract_currency(self, soup: BeautifulSoup) -> Optional[str]:
        """Detecta la moneda del precio."""
        price_el = soup.find(class_=re.compile(r"price|precio", re.I))
        if price_el:
            text = price_el.get_text(strip=True)
            if "₡" in text or "CRC" in text.upper() or "colones" in text.lower():
                return "CRC"
            if "$" in text or "USD" in text.upper():
                return "USD"
        return None

    def _extract_seller_type(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Detecta el tipo de vendedor. Solo retorna 'particular' o 'agencia'
        si encuentra una etiqueta clara; nunca devuelve el blob completo
        del bloque del vendedor (que contiene nombre/teléfono).
        """
        # Buscar badges/etiquetas pequeñas (≤30 chars) con la palabra clave
        for el in soup.find_all(class_=re.compile(r"badge|tag|label|tipo|kind", re.I)):
            text = el.get_text(" ", strip=True).lower()
            if not text or len(text) > 30:
                continue
            if "particular" in text or "privado" in text:
                return "particular"
            if "agencia" in text or "dealer" in text or "concesionario" in text:
                return "agencia"

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extrae la descripción del anuncio."""
        desc = soup.find(class_=re.compile(r"description|descripcion|comment", re.I))
        if desc:
            return desc.get_text(strip=True)[:5000]  # Limitar longitud
        return None

    def _extract_photos(self, soup: BeautifulSoup) -> Optional[list]:
        """
        Extrae URLs de las fotos del anuncio.
        En CRAutos las fotos siguen el patrón:
            https://crautos.com/clasificados/usados/<id>-<n>.jpg
        Las ordenamos por <n> y descartamos duplicados.
        """
        pattern = re.compile(
            r"clasificados/usados/(\d+)-(\d+)\.(?:jpg|jpeg|png|webp)", re.I
        )

        seen = {}
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy")
            if not src:
                continue
            full_url = urljoin(BASE_URL, src)
            m = pattern.search(full_url)
            if not m:
                continue
            idx = int(m.group(2))
            seen.setdefault(idx, full_url)

        photos = [seen[k] for k in sorted(seen)]
        return photos if photos else None

    @staticmethod
    def _parse_number(text) -> Optional[int]:
        """Extrae un número de un texto."""
        if text is None:
            return None
        if isinstance(text, (int, float)):
            return int(text)
        # Remover todo excepto dígitos y punto
        cleaned = re.sub(r"[^\d]", "", str(text))
        if cleaned:
            return int(cleaned)
        return None
