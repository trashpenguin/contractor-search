# Contractor Finder v3

Professional desktop application for finding contractors (HVAC, Electrical, Excavating) across USA locations. The application aggregates data from multiple sources including OpenStreetMap, YellowPages, Yelp, and Google Maps, then enriches the results with phone numbers, emails, websites, and business details.

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

---

# ✨ Features

- Multi-source contractor scraping
- Async enrichment pipeline
- SQLite caching system
- Smart proxy rotation with health scoring
- Email extraction & validation
- Website discovery & scraping
- Google Sheets export support
- Dark-themed desktop UI
- Search history support
- Multi-trade searching
- Structured logging
- High-speed async processing

---

# 🔍 Supported Sources

| Source | Purpose |
|---|---|
| OpenStreetMap (OSM) | Business discovery |
| YellowPages | Contractor listings |
| Yelp | Business reviews & contact discovery |
| Google Maps | Additional contractor discovery |
| DuckDuckGo | Website & email enrichment |

---

# 📋 Requirements

## Python

- Python 3.9 or higher

## Dependencies

Install required packages:

```bash
pip install PySide6 scrapling aiohttp dnspython aiosqlite
```
Or install from requirements.txt:
```bash
pip install -r requirements.txt
```
🚀 Installation
Clone Repository
git clone https://github.com/yourusername/contractor-finder.git
cd contractor-finder
Install Dependencies
pip install -r requirements.txt
Run Application
python contractor_gui.py
📦 Build Executable
Install PyInstaller
pip install pyinstaller
Build Single Executable
pyinstaller --onefile --windowed --name "ContractorFinder" contractor_gui.py

Executable will be generated inside:

dist/
🎯 Usage Guide
Basic Search
Enter a US city, state, or ZIP code
Select one or more trades
Select data sources
Configure search radius
Click Search

Results will appear in the results table.

⚙️ Search Parameters
Parameter	Description	Default
Location	US city/state or ZIP	Warren, MI
Radius	Search radius	40 miles
Per Trade/Source	Max results per source	30
Enrichment	Website/email extraction	Enabled
📊 Result Columns
Column	Description
Trade	Contractor category
Source	Data source
Company Name	Business name
Phone	Normalized phone
Email	Extracted or guessed email
Email Status	Validation status
Website	Business website
Address	Business address
Note	Additional warnings/info
🏗️ Application Architecture
Data Flow
Search Location
      ↓
Geocode via Nominatim
      ↓
Parallel Multi-Source Scraping
 ├── OSM
 ├── YellowPages
 ├── Yelp
 └── Google Maps
      ↓
Deduplication
      ↓
Async Enrichment Pipeline
 ├── Domain Guessing
 ├── DDG Fallback Search
 ├── Website Scraping
 └── Contact Extraction
      ↓
Email Validation
      ↓
Display & Export
🔧 Core Components
Scrapling

Stealth browser automation & anti-bot handling.

aiohttp

Async HTTP requests with connection pooling.

SQLite

Persistent caching system for:

contacts
DDG results
search history
websites
Proxy Manager

Features:

automatic proxy testing
health scoring
sticky sessions
retry handling
Async Enrichment

Parallel enrichment pipeline:

website scraping
email extraction
contact discovery
MX verification
💾 Cache Locations
Windows
C:\Users\[USERNAME]\.contractor_finder_cache.db
Linux/macOS
~/.contractor_finder_cache.db
⚙️ Configuration
Optional Environment Variables
Linux/macOS
export AIOHTTP_TIMEOUT=15
export NO_PROXY=1
Windows PowerShell
$env:AIOHTTP_TIMEOUT=15
$env:NO_PROXY=1
🔨 Modifying Trade Keywords

Edit the TRADE_KW dictionary:

TRADE_KW = {
    "HVAC": {
        "osm": ["heating", "hvac", "furnace"],
        "yp": "hvac+contractor",
        "google": "HVAC contractor",
        "yelp": "hvac"
    }
}
📈 Performance Benchmarks
Search Type	Time	Approx Results
1 trade, no enrichment	45–60 sec	~90
3 trades, enrichment	3–5 min	~180
3 trades, all sources	6–8 min	~300
Tested On
Warren, MI
40 mile radius
All sources enabled
🔍 Logging

Logs are stored at:

Windows
~\.contractor_finder.log
Linux/macOS
~/.contractor_finder.log
View Logs
Linux/macOS
tail -f ~/.contractor_finder.log
Windows PowerShell
Get-Content ~\.contractor_finder.log -Wait
🛠️ Troubleshooting
Scrapling unavailable

Update Scrapling:

pip install scrapling --upgrade
No results from YellowPages or Yelp

Possible causes:

temporary blocking
rate limiting
proxy failures

Solutions:

retry after 60 seconds
enable proxy rotation
reduce concurrency
Search takes too long

Suggestions:

reduce search radius
lower per-source limits
disable enrichment
DuckDuckGo rate limiting

The app includes:

built-in DDG limiter
automatic cooldown pauses
concurrency restrictions

Check logs for:

[DDG] Rate limit pause
🛡️ Legal & Ethical Use

This tool is intended for legitimate business research only.

Please:

respect website rate limits
avoid excessive scraping
comply with Terms of Service
use responsibly
🤝 Contributing
Fork Repository
git clone https://github.com/yourusername/contractor-finder.git
Create Branch
git checkout -b feature/AmazingFeature
Commit Changes
git commit -m "Add AmazingFeature"
Push Changes
git push origin feature/AmazingFeature
Open Pull Request

Submit your PR through GitHub.

🧪 Development Setup
Install Development Dependencies
pip install black pylint pytest
Run Tests
pytest tests/
Format Code
black contractor_gui.py
📝 Release Notes
v3.0
Async enrichment pipeline
Yelp stealth scraping
Role account detection
Search history support
Persistent async event loop
Structured file logging
SQLite caching
Improved proxy pool
v2.x
Google Maps integration
Email MX verification
Proxy rotation
Website enrichment
v1.x
Basic OSM + YellowPages scraping
CSV/TXT export
📄 License

MIT License

See the LICENSE file for more details.

🙏 Acknowledgments
Scrapling
OpenStreetMap
Overpass API
Nominatim
PySide6
aiohttp
dnspython
📧 Support

For bug reports, feature requests, or improvements:

Open an issue on GitHub.
