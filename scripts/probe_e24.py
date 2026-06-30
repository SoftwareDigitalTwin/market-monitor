"""
Probe: capture all network requests on Encuentra24's vehicle search page.
Goal: find the real listings API or paginated URL that Next.js consumes.
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

# Try several candidate listing URLs
CANDIDATES = [
    "https://www.encuentra24.com/costa-rica-es/autos",
    "https://www.encuentra24.com/costa-rica-es/bienes-vehiculos-usados",
    "https://www.encuentra24.com/costa-rica-es/autos-motos",
    "https://www.encuentra24.com/costa-rica-es/cnsearch?q=autos",
]


async def probe(url: str, idx: int):
    requests_log = []
    responses_log = []
    listing_hrefs = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        async def on_req(req):
            requests_log.append({"url": req.url, "method": req.method, "type": req.resource_type})

        async def on_resp(resp):
            try:
                ct = resp.headers.get("content-type", "")
            except Exception:
                ct = ""
            entry = {
                "url": resp.url,
                "status": resp.status,
                "content_type": ct,
            }
            # Capture small JSON bodies that look like listings
            if "json" in ct and resp.status == 200:
                try:
                    body = await resp.body()
                    if len(body) < 500_000:
                        entry["sample"] = body[:1500].decode("utf-8", errors="replace")
                        entry["size"] = len(body)
                except Exception as e:
                    entry["body_err"] = str(e)
            responses_log.append(entry)

        page.on("request", on_req)
        page.on("response", on_resp)

        print(f"\n=== probing {url} ===")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"goto err: {e}")

        # Wait for network to settle a bit and any XHR to fire
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Scroll to trigger lazy loads
        for _ in range(8):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(0.5)

        await asyncio.sleep(2)

        # Collect anchors that look like listing detail pages
        anchors = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))
        """)
        for h in anchors:
            if not h:
                continue
            if re.search(r"/costa-rica-es/.+/\d{6,}", h):
                listing_hrefs.add(h)

        html = await page.content()
        (OUT / f"page_{idx}.html").write_text(html, encoding="utf-8")
        await browser.close()

    out = {
        "url": url,
        "anchor_listing_hrefs": sorted(listing_hrefs)[:30],
        "anchor_count": len(listing_hrefs),
        "requests": requests_log,
        "responses": responses_log,
    }
    (OUT / f"probe_{idx}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  anchors w/ id: {len(listing_hrefs)}")
    print(f"  requests: {len(requests_log)}, responses: {len(responses_log)}")

    # Quick filter: which response URLs look interesting (not analytics, not images)
    interesting = []
    for r in responses_log:
        u = r["url"]
        ct = r.get("content_type", "")
        if "json" not in ct:
            continue
        if any(s in u for s in ["clickhouse-tracker", "google", "doubleclick", "facebook", "/gtag/"]):
            continue
        interesting.append((r["status"], r.get("size", 0), u))
    print(f"  interesting JSON responses ({len(interesting)}):")
    for s, sz, u in interesting[:30]:
        print(f"    {s} {sz}b {u[:160]}")


async def main():
    for i, u in enumerate(CANDIDATES):
        await probe(u, i)


if __name__ == "__main__":
    asyncio.run(main())
