# Contractor Finder v3

Professional desktop application for finding contractors (HVAC, Electrical, Excavating) across USA locations. The application aggregates data from multiple sources including OpenStreetMap, YellowPages, Yelp, and Google Maps, then enriches the results with phone numbers, emails, websites, and business details.

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

---

## 📖 About

<p align="center">
  <strong>Multi-source contractor discovery & enrichment tool for HVAC, Electrical, and Excavating businesses across the USA.</strong>
</p>

**Contractor Finder** is a PySide6 desktop application that solves the problem of finding qualified trade contractors in any US location. Instead of manually searching multiple directories and scraping websites for contact information, this tool automates the entire workflow:

1. **Discover** — Searches OpenStreetMap, YellowPages, Yelp, and Google Maps simultaneously
2. **Enrich** — Finds and scrapes each contractor's website for phone numbers and emails
3. **Verify** — Validates emails via MX record checks and detects role accounts
4. **Export** — Save results as CSV, TXT, or import into Google Sheets

Built with Scrapling's stealth browser automation, an elite proxy pool with health scoring, and a fully async enrichment pipeline that processes up to 15 websites concurrently. All data is cached in SQLite to avoid redundant lookups.

| | | |
|---|---|---|
| **Repository** | [github.com/trashpenguin/contractor-search](https://github.com/trashpenguin/contractor-search) | |
| **Topics** | `contractor-search` `hvac` `electrical` `excavating` `web-scraping` `data-enrichment` `pyside6` `scrapling` `async-pipeline` `proxy-rotation` | |

---

### Key Use Cases

- 🏢 **Sales teams** — Build targeted lists of HVAC, electrical, and excavating contractors
- 📊 **Market research** — Analyze contractor density and contactability by region
- 🔍 **Lead generation** — Discover companies without cold-calling directories
- 📋 **Competitive analysis** — Compare contractor presence across sources

---

## ✨ Features

- Multi-source contractor scraping (OSM, YellowPages, Yelp, Google Maps)
- Async enrichment pipeline (batches of 15 concurrent scrapes)
- Smart deduplication with data merging across sources
- SQLite caching with TTL-based expiry (7-day contacts, 1-day DDG)
- Elite proxy pool with health scoring, sticky sessions & circuit breakers
- Domain guessing engine (no rate limits, faster than DDG)
- Email extraction & MX-based validation
- Cloudflare email obfuscation decode
- Role account detection (info@, contact@, etc.)
- Website discovery with multi-page contact scraping
- Google Sheets export support (via CSV import)
- Dark-themed desktop UI with live stats & filtering
- Search history support (last 20 locations)
- Multi-trade searching with parallel enrichment
- Structured logging with rotating file handler

---

## 🔍 Supported Sources

| Source | Purpose | Method |
|---|---|---|
| OpenStreetMap (OSM) | Business discovery via Overpass API + Nominatim fallback | HTTP POST |
| YellowPages | Contractor listings via stealth browser | StealthySession |
| Yelp | Business reviews & contact discovery | StealthySession |
| Google Maps | Additional contractor discovery | StealthySession |
| DuckDuckGo | Website & email enrichment fallback | HTML endpoint (rate-limited) |

---

## 📋 Requirements

### Python

- Python 3.9 or higher

### Dependencies

Install required packages:

```bash
pip install -r requirements.txt
```

#### requirements.txt

```
scrapling         # Stealth browser automation & anti-bot handling
browserforge      # Browser fingerprint generation
curl_cffi         # Curl impersonation for Scrapling
playwright        # Browser automation backend
patchright        # Patched Playwright variant
PySide6           # Qt6 desktop UI framework
dnspython         # DNS/MX record resolution
msgspec           # Fast serialization
aiohttp           # Async HTTP with connection pooling
```

## 🚀 Installation

### Clone Repository

```bash
git clone https://github.com/yourusername/contractor-finder.git
cd contractor-finder
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Install Browser Backends

```bash
python -m playwright install chromium
python -m patchright install chromium
```

### Run Application

```bash
python contractor_gui.py
```

**Windows:** Double-click `launch_windows.bat` for auto-setup and launch.

## 📦 Build Executable

### Install PyInstaller

```bash
pip install pyinstaller
```

### Build Single Executable

```bash
pyinstaller --onefile --windowed --name "ContractorFinder" contractor_gui.py
```

Executable will be generated inside:

```
dist/
```

## 🎯 Usage Guide

### Basic Search

1. Enter a US city, state, or ZIP code
2. Select one or more trades (HVAC, Electrical, Excavating)
3. Select data sources (OSM, YellowPages, Yelp, Google Maps)
4. Configure search radius
5. Enable/disable website enrichment (recommended: enabled)
6. Click **Search Contractors ↗**

Results appear live in the table with real-time progress tracking.

### Post-Search Actions

- **✉ Verify Emails** — Validate all discovered emails via MX record check
- **📊 Export → Google Sheets** — Export to CSV and open Google Sheets
- **Export CSV** — Save results as CSV file
- **Export TXT** — Save formatted text report grouped by trade
- **Filter** — Filter results by trade, source, or company name

---

## ⚙️ Search Parameters

| Parameter | Description | Default |
|---|---|---|
| Location | US city/state or ZIP | Warren, MI |
| Radius | Search radius | 40 miles |
| Per Trade/Source | Max results per source | 30 |
| Enrichment | Scrape websites for phone+email | Enabled |

## 📊 Result Columns

| Column | Description |
|---|---|
| Trade | Contractor category (HVAC/Electrical/Excavating) |
| Source | Data source (OSM/YellowPages/Yelp/Google) |
| Company Name | Business name |
| Phone | Normalized (XXX) XXX-XXXX format |
| Email | Extracted or guessed email |
| Email Status | ✅ Valid / ❌ Invalid / ❓ Unknown |
| Website | Business website |
| Address | Business address |
| Note | Role account warning or additional info |

---

## 🏗️ Application Architecture

### Module Layout

The codebase is split into focused modules for easy maintenance:

```
contractor-search/
├── contractor_gui.py        ← entry point (~50 lines)
├── models.py                ← Contractor dataclass
├── constants.py             ← regexes, TRADE_KW, colour maps, proxy sources
├── compat.py                ← optional-dep detection (scrapling/aiohttp/dnspython)
├── cache.py                 ← ContactCache (SQLite) + SearchHistory
├── proxy.py                 ← ProxyManager elite pool
├── http_client.py           ← http_get, stealth_get, post_bytes, event loop
├── extractor.py             ← extract_contacts, verify_email, email helpers
├── enricher.py              ← async/sync enrichment pipeline + dedup
├── search.py                ← run_search orchestrator
├── workers.py               ← SearchWorker / VerifyWorker (QThread)
├── scrapers/
│   ├── ddg.py               ← DuckDuckGo search + rate limiter
│   ├── osm.py               ← OpenStreetMap / Overpass / Nominatim
│   ├── yellowpages.py       ← YellowPages StealthySession scraper
│   ├── yelp.py              ← Yelp StealthySession scraper
│   └── google.py            ← Google Maps StealthySession scraper
└── gui/
    ├── style.py             ← STYLE CSS, COLS, VERIFY_COLORS/ICONS
    ├── widgets.py           ← StatCard widget
    └── main_window.py       ← MainWindow (~420 lines)
```

**Dependency flow (no circular imports):**
`models` → `constants` → `compat` → `cache` → `proxy` → `http_client` → `extractor` → `scrapers/*` → `enricher` → `search` → `workers` → `gui/*` → `contractor_gui.py`

### Scrapling Strategy

The app uses three Scrapling fetcher types (per Scrapling docs v0.4+):

| Fetcher | Purpose |
|---|---|
| `FetcherSession` / `Fetcher` | Fast HTTP with browser fingerprint — DDG search, contractor websites |
| `StealthySession` | Persistent stealth browser (one browser, many pages) — YellowPages, Yelp, Google Maps |
| `StealthyFetcher` | Single-shot stealth fetch — fallback when session not available |

### Data Flow

```
Search Location
      ↓
Geocode via Nominatim (lat/lon)
      ↓
Parallel Multi-Source Scraping
 ├── OSM: Overpass API + Nominatim fallback
 ├── YellowPages: StealthySession (multi-page, Cloudflare bypass)
 ├── Yelp: StealthySession (biz_redir website extraction)
 └── Google Maps: StealthySession (role='feed' + scroll)
      ↓
Smart Deduplication
 ├── Name similarity (fuzzy + suffix stripping)
 ├── Phone number comparison (10-digit normalized)
 └── Domain comparison (root domain)
      ↓
Async Enrichment Pipeline (batches of 15)
 ├── Step 1: Domain guessing (common patterns, zero rate limiting)
 ├── Step 2: DDG fallback (if domain guess fails, rate-limited)
 ├── Step 3: Website scraping (homepage + up to 6 contact/about subpages)
 │   ├── JSON-LD schema.org parsing (most reliable)
 │   ├── mailto/tel link extraction
 │   ├── Meta tag scanning
 │   ├── Structured data attributes
 │   ├── Footer/contact section scan
 │   ├── Cloudflare email obfuscation decode
 │   └── Obfuscation pattern matching ([at], AT, (at))
 └── Step 4: Email guessing from MX-verified domain
      ↓
MX Record Verification (async, non-blocking)
      ↓
Display & Export
```

## 🔧 Core Components

### Scrapling Fetchers

- **FetcherSession** — Fast HTTP with browser fingerprint (DDG search, contractor websites)
- **StealthySession** — Persistent headless browser, multi-page (YP, Yelp, Google Maps — 1 browser, many pages)
- **StealthyFetcher** — Single-shot stealth fetch (fallback)

### Proxy Manager (Elite Pool)

Multi-source proxy aggregation (4 sources, 300 max raw candidates):

- **Health scoring** — Each proxy starts at score 5; drops on failure, removed at ≤ 0
- **Circuit breakers** — TLS/CONNECT/certificate/403 errors = immediate permanent ban
- **Sticky sessions** — Each proxy handles up to 10 requests before rotating
- **Cooldown** — Timeout errors trigger 60s cooldown instead of immediate removal
- **Traffic routing** — OSM/Nominatim bypass proxy entirely; company websites use direct connection
- **Concurrent testing** — 30-thread HTTPS/HTTP validation pool

### Async Enrichment

Parallel enrichment pipeline with semaphore-based domain concurrency control:

- **Domain guessing** — Zero rate limiting, 9 common patterns (clean.com, cleanhvac.com, etc.)
- **DDG search** — HTML endpoint, rate-limited to 12 requests/min, 24h cache
- **Website scraping** — Shared `aiohttp.ClientSession`, up to 6 subpages per site
- **Email guessing** — 7 common prefixes (info, contact, service, office, admin, support, hello) with MX pre-check
- **Cache** — SQLite with 7-day TTL on contacts, 1-day TTL on DDG results

### Contact Extraction (8 Strategies)

| # | Strategy | Priority |
|---|---|---|
| 1 | JSON-LD / schema.org | Highest (most reliable) |
| 2 | Scrapling CSS: mailto/tel links | High |
| 3 | Meta tags (email/phone) | Medium |
| 4 | Structured data attributes (itemprop) | Medium |
| 5 | Footer/contact section regex scan | Medium |
| 6 | Cloudflare data-cfemail decode | Medium |
| 7 | Obfuscation patterns ([at], AT, (at), @) | Low |
| 8 | Full text regex fallback | Lowest |

### SQLite Cache

Persistent caching system with:

- **contacts** table — Keyed by domain, stores email/phone/website, 7-day TTL
- **ddg_cache** table — Keyed by MD5 query hash, stores JSON results, 1-day TTL
- **Cleanup** — Automatic purge of expired entries
- **Thread-safe** — Threading.Lock on all operations

### Smart Deduplication

Merges duplicate contractor records across sources:

- **Name comparison** — Fuzzy matching with suffix stripping (LLC, Inc, Co, services, etc.)
- **Phone comparison** — 10-digit normalized phone matching
- **Domain comparison** — Root domain comparison
- **Data merging** — Keeps the best record, fills in missing fields from duplicates
- **Sorting** — Records with most data (phone+email+website) are kept as canonical

### Email Verification

| Check | Description |
|---|---|
| Syntax | RFC-compliant regex validation |
| Filter | Rejects spam/CDN/tracking patterns (70+ blacklisted patterns) |
| MX record | DNS MX lookup — domain accepts email |
| Fallback A record | If no MX but A record exists → "unknown" |

**Note:** SMTP RCPT TO has been removed (unreliable in 2026 due to tarpitting, greylisting, catch-all mailboxes).

---

## 💾 Cache Locations

**Windows**

```
C:\Users\[USERNAME]\.contractor_finder_cache.db
```

**Linux/macOS**

```
~/.contractor_finder_cache.db
```

## ⚙️ Configuration

### Optional Environment Variables

**Linux/macOS**

```bash
export AIOHTTP_TIMEOUT=15
export NO_PROXY=1
```

**Windows PowerShell**

```powershell
$env:AIOHTTP_TIMEOUT=15
$env:NO_PROXY=1
```

## 🔨 Modifying Trade Keywords

Edit the `TRADE_KW` dictionary in `constants.py`:

```python
TRADE_KW = {
    "HVAC": {
        "osm": ["heating", "hvac", "furnace", "cooling", "air conditioning"],
        "yp": "hvac+heating+cooling+contractor",
        "google": "HVAC contractor",
        "yelp": "hvac"
    }
}
```

Each trade has separate keyword sets per source (OSM, YellowPages, Google, Yelp).

## 📈 Performance Benchmarks

| Search Type | Time | Approx Results |
|---|---|---|
| 1 trade, no enrichment | 45–60 sec | ~90 |
| 3 trades, enrichment | 3–5 min | ~180 |
| 3 trades, all sources | 6–8 min | ~300 |

**Tested On:** Warren, MI with 40 mile radius, all sources enabled.

## 🔍 Logging

Logs are stored at:

**Windows**

```
~\.contractor_finder.log
```

**Linux/macOS**

```
~/.contractor_finder.log
```

Log features:
- **RotatingFileHandler** — 5MB max, 3 backup files
- **Structured format** — `YYYY-MM-DD HH:MM:SS [LEVEL] message`
- **Console output** — INFO level and above (timestamps only)
- **File output** — DEBUG level and above (full detail)

### View Logs

**Linux/macOS**

```bash
tail -f ~/.contractor_finder.log
```

**Windows PowerShell**

```powershell
Get-Content ~\.contractor_finder.log -Wait
```

## 🛠️ Troubleshooting

### Scrapling unavailable

Update Scrapling:

```bash
pip install scrapling --upgrade
```

### Missing browser engines

Install Playwright and Patchright browsers:

```bash
python -m playwright install chromium
python -m patchright install chromium
```

### No results from YellowPages or Yelp

**Possible causes:**
- temporary blocking by Cloudflare
- rate limiting
- proxy failures

**Solutions:**
- retry after 60 seconds (YP auto-retries 3x on Cloudflare)
- check logs for `[YP] Cloudflare` or `[Yelp] Empty/blocked`
- reduce concurrency / wait between searches

### Search takes too long

**Suggestions:**
- reduce search radius
- lower per-source limits
- disable enrichment

### DuckDuckGo rate limiting

The app includes:
- built-in DDG limiter (12 requests/min, 1.5s minimum gap)
- automatic 20s backoff on 202 responses
- 24-hour cache to avoid redundant queries

Check logs for:

```
[DDG] Rate limit pause
[DDG] Rate-limited (short response)
```

### Proxy pool empty

Check logs for:
```
[Proxy] No working proxies — direct connection only
```

If no proxies are available, the app falls back to direct connections (some sources may block).

## 🛡️ Legal & Ethical Use

This tool is intended for legitimate business research only.

Please:
- respect website rate limits
- avoid excessive scraping
- comply with Terms of Service
- use responsibly

## 🤝 Contributing

1. **Fork Repository**

   ```bash
   git clone https://github.com/yourusername/contractor-finder.git
   ```

2. **Create Branch**

   ```bash
   git checkout -b feature/AmazingFeature
   ```

3. **Commit Changes**

   ```bash
   git commit -m "Add AmazingFeature"
   ```

4. **Push Changes**

   ```bash
   git push origin feature/AmazingFeature
   ```

5. **Open Pull Request**

   Submit your PR through GitHub.

## 🧪 Development Setup

### Install Development Dependencies

```bash
pip install black pylint pytest
```

### Run Tests

```bash
pytest tests/
```

### Format Code

```bash
black contractor_gui.py models.py constants.py compat.py cache.py proxy.py \
      http_client.py extractor.py enricher.py search.py workers.py \
      scrapers/ gui/
```

## 📝 Release Notes

### v3.2 — Current

- Codebase split from single 2 271-line file into 18 focused modules
- New `scrapers/` package (ddg, osm, yellowpages, yelp, google)
- New `gui/` package (style, widgets, main_window)
- `constants.py` — single source of truth for all regexes and lookup dicts
- `compat.py` — centralised optional-dependency detection
- `contractor_gui.py` reduced to ~50-line entry point
- Logging configured in entry point before any module import (fixes early-import ordering bug)
- No behaviour changes — identical feature set to v3.1

### v3.1

- Async enrichment pipeline (batches of 15 concurrent scrapes)
- StealthySession persistent browser for YP, Yelp, Google Maps
- Elite proxy pool with health scoring + circuit breakers + sticky sessions
- Traffic-aware proxy routing (OSM bypass, company sites direct)
- Cloudflare email obfuscation decode (data-cfemail)
- Role account detection (info@, contact@, service@)
- Search history support (last 20 locations)
- Persistent async event loop (no Windows loop issues)
- Structured logging with rotating file handler
- SQLite caching with 7-day / 1-day TTL
- Multi-strategy contact extraction (8 strategies)
- Domain guessing engine (no rate limits)
- Email MX verification (SMTP removed)
- Nominatim fallback for OSM business discovery
- 70+ blacklisted email patterns (spam/CDN/tracking)
- Smart dedup with name/phone/domain merging
- Smart obfuscation pattern matching ([at], AT, (at))

### v2.x

- Google Maps integration
- Email MX verification
- Proxy rotation
- Website enrichment

### v1.x

- Basic OSM + YellowPages scraping
- CSV/TXT export

## 📄 License

MIT License

See the LICENSE file for more details.

## 🙏 Acknowledgments

- Scrapling — stealth browser automation
- OpenStreetMap — Overpass API & Nominatim
- PySide6 — Qt desktop UI framework
- aiohttp — async HTTP client
- dnspython — DNS/MX resolution
- Playwright & Patchright — browser automation backends
- browserforge — browser fingerprint generation

## 📧 Support

For bug reports, feature requests, or improvements:

Open an issue on GitHub.