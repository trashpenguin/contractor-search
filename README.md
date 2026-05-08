# Contractor Finder v3

A professional desktop application for finding contractors (HVAC, Electrical, Excavating) across USA locations. Scrapes data from OSM, YellowPages, Yelp, and Google Maps, then enriches results with phone numbers, emails, and websites.

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

## ✨ Features

- **Multi-Source Scraping**: OSM, YellowPages, Yelp, Google Maps
- **Smart Enrichment**: Automatically finds websites, extracts phone/email
- **Email Verification**: MX record & syntax validation with role account detection
- **Smart Caching**: SQLite cache (7 days for contacts, 24h for search results)
- **Proxy Pool**: Automatic proxy rotation with health scoring
- **Async Performance**: 15x parallel enrichment for faster results
- **Export Options**: CSV, TXT, direct Google Sheets integration
- **Search History**: Remembers last 20 locations
- **Dark Theme UI**: Professional dark interface with trade colors

## 📋 Prerequisites

### Required
- Python 3.9 or higher
- pip package manager

### Python Dependencies

```bash
pip install PySide6 scrapling aiohttp dnspython
🚀 Installation
From Source
bash
# Clone the repository
git clone https://github.com/yourusername/contractor-finder.git
cd contractor-finder

# Install dependencies
pip install -r requirements.txt

# Run the application
python contractor_gui.py
Building Executable (Optional)
bash
# Install PyInstaller
pip install pyinstaller

# Create single executable
pyinstaller --onefile --windowed --name "ContractorFinder" contractor_gui.py
🎯 Usage Guide
Basic Search
Enter Location: City, State (e.g., "Warren, MI") or ZIP code

Select Trades: HVAC, Electrical, and/or Excavating

Choose Sources: OSM, YellowPages, Yelp, Google Maps

Set Radius: 10-80 miles

Click Search: Results appear in table below

Search Parameters
Parameter	Description	Default
Location	US city, state, or ZIP	Warren, MI
Radius	Search radius in miles	40 mi
Per Trade/Source	Max results per source/trade	30
Enrichment	Scrape websites for contact info	✓ Enabled
Understanding Results
Column	Description
Trade	Contractor type (color-coded)
Source	Where data was found
Company Name	Business name
Phone	Normalized phone number
Email	Extracted or guessed email
Email Status	✅ Valid / ❌ Invalid / ❓ Unknown / ⚠️ Role account
Website	Company website URL
Address	Physical address
Note	Role account warnings
Post-Search Actions
Verify Emails: MX record validation for all emails

Export CSV: Save as spreadsheet

Export TXT: Formatted text report

Google Sheets: Auto-upload to Google Sheets

Filter: By trade, source, or name search

🏗️ Architecture
Data Flow
text
Search Location → Geocode (Nominatim)
       ↓
Multi-Source Scraping (Parallel)
  ├── OSM (Overpass API)
  ├── YellowPages (StealthySession)
  ├── Yelp (StealthySession)
  └── Google Maps (StealthySession)
       ↓
Deduplication (Name/Phone/Domain)
       ↓
Enrichment (Async, 15x parallel)
  ├── Domain Guessing
  ├── DDG Fallback
  └── Website Scraping
       ↓
Email Verification (MX + syntax)
       ↓
Display & Export
Key Components
Scrapling: Browser fingerprinting & stealth browsing

aiohttp: Async HTTP with connection pooling

SQLite: Persistent cache (contacts, DDG results)

Proxy Manager: Auto-testing, health scoring, sticky sessions

StealthySession: Single browser for multi-page scraping

Cache Locations
Windows: C:\Users\[User]\.contractor_finder_cache.db

macOS/Linux: ~/.contractor_finder_cache.db

⚙️ Configuration
Environment Variables (Optional)
bash
# Increase timeout for slow connections
export AIOHTTP_TIMEOUT=15

# Disable proxy pool (direct connections only)
export NO_PROXY=1
Modifying Search Parameters
Edit TRADE_KW dictionary in code to add/modify search keywords:

python
TRADE_KW = {
    "HVAC": {
        "osm": ["heating","hvac","furnace"],
        "yp": "hvac+contractor",
        "google": "HVAC contractor",
        "yelp": "hvac"
    }
}
🔧 Troubleshooting
Common Issues
Q: "Scrapling unavailable" warning

A: Run pip install scrapling --upgrade

Q: No results from YellowPages/Yelp

A: Website may be blocking. Wait 60 seconds and retry. Proxy pool will auto-rotate.

Q: Email verification shows "unknown"

A: Domain exists but has no MX record. Email may still work.

Q: Search takes too long

A: Reduce radius, limit per-source results, or disable enrichment.

Q: Rate limiting on DuckDuckGo

A: Built-in rate limiter (12/min) automatically pauses. Check scraper.log.

Logging
Logs are written to ~/.contractor_finder.log (rotates at 5MB):

bash
# View logs on Linux/macOS
tail -f ~/.contractor_finder.log

# View logs on Windows (PowerShell)
Get-Content ~\.contractor_finder.log -Wait
📊 Performance Benchmarks
Search Parameters	Time	Results
1 trade, 30 limit, no enrichment	45-60s	~90
3 trades, 30 limit, with enrichment	3-5 min	~180
3 trades, 50 limit, all sources	6-8 min	~300
Tested on: Warren, MI | 40 mi radius | All sources

🛡️ Legal & Ethical Use
This tool is for legitimate business research only:

Respect robots.txt and rate limits

Don't overload target servers

Use for finding contractor contact info for legitimate business purposes

Comply with website Terms of Service

🤝 Contributing
Fork the repository

Create a feature branch (git checkout -b feature/AmazingFeature)

Commit changes (git commit -m 'Add AmazingFeature')

Push to branch (git push origin feature/AmazingFeature)

Open a Pull Request

Development Setup
bash
# Install development dependencies
pip install black pylint pytest

# Run tests
pytest tests/

# Format code
black contractor_gui.py
📝 Release Notes
v3.0 (Current)
Async enrichment (15x parallel)

Yelp StealthySession (bypasses anti-bot)

Role account detection

Search history dropdown

Persistent async event loop

Structured logging to file

v2.x
SQLite caching

Proxy pool with health scoring

Google Maps integration

Email MX verification

v1.x
Basic scraping (OSM + YellowPages)

CSV/TXT export

📄 License
MIT License - see LICENSE file for details

🙏 Acknowledgments
Scrapling - Stealth browser automation

Nominatim - Geocoding API

Overpass API - OSM data queries

PySide6 - Qt GUI framework

📧 Contact
For bugs or feature requests, please open a GitHub issu
