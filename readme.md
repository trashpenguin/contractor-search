# Contractor Finder

A Python desktop app for discovering US contractors, collecting public contact
details, checking email domains, and exporting results. Sources include
OpenStreetMap, YellowPages, Yelp, Google Maps, Google Search, and Google Places.

## Install and launch

Use Python 3.11 or later. The dependency versions in `requirements.txt` are
pinned and tested in CI.

```bash
git clone https://github.com/trashpenguin/contractor-search.git
cd contractor-search
python -m pip install -r requirements.txt
python contractor_gui.py
```

On Windows, `launch_windows.bat` automates installation and launch.
The first launch downloads Chromium for Playwright and Patchright. To install
the browser engines manually:

```bash
python -m playwright install chromium
python -m patchright install chromium
```

Linux may also require Chromium and Qt system libraries. Google Places requires
your own API key with the appropriate API enabled; review billing and quotas in
Google Cloud before selecting that source.

## Search and verify

1. Enter a US city/state or ZIP code.
2. Select trades, sources, radius, and the result limit per trade/source.
3. Enable website enrichment to collect additional phone numbers and emails.
4. Click Search. Use Stop to cancel and retain results already displayed.
5. Filter results by trade, source, name, or contact completeness.
6. Verify Emails to check syntax and DNS mail records.

Sources run sequentially for each trade; website enrichment runs concurrently.
The radius selector uses miles and converts to meters. OSM's Overpass query and
Nominatim fallback respect this radius. Other providers use location or bias
controls and may return businesses outside the selected radius.

Guessed websites require a matching business name plus phone or address
evidence. Conflicting phone numbers or addresses prevent duplicate records
from merging. A complete contact record scores up to three points (phone,
email, website); that score measures completeness, not verified accuracy.

Email origin and verification are separate. **Guessed** emails remain labeled
after verification. A valid mail domain does not prove that the mailbox exists.
Sources, discovery timestamps, contact URLs, acquisition methods, and confidence
are retained for review. Provider pages can change or block access; failed or
partial searches are reported in the interface.

Search and email verification cannot overlap. Stop cancels queued enrichment
and retry delays; an active synchronous HTTP or browser request may need to
finish its timeout. Closing waits for active workers to finish.

## Export

- **Export CSV:** one contractor per row, including provenance and verification.
- **Export Board CSV:** trade groups and board columns, plus provenance fields.
- **Export TXT:** a readable report with email status and source information.
- **Google Sheets:** creates a board CSV and shows manual import instructions.

Exports include all collected rows. CSV saves write to a temporary file and
replace the destination atomically, preserving an existing file if saving fails.

Settings, search history, the SQLite cache, and rotating logs are stored under
your user profile. Clear Cache removes cached search and contact results.
Proxy use is optional and off by default; TLS certificate checks remain enabled.

## Development and Windows builds

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
black --check .
isort --check-only .
flake8 .
```

Run tests with Qt's offscreen platform:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ -v
```

In PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/ -v
```

Tests use real Qt, HTML parser, and HTTP dependencies with controlled network
fixtures. CI also starts the source GUI, installs and launches both Chromium
engines on Windows, builds with PyInstaller, and starts the frozen application.
`--smoke-test` checks runtime dependencies, skips browser installation, and
closes the GUI automatically.

```bash
python -m pip install -r requirements-build.txt
pyinstaller ContractorFinder.spec --clean --noconfirm
```

The Windows executable is `dist/ContractorFinder/ContractorFinder.exe`.
Download the complete `ContractorFinder-Windows` artifact from a successful
GitHub Actions run and keep its supporting files beside the executable.

## Configuration

Environment variables include `LOG_LEVEL`, `LOG_FORMAT=json`,
`ENRICH_BATCH_SIZE=15`, `DDG_CAP=30`, `SEM_DDG=2`, `SEM_GOOGLE=1`,
`SEM_YELLOWPAGES=2`, `SEM_DEFAULT=6`, `TTL_CONTACT=604800`, and
`TTL_DDG=86400`. Batch size and semaphore limits must be positive.
