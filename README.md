# DecaScout

DecaScout is a cross-country Decathlon price dashboard. The browser reads one current generated snapshot; it does not fetch retailer pages and it does not display price history.

## Run locally

```bash
python3 server.py
```

Open <http://127.0.0.1:8080/decascout.html>.

The checked-in `data/catalog.json` is a small fixture so the interface is usable immediately. Generate a real snapshot with:

```bash
python3 scripts/discover_catalog.py
```

Scan only some countries, several in parallel, with a live progress line:

```bash
python3 scripts/discover_catalog.py -c de,fr,at --store-jobs 3 --workers 8
```

`--store-jobs` sets how many countries run at once (default 4); `--workers` is the fetch concurrency per country. A `--country` run refreshes just those markets and keeps the other markets' previous data in the output files.

The collector is dependency-free and writes:

- `data/catalog.json` — the current product/price/availability snapshot consumed by the website;
- `data/catalog.csv` — one row per product and market offer;
- `data/stores.json` — discovered official store coverage and scan status;
- `data/delta.json` — products and stores newly found or no longer observed, price changes, and availability changes;
- `data/history/<product-id>.json` — per-product event and snapshot history for analysis only.

## Catalogue refresh workflow

`.github/workflows/daily-catalog.yml` runs the collector and commits the refreshed snapshot. **The daily schedule is currently disabled** (the `schedule` trigger is commented out); the workflow only runs when started manually from the Actions tab. Its optional `countries` input takes comma-separated codes such as `de,fr` and maps to `--country`. To re-enable the daily run, uncomment the `schedule` block.

The collector discovers country shops from Decathlon’s official global local-sites page, follows each shop’s public `robots.txt`/sitemap trail, extracts product URLs and model IDs, fetches the public product pages, and normalizes prices to EUR. No login, bot-protection bypass, or authenticated endpoint is used.

The collector keeps all product IDs found across every successfully scanned store. A product is only marked globally vanished when every store that previously carried it completed the new scan. Partial or blocked stores are retained in the coverage metadata so an outage does not create false disappearances.

A full crawl takes time and may hit retailer rate limits or regional blocking. Use an approved feed or retailer partnership if DecaScout is deployed as a public commercial service.

## GitHub Pages deployment

The site is served at `https://decascout.sunken.dev`.

1. In **Settings → Pages**, choose **GitHub Actions** as the source.
2. Create a DNS CNAME record for `decascout.sunken.dev` pointing to `<github-owner>.github.io`.
3. Keep the committed `CNAME` file in place. GitHub issues HTTPS once the DNS record resolves.

`.github/workflows/pages.yml` runs the tests, assembles a static artifact (`index.html` from `decascout.html`, the current snapshot, favicon, `robots.txt`, `sitemap.xml`, and the social image) and deploys it. It runs on pushes to `main`, manually, and after a successful catalogue refresh. `.github/workflows/ci.yml` runs the tests on pull requests, and Dependabot keeps the action versions current weekly.

The root `index.html` is only a redirect for branch-based Pages setups; the Actions deployment publishes the dashboard as the root page.

## SEO, accessibility and social preview

`decascout.html` carries a description, canonical URL, Open Graph and Twitter card tags, and schema.org `WebApplication` JSON-LD. It has a skip link, visible focus styles, reduced-motion support, and a basket drawer that is inert while closed, closes on Escape and returns focus to its trigger.

The 1200×630 social image lives at `assets/og-image.png`. Regenerate it with `python3 scripts/make_og_image.py` (needs Pillow and macOS system fonts).

## Tests

```bash
python3 -m unittest discover -s tests -v
```
