#!/usr/bin/env python3
"""Discover Decathlon products and write one current daily catalogue.

The collector intentionally works with public pages and public sitemaps only.
It does not log in, evade bot protection, or try to turn a blocked page into a
successful scan.  A failed/partial store scan is recorded as such so a single
outage cannot make every product in that market look vanished.

The generated ``data/catalog.json`` is the website's only product data source.
Per-product files in ``data/history`` keep event and snapshot history for later
analysis, but are not loaded by the web UI.
"""

from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_STORES_PAGE = "https://www.decathlon-united.media/en_GB/around-the-world/"
MAX_PAGE_BYTES = 8_000_000
FETCH_TIMEOUT_SECONDS = 25
USER_AGENT = os.environ.get(
    "DECASCOUT_USER_AGENT",
    "DecaScout catalogue refresh (+respectful public sitemap/product-page fetcher)",
)


def _store(code: str, name: str, domain: str, currency: str) -> dict[str, str]:
    return {
        "code": code,
        "name": name,
        "short": code.upper(),
        "domain": domain,
        "website": f"https://{domain}",
        "currency": currency,
        "symbol": {"EUR": "€", "GBP": "£", "USD": "$", "CHF": "CHF", "PLN": "zł", "CZK": "Kč"}.get(currency.upper(), currency.upper()),
    }


# This is a safety-net catalogue of the official local websites.  The same
# list is also used as metadata when the official page discovers a host.  The
# page is fetched on every run, so newly added official hosts can be included
# without changing this file.
DEFAULT_STORE_DATA = [
    ("dz", "Algeria", "www.decathlon.com.dz", "DZD"),
    ("au", "Australia", "www.decathlon.com.au", "AUD"),
    ("at", "Austria", "www.decathlon.at", "EUR"),
    ("be", "Belgium", "www.decathlon.be", "EUR"),
    ("br", "Brazil", "www.decathlon.com.br", "BRL"),
    ("bg", "Bulgaria", "www.decathlon.bg", "BGN"),
    ("kh", "Cambodia", "www.decathlon.com.kh", "USD"),
    ("ca", "Canada", "www.decathlon.ca", "CAD"),
    ("cl", "Chile", "www.decathlon.cl", "CLP"),
    ("cn", "China", "www.decathlon.com.cn", "CNY"),
    ("co", "Colombia", "www.decathlon.com.co", "COP"),
    ("hr", "Croatia", "www.decathlon.hr", "EUR"),
    ("cz", "Czechia", "www.decathlon.cz", "CZK"),
    ("cd", "Democratic Republic of the Congo", "decathlon.cd", "USD"),
    ("eg", "Egypt", "www.decathlon.eg", "EGP"),
    ("fr", "France", "www.decathlon.fr", "EUR"),
    ("de", "Germany", "www.decathlon.de", "EUR"),
    ("gh", "Ghana", "www.decathlon.com.gh", "GHS"),
    ("gr", "Greece", "www.decathlon.com.gr", "EUR"),
    ("hk", "Hong Kong", "www.decathlon.com.hk", "HKD"),
    ("hu", "Hungary", "www.decathlon.hu", "HUF"),
    ("mu", "Mauritius", "decathlon.mu", "MUR"),
    ("in", "India", "www.decathlon.in", "INR"),
    ("id", "Indonesia", "www.decathlon.co.id", "IDR"),
    ("ie", "Ireland", "www.decathlon.ie", "EUR"),
    ("il", "Israel", "www.decathlon.co.il", "ILS"),
    ("it", "Italy", "www.decathlon.it", "EUR"),
    ("ci", "Ivory Coast", "www.decathlon.ci", "XOF"),
    ("jp", "Japan", "www.decathlon.co.jp", "JPY"),
    ("kz", "Kazakhstan", "www.decathlon.kz", "KZT"),
    ("ke", "Kenya", "www.decathlon.co.ke", "KES"),
    ("kw", "Kuwait", "decathlon.com.kw", "KWD"),
    ("lv", "Latvia", "decathlon.lv", "EUR"),
    ("lb", "Lebanon", "decathlon.com.lb", "USD"),
    ("lt", "Lithuania", "www.decathlon.lt", "EUR"),
    ("my", "Malaysia", "www.decathlon.my", "MYR"),
    ("mt", "Malta", "www.decathlon.mt", "EUR"),
    ("mx", "Mexico", "www.decathlon.com.mx", "MXN"),
    ("ma", "Morocco", "www.decathlon.ma", "MAD"),
    ("nl", "Netherlands", "www.decathlon.nl", "EUR"),
    ("ph", "Philippines", "www.decathlon.ph", "PHP"),
    ("pl", "Poland", "www.decathlon.pl", "PLN"),
    ("pt", "Portugal", "www.decathlon.pt", "EUR"),
    ("qa", "Qatar", "decathlon.qa", "QAR"),
    ("rs", "Serbia", "www.decathlon.rs", "RSD"),
    ("ro", "Romania", "www.decathlon.ro", "RON"),
    ("sn", "Senegal", "www.decathlon.sn", "XOF"),
    ("sg", "Singapore", "www.decathlon.sg", "SGD"),
    ("sk", "Slovakia", "www.decathlon.sk", "EUR"),
    ("si", "Slovenia", "www.decathlon.si", "EUR"),
    ("za", "South Africa", "www.decathlon.co.za", "ZAR"),
    ("kr", "South Korea", "www.decathlon.co.kr", "KRW"),
    ("es", "Spain", "www.decathlon.es", "EUR"),
    ("se", "Sweden", "www.decathlon.se", "SEK"),
    ("ch", "Switzerland", "www.decathlon.ch", "CHF"),
    ("tw", "Taiwan", "www.decathlon.tw", "TWD"),
    ("th", "Thailand", "www.decathlon.co.th", "THB"),
    ("tn", "Tunisia", "www.decathlon.tn", "TND"),
    ("tr", "Türkiye", "www.decathlon.com.tr", "TRY"),
    ("ua", "Ukraine", "www.decathlon.ua", "UAH"),
    ("ae", "United Arab Emirates", "decathlon.ae", "AED"),
    ("gb", "United Kingdom", "www.decathlon.co.uk", "GBP"),
    ("us", "United States", "www.decathlon.com", "USD"),
    ("vn", "Vietnam", "www.decathlon.vn", "VND"),
]
FALLBACK_RATES_FROM_EUR = {
    "EUR": 1.0,
    "AED": 3.95,
    "AUD": 1.78,
    "BGN": 1.96,
    "BRL": 6.10,
    "CAD": 1.56,
    "CHF": 0.94,
    "CLP": 1_050.0,
    "CNY": 8.10,
    "COP": 4_650.0,
    "CZK": 24.90,
    "DZD": 145.0,
    "EGP": 54.0,
    "GBP": 0.86,
    "GHS": 17.0,
    "HKD": 8.55,
    "HUF": 395.0,
    "IDR": 17_500.0,
    "ILS": 4.05,
    "INR": 92.0,
    "JPY": 170.0,
    "KES": 145.0,
    "KRW": 1_600.0,
    "KWD": 0.33,
    "KZT": 560.0,
    "MAD": 10.8,
    "MUR": 52.0,
    "MXN": 22.0,
    "MYR": 4.75,
    "PHP": 64.0,
    "PLN": 4.30,
    "QAR": 3.95,
    "RON": 5.10,
    "RSD": 117.0,
    "SEK": 11.2,
    "SGD": 1.47,
    "THB": 37.5,
    "TND": 3.35,
    "TRY": 50.0,
    "TWD": 36.5,
    "UAH": 48.0,
    "VND": 30_000.0,
    "XOF": 655.957,
    "ZAR": 20.0,
}

CURRENCY_SYMBOLS = {
    "AED": "AED",
    "AUD": "A$",
    "BRL": "R$",
    "CAD": "C$",
    "CHF": "CHF",
    "CNY": "¥",
    "CZK": "Kč",
    "DZD": "دج",
    "EGP": "E£",
    "EUR": "€",
    "GBP": "£",
    "HKD": "HK$",
    "HUF": "Ft",
    "IDR": "Rp",
    "ILS": "₪",
    "INR": "₹",
    "JPY": "¥",
    "KRW": "₩",
    "KWD": "KWD",
    "MAD": "MAD",
    "MXN": "MX$",
    "MYR": "RM",
    "PHP": "₱",
    "PLN": "zł",
    "QAR": "QAR",
    "RON": "lei",
    "RSD": "дин",
    "SEK": "kr",
    "SGD": "S$",
    "THB": "฿",
    "TND": "TND",
    "TRY": "₺",
    "TWD": "NT$",
    "UAH": "₴",
    "VND": "₫",
    "XOF": "CFA",
    "ZAR": "R",
}

DEFAULT_STORES = [_store(*row) for row in DEFAULT_STORE_DATA]
STORE_BY_HOST = {store["domain"]: store for store in DEFAULT_STORES}

PAGE_CACHE: dict[str, str] = {}
CACHE_LOCK = Lock()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())


def fetch_text(url: str, accept: str = "text/html,application/xml;q=0.9,*/*;q=0.5") -> str:
    """Fetch one public page with a bounded response size and in-run cache."""
    with CACHE_LOCK:
        if url in PAGE_CACHE:
            return PAGE_CACHE[url]

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-GB,en;q=0.8,de;q=0.6,fr;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_PAGE_BYTES)
    text = raw.decode("utf-8", errors="replace")
    with CACHE_LOCK:
        PAGE_CACHE[url] = text
    return text


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_number(value: Any) -> float | None:
    """Parse common European, UK, and machine-readable price formats."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    text = html_lib.unescape(str(value)).replace("\xa0", " ").strip()
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) in {1, 2}:
            text = "".join(parts[:-1]) + "." + parts[-1]
        else:
            text = "".join(parts)
    elif text.count(".") > 1:
        parts = text.split(".")
        if len(parts[-1]) in {1, 2}:
            text = "".join(parts[:-1]) + "." + parts[-1]
        else:
            text = "".join(parts)

    try:
        return float(text)
    except ValueError:
        return None


def find_jsonld_product(page: str) -> dict[str, Any]:
    scripts = re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        page,
        flags=re.I | re.S,
    )

    def walk(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            kind = value.get("@type")
            if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
                return value
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None

    for script in scripts:
        try:
            found = walk(json.loads(html_lib.unescape(script)))
            if found:
                return found
        except (TypeError, ValueError):
            continue
    return {}


def extract_model_id(value: str, fallback: str = "") -> str:
    """Extract a Decathlon model/product ID from a URL or page fragment."""
    patterns = [
        r"(?:[?&](?:mc|sku|modelCode|model_code|productId|product_id)=)(\d{6,9})",
        r"(?:\b(?:model\s*code|modelcode|product\s*id|productid|ref(?:erence)?|id)\s*[:=#-]?\s*)(\d{6,9})",
        r"(?:^|[/_\-.])R-p-(\d{6,9})(?:[/_\-.?#]|$)",
        r"m(\d{6,9})(?:[/_\-.?#]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.I)
        if match:
            return match.group(1)
    return fallback


def infer_currency(page: str, store: dict[str, str], structured: dict[str, Any]) -> str:
    offers = structured.get("offers") if isinstance(structured, dict) else None
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict) and offers.get("priceCurrency"):
        return str(offers["priceCurrency"]).upper()
    match = re.search(r"(?:priceCurrency|currency)[\"']?\s*[:=]\s*[\"']([A-Z]{3})", page, flags=re.I)
    return match.group(1).upper() if match else store["currency"]


def find_price(page: str, structured: dict[str, Any]) -> float | None:
    offers = structured.get("offers") if isinstance(structured, dict) else None
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        for key in ("price", "lowPrice"):
            price = parse_number(offers.get(key))
            if price is not None:
                return price

    patterns = [
        r"(?:current price|aktueller preis|prix actuel|precio actual|prezzo attuale|price|preis|prix|precio|prezzo)\s*[:\-]?\s*([0-9][0-9.,]*)\s*(?:€|EUR|CHF|PLN|CZK|zł|Kč)?",
        r"[\"'](?:price|currentPrice|salePrice)[\"']\s*[:=]\s*[\"']?([0-9]+(?:[.,][0-9]{1,2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.I)
        if match:
            price = parse_number(match.group(1))
            if price is not None:
                return price
    return None


def product_url_candidates(page: str, base_url: str) -> list[str]:
    candidates: list[str] = []
    for raw_href in re.findall(r"(?:href|canonical)=[\"']([^\"']+)", page, flags=re.I):
        href = html_lib.unescape(raw_href)
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = normalise_url(urljoin(base_url, href))
        if is_product_url(absolute):
            candidates.append(absolute)
    return list(dict.fromkeys(candidates))


def normalise_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse(("https", parsed.netloc.lower(), parsed.path or "/", "", parsed.query, ""))


def is_product_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return bool(
        "/p/" in path
        or "/product/" in path
        or "/products/" in path
        or "/_/r-p-" in path
        or "mc=" in parsed.query.lower()
        or "sku=" in parsed.query.lower()
    )


def sitemap_locs(text: str) -> list[str]:
    return [
        html_lib.unescape(value).strip()
        for value in re.findall(r"<loc[^>]*>(.*?)</loc>", text, flags=re.I | re.S)
        if value.strip()
    ]


def discover_sitemaps(website: str) -> list[str]:
    robots_url = website.rstrip("/") + "/robots.txt"
    found: list[str] = []
    try:
        robots = fetch_text(robots_url, accept="text/plain,*/*;q=0.5")
        found.extend(
            match.group(1).strip()
            for match in re.finditer(r"^\s*Sitemap:\s*(\S+)", robots, flags=re.I | re.M)
        )
    except (HTTPError, URLError, TimeoutError, OSError):
        pass

    if not found:
        found.extend(
            urljoin(website.rstrip("/") + "/", path)
            for path in ("sitemap.xml", "sitemap_index.xml", "sitemap-index.xml")
        )
    return list(dict.fromkeys(normalise_url(item) for item in found if normalise_url(item)))


def collect_product_urls(website: str) -> tuple[list[str], list[str], list[str]]:
    """Return product URLs, visited sitemap URLs, and scan errors."""
    queue = [(url, 0) for url in discover_sitemaps(website)]
    visited: set[str] = set()
    product_urls: set[str] = set()
    errors: list[str] = []

    while queue:
        sitemap_url, depth = queue.pop(0)
        if sitemap_url in visited or depth > 4:
            continue
        visited.add(sitemap_url)
        try:
            text = fetch_text(sitemap_url, accept="application/xml,text/xml;q=0.9,*/*;q=0.5")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{sitemap_url}: {exc}")
            continue

        locs = sitemap_locs(text)
        is_index = bool(re.search(r"<sitemapindex\b", text, flags=re.I))
        for loc in locs:
            absolute = normalise_url(urljoin(sitemap_url, loc))
            if not absolute:
                continue
            if is_product_url(absolute):
                product_urls.add(absolute)
            elif is_index or ".xml" in urlparse(absolute).path.lower() or "sitemap" in absolute.lower():
                queue.append((absolute, depth + 1))

    return sorted(product_urls), sorted(visited), errors


def stock_signal(page: str, structured: dict[str, Any]) -> tuple[bool, str]:
    offers = structured.get("offers") if isinstance(structured, dict) else None
    if isinstance(offers, list) and offers:
        offers = offers[0]
    availability = str(offers.get("availability", "")) if isinstance(offers, dict) else ""
    text = f"{availability} {page}"
    if re.search(
        r"outofstock|sold out|out of stock|currently unavailable|nicht verfügbar|ausverkauft|rupture de stock|agotado|esaurito|niet beschikbaar",
        text,
        flags=re.I,
    ):
        return False, "Unavailable signal"
    if re.search(r"instock|in stock|add to cart|in den warenkorb|ajouter au panier|añadir al carrito", text, flags=re.I):
        return True, "In stock signal"
    return True, "Availability not stated"


def product_icon(name: str, category: str) -> str:
    text = f"{name} {category}".lower()
    for terms, icon in (
        (("ski", "snowboard"), "⛷️"),
        (("football", "soccer"), "⚽"),
        (("bike", "cycling", "helmet", "velo"), "🚴"),
        (("camp", "sleeping", "hiking", "backpack", "trek"), "🎒"),
        (("fitness", "yoga", "training", "mat"), "🧘"),
        (("swim", "surf", "diving"), "🏊"),
    ):
        if any(term in text for term in terms):
            return icon
    return "🟢"


def parse_product(page: str, url: str, store: dict[str, str], requested_id: str = "") -> dict[str, Any] | None:
    structured = find_jsonld_product(page)
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", page, flags=re.I | re.S)
    title = strip_tags(title_match.group(1)) if title_match else ""
    name = str(structured.get("name") or title).strip()
    category = str(structured.get("category") or "Decathlon product").strip()
    price = find_price(page, structured)
    code = extract_model_id(page + " " + url, requested_id)
    currency = infer_currency(page, store, structured)
    if not name or price is None or not code:
        return None

    aggregate = structured.get("aggregateRating") if isinstance(structured, dict) else None
    rating = aggregate.get("ratingValue") if isinstance(aggregate, dict) else "—"
    image = structured.get("image") if isinstance(structured, dict) else ""
    if isinstance(image, list):
        image = image[0] if image else ""
    stock, stock_status = stock_signal(page, structured)
    return {
        "id": code,
        "name": html_lib.unescape(name),
        "category": category,
        "sport": category if category and category != "Decathlon product" else "Discovered",
        "icon": product_icon(name, category),
        "rating": str(rating or "—"),
        "image": str(image or ""),
        "price": price,
        "currency": currency,
        "local": format_local(price, currency),
        "stock": stock,
        "stock_status": stock_status,
        "url": url,
    }


def format_local(price: float, currency: str) -> str:
    currency = currency.upper()
    decimals = 0 if currency in {"CLP", "COP", "CZK", "HUF", "IDR", "JPY", "KRW", "VND"} else 2
    rendered = f"{price:,.{decimals}f}"
    if decimals:
        rendered = rendered.replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        rendered = rendered.replace(",", ".")
    symbol = currency_symbol(currency)
    return f"{symbol}{rendered}" if currency in {"EUR", "GBP", "USD", "CHF", "PLN", "CZK", "JPY"} else f"{rendered} {symbol}"


def to_eur(price: float, currency: str, rates: dict[str, float]) -> float | None:
    rate = rates.get(currency.upper())
    return round(price / rate, 2) if rate else None


def load_fx_rates() -> tuple[dict[str, float], str]:
    try:
        payload = json.loads(fetch_text("https://api.frankfurter.app/latest?from=EUR", accept="application/json"))
        rates = {"EUR": 1.0}
        rates.update({str(key).upper(): float(value) for key, value in payload.get("rates", {}).items()})
        return rates, "Frankfurter/ECB rates"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
        return dict(FALLBACK_RATES_FROM_EUR), "fallback rates"


def infer_store_from_host(host: str) -> dict[str, str] | None:
    host = host.lower().split(":", 1)[0].rstrip(".")
    if host in STORE_BY_HOST:
        return dict(STORE_BY_HOST[host])
    for known_host, store in STORE_BY_HOST.items():
        if host == known_host.removeprefix("www."):
            return dict(store)
    return None


def store_from_url(raw_url: str) -> dict[str, str] | None:
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if "decathlon" not in host or host.endswith("decathlon-united.media") or "decathlon-united" in host:
        return None
    known = infer_store_from_host(host)
    if known:
        known["website"] = f"https://{host}"
        known["domain"] = host
        return known

    # A new official host can still be useful before its metadata is added.
    parts = host.split(".")
    code = parts[-1] if parts[-1] not in {"com", "net", "org"} else "global"
    if code == "uk":
        code = "gb"
    return _store(code, code.upper(), host, "EUR")


def discover_stores(official_page: str = OFFICIAL_STORES_PAGE) -> tuple[list[dict[str, str]], str]:
    stores: dict[str, dict[str, str]] = {store["domain"]: dict(store) for store in DEFAULT_STORES}
    discovery_source = "fallback official store catalogue"
    try:
        page = fetch_text(official_page)
        links = re.findall(r"(?:href|data-href)=[\"']([^\"']+)[\"']", page, flags=re.I)
        links.extend(re.findall(r"https?://[^\s\"'<>]+", page, flags=re.I))
        discovered = [store_from_url(link.rstrip(".,);")) for link in links]
        for store in discovered:
            if store:
                stores[store["domain"]] = store
        discovery_source = official_page
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        print(f"official store page unavailable; using fallback list: {exc}", file=sys.stderr)

    return sorted(stores.values(), key=lambda item: (item["code"], item["name"])), discovery_source


def crawl_store(store: dict[str, str], workers: int, max_products: int = 0, progress: "Progress | None" = None) -> dict[str, Any]:
    started_at = now_iso()
    product_urls, sitemap_urls, sitemap_errors = collect_product_urls(store["website"])
    if max_products > 0:
        product_urls = product_urls[:max_products]
    if progress:
        progress.store_started(store["code"], len(product_urls))

    products: dict[str, dict[str, Any]] = {}
    errors = list(sitemap_errors)

    def fetch_candidate(url: str) -> dict[str, Any] | None:
        requested_id = extract_model_id(url)
        try:
            page = fetch_text(url)
            return parse_product(page, url, store, requested_id)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"{url}: {exc}") from exc

    if product_urls:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch_candidate, url): url for url in product_urls}
            for future in as_completed(futures):
                if progress:
                    progress.product_done(store["code"])
                try:
                    parsed = future.result()
                    if parsed and parsed["id"]:
                        products[parsed["id"]] = parsed
                except Exception as exc:  # noqa: BLE001 - persisted as per-store scan evidence
                    errors.append(str(exc))

    # A sitemap that was fetched cleanly is the minimum evidence that an empty
    # result is real. If the sitemap itself failed, preserve the distinction.
    scan_complete = bool(sitemap_urls) and not sitemap_errors
    return {
        "store": store,
        "started_at": started_at,
        "finished_at": now_iso(),
        "sitemap_urls": sitemap_urls,
        "product_url_count": len(product_urls),
        "products": products,
        "errors": errors[:25],
        "scan_complete": scan_complete,
    }


class Progress:
    """Thread-safe progress reporting for parallel store crawls.

    On a terminal it redraws one status line; otherwise (e.g. CI logs) it
    prints one line per finished store.
    """

    def __init__(self, total_stores: int, stream: Any = None) -> None:
        self.total_stores = total_stores
        self.stream = stream or sys.stderr
        self.interactive = self.stream.isatty()
        self.finished_stores = 0
        self.active: dict[str, list[int]] = {}
        self.lock = Lock()

    def store_started(self, code: str, product_total: int) -> None:
        with self.lock:
            self.active[code] = [0, product_total]
            self._render()

    def product_done(self, code: str) -> None:
        with self.lock:
            self.active[code][0] += 1
            self._render()

    def store_finished(self, code: str, product_count: int, complete: bool) -> None:
        with self.lock:
            self.active.pop(code, None)
            self.finished_stores += 1
            self._clear()
            status = "complete" if complete else "partial"
            print(f"[{self.finished_stores}/{self.total_stores}] {code}: {product_count} products · {status}", file=self.stream, flush=True)
            self._render()

    def _line(self) -> str:
        active = " ".join(f"{code} {done}/{total}" for code, (done, total) in sorted(self.active.items()))
        return f"stores {self.finished_stores}/{self.total_stores} | {active}"

    def _render(self) -> None:
        if self.interactive:
            width = shutil.get_terminal_size().columns - 1
            print(f"\r{self._line()[:width]:<{width}}", end="", file=self.stream, flush=True)

    def _clear(self) -> None:
        if self.interactive:
            width = shutil.get_terminal_size().columns - 1
            print(f"\r{' ' * width}\r", end="", file=self.stream)


def crawl_stores(stores: list[dict[str, str]], workers: int, max_products: int, store_jobs: int, progress: Progress) -> list[dict[str, Any]]:
    def run(store: dict[str, str]) -> dict[str, Any]:
        try:
            result = crawl_store(store, workers, max_products, progress)
        except Exception as exc:  # noqa: BLE001 - keep one store failure from stopping the global run
            result = {"store": store, "sitemap_urls": [], "product_url_count": 0, "products": {}, "errors": [str(exc)], "scan_complete": False, "finished_at": now_iso()}
        progress.store_finished(store["code"], len(result["products"]), result["scan_complete"])
        return result

    with ThreadPoolExecutor(max_workers=max(1, store_jobs)) as pool:
        return list(pool.map(run, stores))


def merge_partial_scan(previous: dict[str, Any], current: dict[str, Any], scanned_codes: set[str]) -> dict[str, Any]:
    """Overlay a scan of some countries onto the previous catalogue, keeping the other markets as they were."""
    stores = {str(store["code"]): store for store in previous.get("stores", [])}
    stores.update({store["code"]: store for store in current["stores"]})

    products = {product["id"]: product for product in current["products"]}
    for old in previous.get("products", []):
        kept = {market: offer for market, offer in (old.get("prices") or {}).items() if market not in scanned_codes}
        if not kept:
            continue
        product = products.setdefault(old["id"], {**old, "prices": {}})
        product["prices"] = {**kept, **product["prices"]}

    product_records = sorted(products.values(), key=lambda item: (item["name"].lower(), item["id"]))
    return {
        **current,
        "store_count": len(stores),
        "product_count": len(product_records),
        "stores": sorted(stores.values(), key=lambda item: item["code"]),
        "products": product_records,
    }


def compact_offer(item: dict[str, Any], observed_at: str) -> dict[str, Any]:
    return {
        "price": round(float(item["price"]), 2),
        "currency": item["currency"],
        "local": item["local"],
        "eur": item.get("eur"),
        "stock": bool(item["stock"]),
        "stock_status": item["stock_status"],
        "url": item["url"],
        "observed_at": observed_at,
    }


def build_catalog(stores: list[dict[str, str]], results: list[dict[str, Any]], rates: dict[str, float], rates_source: str, discovery_source: str, generated_at: str) -> dict[str, Any]:
    products: dict[str, dict[str, Any]] = {}
    store_records: list[dict[str, Any]] = []
    result_by_domain = {result["store"]["domain"]: result for result in results}

    for store in stores:
        result = result_by_domain.get(store["domain"], {"products": {}, "sitemap_urls": [], "product_url_count": 0, "errors": ["Store was not scanned"], "scan_complete": False})
        store_record = {
            **store,
            "status": "active" if result["scan_complete"] else "partial",
            "scan_complete": result["scan_complete"],
            "sitemap_count": len(result["sitemap_urls"]),
            "product_url_count": result["product_url_count"],
            "product_count": len(result["products"]),
            "errors": result["errors"],
            "last_scan": result.get("finished_at", generated_at),
        }
        store_records.append(store_record)

        for product_id, item in result["products"].items():
            product = products.setdefault(
                product_id,
                {
                    "id": product_id,
                    "name": item["name"],
                    "sport": item["sport"],
                    "category": item["category"],
                    "icon": item["icon"],
                    "rating": item["rating"],
                    "sample": "Daily public country-shop snapshot",
                    "prices": {},
                },
            )
            # Prefer the first complete product record, but keep a non-empty
            # canonical name/category if a later localized page is sparse.
            if len(item["name"]) > len(product["name"]):
                product["name"] = item["name"]
            eur_value = to_eur(item["price"], item["currency"], rates)
            product["prices"][store["code"]] = compact_offer({**item, "eur": eur_value}, generated_at)

    product_records = sorted(products.values(), key=lambda item: (item["name"].lower(), item["id"]))
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "base_currency": "EUR",
        "rates_source": rates_source,
        "discovery_source": discovery_source,
        "store_count": len(store_records),
        "product_count": len(product_records),
        "stores": store_records,
        "products": product_records,
    }


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def previous_locations(catalog: dict[str, Any]) -> dict[str, set[str]]:
    locations: dict[str, set[str]] = {}
    for product in catalog.get("products", []):
        product_id = str(product.get("id", ""))
        locations[product_id] = set((product.get("prices") or {}).keys())
    return locations


def build_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_products = {str(item.get("id")): item for item in previous.get("products", [])}
    current_products = {str(item.get("id")): item for item in current.get("products", [])}
    previous_ids = set(previous_products)
    current_ids = set(current_products)
    complete_stores = {store["code"] for store in current.get("stores", []) if store.get("scan_complete")}
    old_locations = previous_locations(previous)

    # A global disappearance is only declared if every store that previously
    # carried the ID completed today's scan. A blocked market must not create a
    # false “vanished” product event.
    vanished = sorted(
        product_id
        for product_id in previous_ids - current_ids
        if old_locations.get(product_id) and old_locations[product_id].issubset(complete_stores)
    )

    old_stores = {str(store.get("code")): store for store in previous.get("stores", [])}
    new_store_codes = sorted({str(store.get("code")) for store in current.get("stores", [])} - set(old_stores))
    vanished_store_codes = sorted(set(old_stores) - {str(store.get("code")) for store in current.get("stores", [])})

    price_changes: list[dict[str, Any]] = []
    availability_changes: list[dict[str, Any]] = []
    store_product_vanished: list[dict[str, str]] = []
    for product_id in sorted(current_ids & previous_ids):
        old_prices = previous_products[product_id].get("prices") or {}
        new_prices = current_products[product_id].get("prices") or {}
        for market in sorted(set(old_prices) | set(new_prices)):
            old_offer = old_prices.get(market)
            new_offer = new_prices.get(market)
            if old_offer and new_offer:
                if (old_offer.get("price"), old_offer.get("currency"), old_offer.get("eur")) != (new_offer.get("price"), new_offer.get("currency"), new_offer.get("eur")):
                    price_changes.append({"product_id": product_id, "market": market, "previous": old_offer, "current": new_offer})
                if bool(old_offer.get("stock")) != bool(new_offer.get("stock")):
                    availability_changes.append({"product_id": product_id, "market": market, "previous": bool(old_offer.get("stock")), "current": bool(new_offer.get("stock"))})
            elif old_offer and market in complete_stores:
                store_product_vanished.append({"product_id": product_id, "market": market})
            elif new_offer and market in old_prices:
                availability_changes.append({"product_id": product_id, "market": market, "previous": False, "current": True})

    return {
        "schema_version": 1,
        "generated_at": current.get("generated_at"),
        "products": {
            "new": sorted(current_ids - previous_ids),
            "vanished": vanished,
            "still_present": sorted(current_ids & previous_ids),
        },
        "stores": {"new": new_store_codes, "vanished": vanished_store_codes},
        "price_changes": price_changes,
        "availability_changes": availability_changes,
        "store_product_vanished": store_product_vanished,
        "scan": {
            "complete_stores": sorted(complete_stores),
            "partial_stores": sorted({store["code"] for store in current.get("stores", []) if not store.get("scan_complete")}),
        },
    }


def history_path(history_dir: Path, product_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", product_id)
    return history_dir / f"{safe_id}.json"


def append_event(history: dict[str, Any], event: dict[str, Any]) -> None:
    events = history.setdefault("events", [])
    dedupe_types = {"product_discovered", "product_vanished", "product_reappeared"}
    if event.get("type") in dedupe_types and events and events[-1].get("type") == event.get("type") and events[-1].get("market") == event.get("market"):
        return
    events.append(event)
    history["events"] = events[-100:]


def update_histories(history_dir: Path, previous: dict[str, Any], current: dict[str, Any], delta: dict[str, Any]) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    previous_products = {str(item.get("id")): item for item in previous.get("products", [])}
    current_products = {str(item.get("id")): item for item in current.get("products", [])}
    generated_at = str(current.get("generated_at"))
    complete_stores = set(delta.get("scan", {}).get("complete_stores", []))

    for product_id, product in current_products.items():
        path = history_path(history_dir, product_id)
        history = read_json(path, {"product_id": product_id, "events": [], "snapshots": []})
        old_product = previous_products.get(product_id)
        if not old_product:
            append_event(history, {"at": generated_at, "type": "product_discovered"})
        elif history.get("status") == "vanished":
            append_event(history, {"at": generated_at, "type": "product_reappeared"})

        old_prices = (old_product or {}).get("prices") or {}
        for market, offer in (product.get("prices") or {}).items():
            old_offer = old_prices.get(market)
            if old_offer and (old_offer.get("price"), old_offer.get("currency")) != (offer.get("price"), offer.get("currency")):
                append_event(history, {"at": generated_at, "type": "price_changed", "market": market, "previous": old_offer.get("price"), "current": offer.get("price"), "currency": offer.get("currency")})
            if old_offer and bool(old_offer.get("stock")) != bool(offer.get("stock")):
                append_event(history, {"at": generated_at, "type": "availability_changed", "market": market, "previous": bool(old_offer.get("stock")), "current": bool(offer.get("stock"))})
            if not old_offer:
                append_event(history, {"at": generated_at, "type": "market_added", "market": market})
        for market in set(old_prices) - set(product.get("prices") or {}):
            if market in complete_stores:
                append_event(history, {"at": generated_at, "type": "market_removed", "market": market})

        snapshots = history.setdefault("snapshots", [])
        snapshots.append(
            {
                "at": generated_at,
                "name": product.get("name"),
                "prices": {
                    market: {key: offer.get(key) for key in ("price", "currency", "eur", "stock")}
                    for market, offer in (product.get("prices") or {}).items()
                },
            }
        )
        history.update({"product_id": product_id, "name": product.get("name"), "status": "active", "last_seen": generated_at, "last_checked": generated_at})
        history["first_seen"] = history.get("first_seen") or generated_at
        history["snapshots"] = snapshots[-730:]
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for product_id in delta.get("products", {}).get("vanished", []):
        path = history_path(history_dir, product_id)
        history = read_json(path, {"product_id": product_id, "events": [], "snapshots": []})
        append_event(history, {"at": generated_at, "type": "product_vanished"})
        history.update({"product_id": product_id, "status": "vanished", "last_checked": generated_at})
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stores = {store["code"]: store for store in catalog.get("stores", [])}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["product_id", "name", "market", "market_name", "price", "currency", "eur", "stock", "stock_status", "url", "generated_at"],
        )
        writer.writeheader()
        for product in catalog.get("products", []):
            for market, offer in (product.get("prices") or {}).items():
                writer.writerow(
                    {
                        "product_id": product.get("id"),
                        "name": product.get("name"),
                        "market": market,
                        "market_name": stores.get(market, {}).get("name", market),
                        "price": offer.get("price"),
                        "currency": offer.get("currency"),
                        "eur": offer.get("eur"),
                        "stock": offer.get("stock"),
                        "stock_status": offer.get("stock_status"),
                        "url": offer.get("url"),
                        "generated_at": catalog.get("generated_at"),
                    }
                )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/catalog.json")
    parser.add_argument("--csv", dest="csv_output", type=Path, default=ROOT / "data/catalog.csv")
    parser.add_argument("--stores-output", type=Path, default=ROOT / "data/stores.json")
    parser.add_argument("--delta-output", type=Path, default=ROOT / "data/delta.json")
    parser.add_argument("--history-dir", type=Path, default=ROOT / "data/history")
    parser.add_argument("--official-page", default=OFFICIAL_STORES_PAGE)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("DECASCOUT_WORKERS", "8")))
    parser.add_argument("--country", "-c", action="append", default=[], metavar="CODE", help="Only scan these country codes (repeatable or comma-separated, e.g. -c de,fr); other markets keep their previous data.")
    parser.add_argument("--store-jobs", type=int, default=int(os.environ.get("DECASCOUT_STORE_JOBS", "4")), help="Number of countries scanned in parallel; --workers applies per country.")
    parser.add_argument("--max-products-per-store", type=int, default=0, help="Fixture/smoke-test limit; zero means all discovered product URLs.")
    parser.add_argument("--allow-empty", action="store_true", help="Permit replacing the current catalogue with an empty scan.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    generated_at = now_iso()
    stores, discovery_source = discover_stores(args.official_page)
    print(f"Discovered {len(stores)} official Decathlon country shops.")

    scanned_codes: set[str] = set()
    if args.country:
        scanned_codes = {code.strip().lower() for value in args.country for code in value.split(",") if code.strip()}
        unknown = scanned_codes - {store["code"] for store in stores}
        if unknown:
            print(f"Unknown country code(s): {', '.join(sorted(unknown))}; available: {', '.join(store['code'] for store in stores)}", file=sys.stderr)
            return 2
        scan_stores = [store for store in stores if store["code"] in scanned_codes]
    else:
        scan_stores = stores

    progress = Progress(len(scan_stores))
    results = crawl_stores(scan_stores, max(1, args.workers), max(0, args.max_products_per_store), args.store_jobs, progress)

    rates, rates_source = load_fx_rates()
    previous = read_json(args.output, {})
    catalog = build_catalog(scan_stores, results, rates, rates_source, discovery_source, generated_at)
    if scanned_codes:
        catalog = merge_partial_scan(previous, catalog, scanned_codes)
    if not catalog["products"] and previous.get("products") and not args.allow_empty:
        print("Refusing to overwrite a non-empty catalogue with an empty scan; use --allow-empty to override.", file=sys.stderr)
        return 2

    delta = build_delta(previous, catalog)
    update_histories(args.history_dir, previous, catalog, delta)
    write_json(args.output, catalog)
    write_csv(args.csv_output, catalog)
    write_json(args.stores_output, {"generated_at": generated_at, "discovery_source": discovery_source, "stores": catalog["stores"]})
    write_json(args.delta_output, delta)
    print(f"Wrote {catalog['product_count']} products across {catalog['store_count']} stores.")
    print(f"New IDs: {len(delta['products']['new'])}; vanished IDs: {len(delta['products']['vanished'])}; price changes: {len(delta['price_changes'])}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
