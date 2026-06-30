"""
Second probe: try the actual category path /costa-rica-es/autos-usados
and look for pagination/API.
"""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "probe_e24_out"
OUT.mkdir(exist_ok=True)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CANDIDATES = [
    "https://www.encuentra24.com/costa-rica-es/autos-usados",
    "https://www.encuentra24.com/costa-rica-es/autos-usados?page=2",
    "https://www.encuentra24.com/costa-rica-es/autos-usados?o=24",
    "https://www.encuentra24.com/costa-rica-es/cnsearch?cat=autos-usados",
    # cnSearch is the search engine of encuentra24
    "https://www.encuentra24.com/costa-rica-es/cnsearch?categoryName=autos-usados&country=cr",
]


async def probe(url: str, idx: int):
    requests_log = []
    responses_log = []
    listing_hrefs = set()
    pagination_links = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        async def on_resp(resp):
            try:
                ct = resp.headers.get("content-type", "")
            except Exception:
                ct = ""
            entry = {"url": resp.url, "status": resp.status, "ct": ct}
            if "json" in ct and resp.status == 200:
                try:
                    body = await resp.body()
                    if len(body) < 800_000:
                        entry["sample"] = body[:600].decode("utf-8", errors="replace")
                        entry["size"] = len(body)
                except Exception:
                    pass
            responses_log.append(entry)

        page.on("response", on_resp)

        print(f"\n=== probing {url} ===")
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

        for _ in range(6):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(0.4)
        await asyncio.sleep(1.5)

        anchors = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))
        """)
        for h in anchors:
            if not h:
                continue
            if re.search(r"/costa-rica-es/.+/\d{6,}", h) and "/user/" not in h:
                listing_hrefs.add(h)
            if re.search(r"(\?|&)(o|page|p)=\d+", h):
                pagination_links.add(h)

        # Look for "next page" markers in HTML
        html = await page.content()
        (OUT / f"v2_page_{idx}.html").write_text(html, encoding="utf-8")
        await browser.close()

    interesting = []
    for r in responses_log:
        u = r["url"]
        ct = r.get("ct", "")
        if "json" not in ct:
            continue
        if any(s in u for s in ["clickhouse-tracker", "google", "doubleclick", "facebook",
                                "/gtag/", "linkedin", "creativecdn", "monitoring",
                                "bing", "tiktok"]):
            continue
        interesting.append((r["status"], r.get("size", 0), u, r.get("sample", "")[:200]))

    out = {
        "url": url,
        "anchor_listing_hrefs": sorted(listing_hrefs),
        "anchor_count": len(listing_hrefs),
        "pagination_links": sorted(pagination_links),
        "interesting_json": [{"status": s, "size": sz, "url": u, "sample": sm} for s, sz, u, sm in interesting],
    }
    (OUT / f"v2_probe_{idx}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  listing anchors: {len(listing_hrefs)}")
    print(f"  pagination_links: {len(pagination_links)}")
    for p in sorted(pagination_links)[:8]:
        print(f"    pg {p}")
    print(f"  interesting JSON: {len(interesting)}")
    for s, sz, u, sm in interesting[:8]:
        print(f"    {s} {sz}b {u[:140]}")


async def main():
    for i, u in enumerate(CANDIDATES):
        await probe(u, i)


if __name__ == "__main__":
    asyncio.run(main())
