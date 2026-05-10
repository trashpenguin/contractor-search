# Contractor Finder v3.2

Professional desktop application for finding contractors (HVAC, Electrical, Excavating) across USA locations. Aggregates data from OpenStreetMap, YellowPages, Yelp, and Google Maps, then enriches results with phone numbers, emails, and websites via a fully async pipeline.

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

---

## About

**Contractor Finder** is a PySide6 desktop application that automates the full contractor discovery workflow:

1. **Discover** — Searches OSM, YellowPages, Yelp, and Google Maps simultaneously
2. **Enrich** — Finds and scrapes each contractor's website for phone numbers and emails
3. **Verify** — Validates emails via MX record checks and detects role accounts
4. **Export** — Save results as CSV, TXT, or import into Google Sheets

Built with Scrapling stealth browser automation, a rate-aware DDG pipeline, and a fully async enrichment system that processes up to 15 websites concurrently. All data is cached in SQLite to avoid redundant lookups.

---

## Features

- Multi-source scraping: OSM (Overpass + Nominatim), YellowPages, Yelp (3-phase), Google Maps (scroll + JS blob)
- Async enrichment pipeline — batches of 15 concurrent website scrapes
- Smart deduplication with data merging across sources
- SQLite caching — 7-day contacts TTL, 1-day DDG TTL (empty results cached too)
- Opt-in proxy rotation (proxifly + 5 other free lists) with health scoring and instant circuit-break on timeout
- Domain guessing engine — 9 common patterns, zero rate limits
- 4-strategy deep email hunt: JS file scan, sitemap crawl, WHOIS lookup, DDG snippet search
- Guessed emails tagged separately (gold "~" indicator) so they're distinguishable from scraped emails
- Cloudflare `data-cfemail` obfuscation decode
- Role account detection (`info@`, `contact@`, etc.)
- Email MX-based verification
- Lead-gen / aggregator domain blocklist (buildzoom, myhomequote, birdeye, houzz, etc.)
- Dark-themed desktop UI — live stats per trade, trade/source/name filters
- Filter resets automatically on each new search
- Search history (last 20 locations)
- Google Sheets export support

---

## Supported Sources

| Source | Method | Notes |
| --- | --- | --- |
| OpenStreetMap | Overpass API POST + Nominatim fallback | Broadest coverage for obscure businesses |
| YellowPages | StealthySession — multi-page with auto retry | Cloudflare 530 handled with 30s backoff |
| Yelp | 3-phase: curl_cffi → StealthySession → DDG fallback | Phase 3 harvests contractor websites directly from DDG results |
| Google Maps | StealthySession with `page_action` scroll (10×) | Geocoded lat/lon for city-level zoom; extracts from JS blob + feed cards + place URLs |
| DuckDuckGo | HTML endpoint — rate-limited, cached | Used for website discovery and email hunting; capped at 8 lookups per trade |

---

## Requirements

- Python 3.9+

```bash
pip install -r requirements.txt
```

### requirements.txt

```text
scrapling        # stealth browser automation
browserforge     # browser fingerprint generation
curl_cffi        # curl impersonation (TLS/JA3 fingerprint bypass)
playwright       # browser automation backend
patchright       # patched Playwright variant
PySide6          # Qt6 desktop UI framework
dnspython        # DNS/MX record resolution
msgspec          # fast JSON serialization
aiohttp          # async HTTP with connection pooling
python-whois     # WHOIS registrant email lookup (email deep-hunt strategy C)
```

---

## Installation

```bash
git clone https://github.com/yourusername/contractor-finder.git
cd contractor-finder
pip install -r requirements.txt
python -m playwright install chromium
python -m patchright install chromium
python contractor_gui.py
```

**Windows:** Double-click `launch_windows.bat` — handles pip install, browser setup, and launch automatically.

---

## Usage

### Basic Search

1. Enter a US city, state, or ZIP code (e.g. `Warren, MI 48091`)
2. Select trades: HVAC, Electrical, Excavating (any combination)
3. Select sources: OSM, YellowPages, Yelp, Google
4. Set search radius and per-source limit
5. Enable **Scrape websites** (recommended) for phone + email enrichment
6. Optionally enable **Use Proxy** to rotate free proxies (helps if your IP is rate-limited)
7. Click **Search Contractors ↗**

Results appear live in the table. All three trades run sequentially; the filter resets to "All" automatically so every trade is visible as results arrive.

### Post-Search Actions

| Button | Action |
| --- | --- |
| ✉ Verify Emails | MX record check on all discovered emails |
| 📊 Export → Google Sheets | Export CSV and open sheets.new |
| Export CSV | Save to file |
| Export TXT | Formatted report grouped by trade |
| Filter dropdowns | Filter by trade, source, or name (live, respects results mid-search) |

---

## Search Parameters

| Parameter | Default | Notes |
| --- | --- | --- |
| Location | Warren, MI 48091 | Any US city, state, or ZIP |
| Radius | 40 mi | OSM search radius |
| Per Trade/Source | 30 | 10 / 20 / 30 / 50 / 75 / 100 |
| Enrichment | On | Scrape websites for phone + email |
| Use Proxy | Off | Enable if getting rate-limited |

---

## Result Columns

| Column | Description |
| --- | --- |
| Trade | HVAC / Electrical / Excavating |
| Source | OSM / YellowPages / Yelp / Google |
| Company Name | Business name |
| Phone | Normalized `(XXX) XXX-XXXX` |
| Email | Scraped, or guessed (shown in gold with `~`) |
| Email Status | ✅ Valid / ❌ Invalid / ❓ Unknown / ~ Guessed |
| Website | Business website |
| Address | Street address if available |
| Note | Role account warning (`info@`, `contact@`, etc.) |

---

## Architecture

### Module Layout

```text
contractor-search/
├── contractor_gui.py        ← entry point (~50 lines)
├── models.py                ← Contractor dataclass
├── constants.py             ← regexes, TRADE_KW, colour maps, SKIP_DOMAINS, proxy sources
├── compat.py                ← optional-dep detection (scrapling / aiohttp / dnspython)
├── cache.py                 ← ContactCache (SQLite, 7d TTL) + SearchHistory
├── proxy.py                 ← ProxyManager — opt-in, 6 sources, health scoring, circuit-break
├── http_client.py           ← http_get, stealth_get, post_bytes, event loop
├── extractor.py             ← extract_contacts (8 strategies), verify_email, _clean_email
├── enricher.py              ← async/sync enrichment pipeline + dedup + 4 deep-hunt strategies
├── search.py                ← run_search orchestrator (per-trade DDG state)
├── workers.py               ← SearchWorker / VerifyWorker (QThread)
├── scrapers/
│   ├── ddg.py               ← DuckDuckGo HTML search, rate limiter, cache
│   ├── osm.py               ← Overpass API + Nominatim keyword fallback
│   ├── yellowpages.py       ← StealthySession, multi-page, 530 retry
│   ├── yelp.py              ← 3-phase: curl_cffi → StealthySession → DDG fallback
│   └── google.py            ← StealthySession, page_action scroll, APP_STATE + feed + place-links
└── gui/
    ├── style.py             ← STYLE CSS, COLS, VERIFY_COLORS/ICONS (guessed = gold)
    ├── widgets.py           ← StatCard
    └── main_window.py       ← MainWindow — filter-aware _add_row, double-start guard
```

**Dependency flow (no circular imports):**
`models → constants → compat → cache → proxy → http_client → extractor → scrapers/* → enricher → search → workers → gui/* → contractor_gui.py`

### Data Flow

```text
Search Location
      ↓
Geocode via Nominatim (lat/lon for city-level anchor)
      ↓
Per-Trade Sequential Scraping
 ├── OSM: Overpass API (nwr around radius) + Nominatim keyword search
 ├── YellowPages: StealthySession multi-page (auto-retry on Cloudflare 530)
 ├── Yelp: Phase 1 curl_cffi → Phase 2 StealthySession (__NEXT_DATA__ JSON)
 │         → Phase 3 DDG fallback (Strategy A: yelp.com/biz/ slugs,
 │                                  Strategy C: contractor websites from DDG titles)
 └── Google Maps: StealthySession + page_action scroll (10× feed panel)
                  → APP_INITIALIZATION_STATE JS blob (phones, websites, name candidates)
                  → div[role='feed'] aria-label cards
                  → a[href*='/maps/place/'] place-link URL names
      ↓
Smart Deduplication
 ├── Name fuzzy match (suffix stripping: LLC, Inc, HVAC, heating, etc.)
 ├── Phone 10-digit normalized match
 └── Root domain match — merges missing fields from duplicates
      ↓
Async Enrichment Pipeline (batches of 15, DDG capped at 8 per trade)
 ├── Step 1: Domain guessing — 9 patterns (no rate limits)
 ├── Step 2: DDG website lookup — only if no website AND no phone; max 8 per trade
 ├── Step 3: Website scrape — homepage + up to 6 contact/about subpages (SQLite cache)
 │   └── 8-strategy contact extraction (JSON-LD → mailto/tel → meta → itemprop →
 │         footer scan → Cloudflare decode → obfuscation → full-text regex)
 └── Step 4: Deep email hunt (runs only when Step 3 finds nothing)
       ├── A: JS file scan (up to 5 same-domain scripts)
       ├── B: Sitemap crawl → contact/about pages
       ├── C: WHOIS registrant email (python-whois)
       └── D: DDG snippet search for "@domain.com"
      ↓
Email tagged "guessed" if generated by MX-pattern (Step 4 fallback prefix@domain)
      ↓
Display & Export
```

### Scrapling Fetcher Types

| Fetcher | Used for |
| --- | --- |
| `Fetcher` / `http_get` (curl_cffi) | DDG search, contractor websites, Yelp Phase 1 |
| `StealthySession` | YellowPages, Yelp Phase 2, Google Maps — persistent browser context |
| `page_action` callback | Google Maps feed scroll (10× before HTML capture) |

### Proxy Manager

Opt-in (disabled by default — enable via "Use Proxy" checkbox):

- **6 sources** — proxifly high-quality, proxifly HTTP, monosans, clarketm, ShiftyTR, TheSpeedX
- **Health scoring** — starts at 5; instant score = -99 on timeout (immediate circuit-break, was 8 timeouts before)
- **Permanent ban** — TLS/CONNECT/certificate/403 errors
- **Sticky sessions** — up to 10 requests per proxy before rotation
- **Bypass** — OSM/Nominatim always use direct connection

### Email Extraction (8 Strategies)

| # | Strategy |
| --- | --- |
| 1 | JSON-LD / schema.org (highest reliability) |
| 2 | `mailto:` / `tel:` links |
| 3 | Meta tags (`name="email"`, `property="email"`) |
| 4 | Structured data attributes (`itemprop`, `data-email`) |
| 5 | Footer / contact section scan |
| 6 | Cloudflare `data-cfemail` XOR decode |
| 7 | Obfuscation patterns (`[at]`, `(at)`, `AT`, `@` with spaces) |
| 8 | Full-text regex fallback |

### Domain Blocklist

Lead-gen and aggregator sites are filtered from results and never scraped:

`yelp.com`, `yellowpages.com`, `bbb.org`, `buildzoom.com`, `threebestrated.com`, `todayshomeowner.com`, `birdeye.com`, `houzz.com`, `myhomequote.com`, `expertise.com`, `homeguide.com`, `porch.com`, `bark.com`, `improvenet.com`, `networx.com` + social/maps platforms

---

## Performance

| Search | Approx Time | Approx Results |
| --- | --- | --- |
| 1 trade, no enrichment | 1–2 min | ~90 |
| 1 trade, enrichment on | 2–3 min | ~90 |
| 3 trades, all sources, enrichment | 8–12 min | ~250–350 |

*Tested on Warren, MI 48091, 40 mi radius, all sources enabled.*

Google Maps now returns ~30 results per trade (up from ~12 before scroll was fixed).

---

## Cache Locations

```text
Windows:   C:\Users\[USERNAME]\.contractor_finder_cache.db
Linux/Mac: ~/.contractor_finder_cache.db
```

Search history:

```text
Windows:   C:\Users\[USERNAME]\.contractor_search_history.json
Linux/Mac: ~/.contractor_search_history.json
```

---

## Troubleshooting

### Only HVAC shows in results

The filter auto-resets on each new search (fixed in latest version). If you changed the filter mid-search, switch it back to "All" — all trades are stored in memory and will reappear.

### No results from Yelp

Yelp search pages return 403. The 3-phase fallback handles this automatically — Phase 3 (DDG) finds contractor websites directly. Results are cached for 24 hours per trade.

### YellowPages shows 530

Normal Cloudflare challenge. The scraper auto-retries with a 30-second backoff; the log will show `[YP] Attempt N got 0 results, retrying...`.

### Search takes too long / DDG rate limiting

DDG lookups are capped at 8 per trade and empty results are cached, so repeated searches for the same location are much faster. If still slow, reduce Per Trade/Source limit or disable enrichment for the first run.

### Missing browser engines

```bash
python -m playwright install chromium
python -m patchright install chromium
```

### Proxy pool empty

Expected — proxy is opt-in and off by default. Enable "Use Proxy" only if your IP is being rate-limited by a specific source.

---

## Modifying Trade Keywords

Edit `TRADE_KW` in `constants.py`:

```python
TRADE_KW = {
    "HVAC": {
        "osm":    ["heating", "hvac", "furnace", "cooling", "air conditioning"],
        "yp":     "hvac+heating+cooling+contractor",
        "google": "HVAC contractor",
        "yelp":   "hvac",
    },
    ...
}
```

Each trade has separate keyword sets per source.

---

## Release Notes

### v3.2 — Current

#### Scraper improvements

- Google Maps: URL now uses geocoded lat/lon at zoom-12 (was defaulting to Pacific Ocean zoom-3); `page_action` scroll triggers lazy-loading of 30+ results (was ~12)
- Google Maps: 3-layer extraction — APP_INITIALIZATION_STATE JS blob, `div[role='feed']` aria-label cards, `a[href*='/maps/place/']` place-link URLs
- Yelp: full 3-phase system — curl_cffi (`__NEXT_DATA__` JSON) → StealthySession → DDG fallback with Strategy A (yelp.com/biz/ slugs) and Strategy C (contractor websites harvested directly from DDG results)
- YellowPages: auto-retry on Cloudflare 530 with 30s backoff

#### Enrichment improvements

- 4-strategy deep email hunt added: JS file scan, sitemap crawl, WHOIS registrant lookup, DDG snippet search
- Guessed emails (MX-pattern prefix@domain) tagged `email_status="guessed"` and displayed in gold with `~` icon
- DDG website lookup now capped at 8 per trade total (shared across all 15-contractor batches) — prevents 30+ DDG calls per trade that blocked Electrical and Excavating from running
- Empty DDG results cached so the same no-result query isn't retried on the next run
- JS file scanner capped at 5 same-domain scripts per site (was downloading 13+ on WordPress sites)
- `_clean_email()` now URL-decodes before stripping (fixes `%20%20foo@bar.com` entries from cache)
- Async DDG enrichment uses full location string instead of hardcoded "Michigan"
- `scrape_website()` sync fallback now uses the same `SCRAPE_SKIP` set as the async path

#### Proxy

- Proxy is now opt-in (off by default) — "Use Proxy" checkbox in UI
- Timeout now sets score = -99 (immediate circuit-break); was -2 per timeout requiring 8 hits to remove
- 6 proxy sources: proxifly (quality + HTTP), monosans, clarketm, ShiftyTR, TheSpeedX

#### Domain filtering

- 15+ lead-gen / aggregator domains added to `SKIP_DOMAINS` and `SCRAPE_SKIP`: buildzoom, threebestrated, todayshomeowner, birdeye, houzz, cozywise, expertise, myhomequote, improvenet, networx, porch, bark, homeguide, fixr

#### GUI fixes

- Filter (trade/source/name) resets to "All" automatically on every new search
- `_add_row` now respects the active filter — rows from non-matching trades go to `self.rows` but stay hidden until the filter is broadened
- Double-start guard — pressing Enter in the location box while a search is running no longer clears results and restarts

#### Dependencies

- `python-whois` added to `requirements.txt` and `launch_windows.bat`

#### Codebase

- Refactored from 2,271-line monolith into 18 focused modules (`scrapers/`, `gui/`, core modules)

### v3.1

- Async enrichment pipeline (batches of 15)
- StealthySession for YP, Yelp, Google Maps
- Elite proxy pool with health scoring + circuit breakers + sticky sessions
- Cloudflare `data-cfemail` decode
- Role account detection
- Search history (last 20 locations)
- SQLite cache with 7-day / 1-day TTL
- 8-strategy contact extraction
- Domain guessing engine
- Email MX verification (SMTP removed — unreliable in 2026)
- Nominatim fallback for OSM
- Smart dedup with name/phone/domain merging

### v2.x

- Google Maps integration, email MX verification, proxy rotation, website enrichment

### v1.x

- Basic OSM + YellowPages scraping, CSV/TXT export

---

## Legal & Ethical Use

This tool is intended for legitimate business research only. Respect website rate limits, comply with Terms of Service, and use responsibly.

---

## Acknowledgments

- [Scrapling](https://github.com/D4Vinci/Scrapling) — stealth browser automation
- [OpenStreetMap](https://www.openstreetmap.org/) — Overpass API & Nominatim
- [PySide6](https://doc.qt.io/qtforpython/) — Qt6 desktop UI
- [aiohttp](https://docs.aiohttp.org/) — async HTTP client
- [dnspython](https://www.dnspython.org/) — DNS/MX resolution
- [Playwright](https://playwright.dev/) & [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) — browser automation backends
- [browserforge](https://github.com/daijro/browserforge) — browser fingerprint generation

---

## Support

Open an issue on GitHub for bug reports or feature requests.
