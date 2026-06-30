"""
Probe v3: confirm page=N pagination on autos-usados, find total page count,
and inspect a single detail page for structure.
"""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "probe_e24_out"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

LIST_PAGES = [
    "https://www.encuentra24.com/costa-rica-es/autos-usados",
    "https://www.encuentra24.com/costa-rica-es/autos-usados?page=2",
    "https://www.encuentra24.com/costa-rica-es/autos-usados?page=10",
    "https://www.encuentra24.com/costa-rica-es/autos-usados?page=50",
]

DETAIL = "https://www.encuentra24.com/costa-rica-es/autos-usados/hyundai-accent/31856338"


async def grab_listing(url: str, idx: int):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"goto err: {e}")
            await browser.close()
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        for _ in range(4):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(0.3)
        await asyncio.sleep(1)

        anchors = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))
        """)
        listings = []
        seen = set()
        for h in anchors:
            if not h:
                continue
            m = re.search(r"^/costa-rica-es/(?:autos-usados|autos-motos)/[^/]+/(\d{6,})$", h)
            if m and h not in seen:
                seen.add(h)
                listings.append(h)

        # try to find total count text in the page
        body_text = await page.evaluate("() => document.body.innerText")
        total_hint = ""
        m = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:resultados|anuncios|car|veh)", body_text, re.I)
        if m:
            total_hint = m.group(0)

        # Pagination text
        m2 = re.search(r"(p[áa]gina|page)\s*\d+\s*(?:de|of)\s*(\d+)", body_text, re.I)
        page_total = m2.group(0) if m2 else ""

        html = await page.content()
        (OUT / f"v3_list_{idx}.html").write_text(html, encoding="utf-8")
        print(f"\n=== {url}")
        print(f"  found {len(listings)} listings")
        for l in listings[:5]:
            print(f"   {l}")
        print(f"  total_hint: {total_hint!r}")
        print(f"  page_total: {page_total!r}")
        await browser.close()


async def grab_detail():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        try:
            await page.goto(DETAIL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"detail goto err: {e}")
            await browser.close()
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(1)

        # Capture useful selectors
        h1 = await page.evaluate("() => document.querySelector('h1')?.innerText || ''")
        text = await page.evaluate("() => document.body.innerText")
        # Find all images
        imgs = await page.evaluate("() => Array.from(document.querySelectorAll('img')).map(i => i.src)")
        # find ld+json
        ld = await page.evaluate("""
            () => Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.textContent)
        """)
        # Find any <meta property="og:..."> values
        meta = await page.evaluate("""
            () => Array.from(document.querySelectorAll('meta')).map(m => ({
                name: m.getAttribute('name') || m.getAttribute('property'), content: m.getAttribute('content')
            })).filter(x => x.name)
        """)

        html = await page.content()
        (OUT / "v3_detail.html").write_text(html, encoding="utf-8")
        out = {
            "h1": h1,
            "body_text_first_4000": text[:4000],
            "img_count": len(imgs),
            "img_samples": imgs[:30],
            "ld_count": len(ld),
            "ld_samples": [s[:1500] for s in ld],
            "meta": meta[:40],
        }
        (OUT / "v3_detail.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\n=== detail page captured ===")
        print(f"  h1: {h1[:200]}")
        print(f"  imgs: {len(imgs)}, ld: {len(ld)}")
        print("  ld sample:", (ld[0][:400] if ld else "—"))
        await browser.close()


async def main():
    for i, u in enumerate(LIST_PAGES):
        await grab_listing(u, i)
    await grab_detail()


if __name__ == "__main__":
    asyncio.run(main())
