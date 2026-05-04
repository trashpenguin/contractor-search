# 🏗️ Contractor Finder

A desktop GUI tool to find **HVAC**, **Electrical**, and **Excavating/Dirtwork** contractors near any US location — built for sourcing vendors for commercial and storage facility projects.

Powered by **Scrapling** (smart web scraping), **PySide6** (GUI), and free **OpenStreetMap / Overpass** data — no paid API keys required.

---

## 📸 Features

- 🔍 Search contractors by **any US city, address, or ZIP code**
- 🏷️ Covers **3 trade types**: HVAC · Electrical · Excavating
- 🌐 **Scrapling-powered** website scraping to extract phone numbers and emails
- 📊 Live results table with **color-coded trades**
- 🔎 Filter by trade type or search by company name
- 📤 Export to **CSV** (Excel-ready) or **TXT**
- 🎨 Dark-themed desktop GUI (PySide6)
- 🆓 100% free — no API keys needed

---

## 📁 Files

| File | Description |
|------|-------------|
| `contractor_gui.py` | Main GUI application |
| `contractor_search.py` | Command-line version (no GUI) |
| `launch_windows.bat` | One-click launcher for Windows |
| `launch_mac_linux.sh` | One-click launcher for Mac/Linux |
| `requirements.txt` | Python dependencies |

---

## 🚀 Quick Start

### Windows
1. Make sure [Python 3.8+](https://python.org) is installed
2. Put all files in the **same folder**
3. Double-click **`launch_windows.bat`**
4. Wait for dependencies to install (first run only)
5. The GUI will open automatically

### Mac / Linux
```bash
bash launch_mac_linux.sh
```

### Manual Setup (any OS)
```bash
# Install dependencies
pip install scrapling browserforge curl_cffi playwright PySide6

# Install Playwright browser
python -m playwright install chromium

# Run the GUI
python contractor_gui.py
```

---

## 🖥️ GUI Usage

1. **Enter a location** — city, address, or ZIP (e.g. `Warren, MI 48091`)
2. **Choose a radius** — 10 to 80 miles
3. **Set results per trade** — up to 50 per category
4. **Select trades** — HVAC, Electrical, Excavating (or all three)
5. **Toggle website scraping** — finds missing emails/phones from contractor websites
6. Click **Search Contractors ↗**
7. Results stream in live — filter, sort, then export

---

## 💻 Command-Line Usage

```bash
# Basic search — Warren, MI
python contractor_search.py "Warren, MI 48091"

# Custom radius and result count
python contractor_search.py "Detroit, MI" --radius-m 50000 --per-category 30

# Search specific trades only
python contractor_search.py "Chicago, IL" --categories "HVAC contractor"

# Print results to terminal
python contractor_search.py "Houston, TX" --print

# Save to custom file
python contractor_search.py "Phoenix, AZ" --output phoenix_contractors.csv
```

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `location` | *(required)* | City, address, or ZIP |
| `--categories` | All 3 trades | Which trades to search |
| `--per-category` | `30` | Max results per trade |
| `--radius-m` | `40000` | Search radius in meters (~25 mi) |
| `--output` | `contractors.csv` | Output CSV filename |
| `--print` | off | Print table to terminal |

---

## 📦 Requirements

- Python 3.8+
- pip packages (auto-installed by launcher):

```
scrapling
browserforge
curl_cffi
playwright
PySide6
```

---

## 📊 Output Columns

| Column | Description |
|--------|-------------|
| Trade | HVAC / Electrical / Excavating |
| Company Name | Business name |
| Phone | Phone number |
| Email | Contact email (scraped from website if not in OSM) |
| Website | Company website |
| Address | Street address |

---

## 🔧 How It Works

1. **Geocoding** — Converts your location input to coordinates using [Nominatim](https://nominatim.openstreetmap.org/) (free OpenStreetMap API)
2. **Overpass API** — Queries OpenStreetMap's Overpass API for businesses matching trade keywords within your radius
3. **Scrapling enrichment** — For contractors that have a website but no email/phone in OSM, the tool scrapes their site using Scrapling's smart CSS selectors and regex, also checking contact/about pages
4. **Export** — Save results as CSV (opens in Excel) or formatted TXT

---

## ⚠️ Notes

- Results depend on OpenStreetMap data coverage in your area — rural areas may return fewer results
- Email/phone accuracy depends on what's publicly listed on contractor websites
- Always verify contact info before reaching out
- Respect contractor websites' terms of service when scraping

---

## 🗺️ Use Case

Originally built to source contractors for a **storage facility construction project** at:
> 6014 & 6015 E 10 Mile Rd, Warren, MI 48091

Works for any commercial construction project anywhere in the US.

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

## 🤝 Contributing

Pull requests welcome. Ideas for improvement:
- [ ] Google Maps / Yelp API integration for more results
- [ ] Email verification / bounce checking
- [ ] Export to Google Sheets
- [ ] Scheduled / recurring searches
- [ ] Contractor rating/review data
