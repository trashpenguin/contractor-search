# Result Quality Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut dead-data results from ~50% to under 20% by scoring results, sorting complete ones first, hiding empties on demand, and recovering phones/domains that are already available but being missed.

**Architecture:** Three independent layers — (1) a `quality_score` property on `Contractor` drives table sorting and a hide-incomplete toggle; (2) targeted phone extraction fixes in Yelp and YellowPages scrapers; (3) wider domain-guessing patterns + a smarter DDG fallback query in the enricher. Each layer is independently testable and does not affect the others.

**Tech Stack:** PySide6 (GUI), aiohttp (async enrichment), scrapling (Yelp/YP parsing), existing `ddg_search` + `PHONE_RE` + `SKIP_DOMAINS` constants.

**Note:** OSM already reads `phone` and `contact:phone` tags (line 144 of `scrapers/osm.py`) — no OSM changes needed.

---

## Task 1: `quality_score` property on `Contractor`

**Files:**
- Modify: `models.py`
- Test: `tests/test_models.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py
from models import Contractor


def test_quality_score_zero():
    c = Contractor(name="Acme")
    assert c.quality_score == 0


def test_quality_score_phone_only():
    c = Contractor(name="Acme", phone="(313) 555-0100")
    assert c.quality_score == 1


def test_quality_score_phone_and_email():
    c = Contractor(name="Acme", phone="(313) 555-0100", email="a@b.com")
    assert c.quality_score == 2


def test_quality_score_full():
    c = Contractor(name="Acme", phone="(313) 555-0100", email="a@b.com", website="https://acme.com")
    assert c.quality_score == 3
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_models.py -v
```
Expected: `AttributeError: 'Contractor' object has no attribute 'quality_score'`

- [ ] **Step 3: Add `quality_score` to `models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Contractor:
    trade: str = ""
    name: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    source: str = ""
    email_status: str = ""
    place_id: str = ""

    @property
    def quality_score(self) -> int:
        return bool(self.phone) + bool(self.email) + bool(self.website)
```

- [ ] **Step 4: Run tests to confirm pass**

```
pytest tests/test_models.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add quality_score property to Contractor (phone+email+website)"
```

---

## Task 2: Sort table by `quality_score` and add hide-incomplete filter

**Files:**
- Modify: `gui/table_mixin.py`

- [ ] **Step 1: Update `_filter` in `table_mixin.py`**

Replace the existing `_filter` method and add a `_hide_incomplete` helper.
The `_filter` method must (a) sort rows by `quality_score` descending, and (b) skip score-0 rows when the hide checkbox is checked.

The hide checkbox will be added in Task 3 as `self.chk_hide`. Read it safely with `getattr` so the mixin doesn't hard-depend on creation order.

```python
def _filter(self):
    trade = self.tf.currentText()
    src = self.sf2.currentText()
    name = self.nf.text().strip().lower()
    hide_empty = getattr(self, "chk_hide", None)
    hide_empty_checked = hide_empty is not None and hide_empty.isChecked()

    matched = []
    for c in self.rows:
        if trade != "All" and c.trade != trade:
            continue
        if src != "All Sources" and c.source != src:
            continue
        if name and name not in c.name.lower():
            continue
        if hide_empty_checked and c.quality_score == 0:
            continue
        matched.append(c)

    matched.sort(key=lambda c: c.quality_score, reverse=True)

    self.table.setRowCount(0)
    for i, c in enumerate(matched):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._fill_row(row, c)
```

Also update `_add_row` to call `_filter` instead of inserting directly, so new rows also respect sort order. Replace the body of `_add_row` after `self.rows.append(c)`:

```python
def _add_row(self, c):
    self.rows.append(c)
    self._filter()
    self._update_stats()
```

- [ ] **Step 2: Verify app still launches and existing filter controls still work**

Run the app manually: `python contractor_gui.py`
- Search any trade/location
- Confirm results appear ordered (full results near top, empties near bottom)
- Confirm the Trade/Source/Name filters still work

- [ ] **Step 3: Commit**

```bash
git add gui/table_mixin.py
git commit -m "feat: sort table by quality_score, gate hide-incomplete in _filter"
```

---

## Task 3: Add "Hide incomplete" checkbox to the GUI

**Files:**
- Modify: `gui/main_window.py`

- [ ] **Step 1: Add the checkbox to `gui/main_window.py`**

`QCheckBox` is already imported. The filter row is the `sf` layout (around line 216). After the `self.nf` block (line 241) and before `root.addLayout(sf)` (line 243), insert:

```python
        self.chk_hide = QCheckBox("Hide incomplete")
        self.chk_hide.setToolTip("Hide contractors with no phone, email, or website")
        self.chk_hide.setFixedHeight(30)
        self.chk_hide.stateChanged.connect(self._filter)
        sf.addWidget(self.chk_hide)
```

The full filter row block after this change looks like:

```python
        sf.addWidget(self.nf)
        self.chk_hide = QCheckBox("Hide incomplete")
        self.chk_hide.setToolTip("Hide contractors with no phone, email, or website")
        self.chk_hide.setFixedHeight(30)
        self.chk_hide.stateChanged.connect(self._filter)
        sf.addWidget(self.chk_hide)
        root.addLayout(sf)
```

- [ ] **Step 3: Verify in the app**

Run `python contractor_gui.py`, do a search, then tick "Hide incomplete":
- Score-0 rows should disappear from the table
- Unticking should bring them back
- The other filters (Trade, Source, Name) should still work with it checked

- [ ] **Step 4: Commit**

```bash
git add gui/main_window.py
git commit -m "feat: add Hide incomplete checkbox wired to _filter"
```

---

## Task 4: Yelp — multi-key phone walk in `_parse_next_data`

**Files:**
- Modify: `scrapers/yelp.py`
- Test: `tests/test_yelp_phone.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_yelp_phone.py
import json
from scrapers.yelp import _parse_next_data


def _wrap(biz: dict) -> str:
    """Wrap a business dict in minimal __NEXT_DATA__ structure."""
    payload = {
        "props": {
            "pageProps": {
                "searchPageProps": {
                    "businessList": [{"searchResultBusiness": biz}]
                }
            }
        }
    }
    blob = json.dumps(payload)
    return f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'


def test_parse_next_data_display_phone():
    html = _wrap({"name": "Acme HVAC", "businessUrl": "/biz/acme", "displayPhone": "(313) 555-0101"})
    results = _parse_next_data(html)
    assert results[0]["phone"] == "(313) 555-0101"


def test_parse_next_data_primary_phone_fallback():
    html = _wrap({"name": "Acme HVAC", "businessUrl": "/biz/acme", "primaryPhone": "(313) 555-0102"})
    results = _parse_next_data(html)
    assert results[0]["phone"] == "(313) 555-0102"


def test_parse_next_data_formatted_phone_fallback():
    html = _wrap({
        "name": "Acme HVAC",
        "businessUrl": "/biz/acme",
        "formattedPhone": "(313) 555-0103",
    })
    results = _parse_next_data(html)
    assert results[0]["phone"] == "(313) 555-0103"


def test_parse_next_data_phone_empty_when_none():
    html = _wrap({"name": "Acme HVAC", "businessUrl": "/biz/acme"})
    results = _parse_next_data(html)
    assert results[0]["phone"] == ""
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_yelp_phone.py -v
```
Expected: `test_parse_next_data_primary_phone_fallback` and `test_parse_next_data_formatted_phone_fallback` FAIL (key not checked).

- [ ] **Step 3: Update phone extraction in `_parse_next_data`**

In `scrapers/yelp.py`, find the line (around line 88):
```python
"phone": biz.get("displayPhone") or biz.get("phone", ""),
```

Replace with:
```python
"phone": (
    biz.get("primaryPhone")
    or biz.get("displayPhone")
    or biz.get("phone")
    or biz.get("formattedPhone", "")
),
```

- [ ] **Step 4: Run tests to confirm pass**

```
pytest tests/test_yelp_phone.py -v
```
Expected: 4 passed

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add scrapers/yelp.py tests/test_yelp_phone.py
git commit -m "fix: add primaryPhone/formattedPhone fallbacks in Yelp __NEXT_DATA__ parser"
```

---

## Task 5: YellowPages — fetch profile page for phone-less results

**Files:**
- Modify: `scrapers/yellowpages.py`

- [ ] **Step 1: Extract the profile URL from each card**

In `scrape_yellowpages`, inside the card loop, after the name selectors block, extract the YP profile URL from the same `<a>` element used for the name:

Find this block (around line 72):
```python
name = ""
for sel in [
    "h2.n a",
    "a.business-name",
    "h2 a",
    ".business-name span",
    "a[class*='business'] span",
    "h3 a",
]:
    els = card.css(sel)
    if els:
        name = els[0].text.strip()
        if name:
            break
```

Replace with:
```python
name = ""
profile_url = ""
for sel in [
    "h2.n a",
    "a.business-name",
    "h2 a",
    ".business-name span",
    "a[class*='business'] span",
    "h3 a",
]:
    els = card.css(sel)
    if els:
        name = els[0].text.strip()
        href = els[0].attrib.get("href", "")
        if href and "yellowpages.com" in href:
            profile_url = href if href.startswith("http") else f"https://www.yellowpages.com{href}"
        if name:
            break
```

- [ ] **Step 2: After building the contractor list, fetch profile pages for phone-less results**

After the card loop (after `logger.info(f"[YP] page {pg}: {found} found ...")`), do NOT fetch inside the page loop — that would block paging. Instead, after all pages are scraped (still inside the `try` block, after the `for pg` loop completes), add a profile fetch pass:

Find the `time.sleep(1.5)` at the end of the page loop. After the entire `for pg` loop closes, add:

```python
# Fetch individual profile pages for any result still missing a phone
_profile_map = {}  # name → profile_url, built during card parsing above
# (profile_url is stored on the Contractor via a temporary attribute below)
for contractor in out:
    _pu = getattr(contractor, "_yp_profile_url", "")
    if _pu and not contractor.phone:
        try:
            resp2 = session.fetch(_pu, wait=3000)
            html2 = resp2.body or ""
            if html2 and not _is_cloudflare(html2):
                m = PHONE_RE.search(Adaptor(html2).get_all_text(separator=" "))
                if m:
                    contractor.phone = m.group(1)
        except Exception:
            pass
        time.sleep(0.5)
```

- [ ] **Step 3: Store `profile_url` on the contractor temporarily**

When creating the `Contractor` in the card loop, also stash the profile URL as a temporary attribute (it won't be serialized — dataclass ignores unknown attrs set post-init):

Find:
```python
out.append(
    Contractor(
        trade=trade,
        name=name,
        phone=phone,
        website=website,
        address=address,
        source="YellowPages",
    )
)
```

Replace with:
```python
c = Contractor(
    trade=trade,
    name=name,
    phone=phone,
    website=website,
    address=address,
    source="YellowPages",
)
c._yp_profile_url = profile_url  # type: ignore[attr-defined]
out.append(c)
```

- [ ] **Step 4: Verify manually**

Run the app, search YellowPages for a trade where some results have blank phones. Confirm that profile-page fetches fill in numbers that were previously empty. Check logs for `[YP]` entries.

- [ ] **Step 5: Commit**

```bash
git add scrapers/yellowpages.py
git commit -m "fix: fetch YP profile page for phone-less results to recover direct-dial numbers"
```

---

## Task 6: Enricher — expand domain patterns and smarter DDG query

**Files:**
- Modify: `enricher.py`
- Test: `tests/test_enricher_domain.py` (create)

- [ ] **Step 1: Write failing test for new domain patterns**

```python
# tests/test_enricher_domain.py
from enricher import _build_domain_candidates


def test_includes_net_variant():
    candidates = _build_domain_candidates("acme", "detroit")
    assert any(".net" in c for c in candidates)


def test_includes_trade_suffix():
    candidates = _build_domain_candidates("acme", "detroit", trade_suffix="plumbing")
    assert any("acmeplumbing" in c for c in candidates)


def test_no_short_names():
    candidates = _build_domain_candidates("ab", "detroit")
    assert candidates == []
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_enricher_domain.py -v
```
Expected: `ImportError: cannot import name '_build_domain_candidates'`

- [ ] **Step 3: Extract `_build_domain_candidates` from `_guess_domain` in `enricher.py`**

Add this function near the top of `enricher.py`, before `enrich_batch_async`:

```python
def _build_domain_candidates(
    clean_name: str, clean_city: str, trade_suffix: str = ""
) -> list[str]:
    """Return ordered list of domain URLs to probe for a contractor."""
    if len(clean_name) < 3:
        return []
    base = [
        f"https://www.{clean_name}.com",
        f"https://{clean_name}.com",
        f"https://www.{clean_name}{clean_city}.com",
        f"https://www.{clean_name}hvac.com",
        f"https://www.{clean_name}heating.com",
        f"https://www.{clean_name}electric.com",
        f"https://www.{clean_name}excavating.com",
        f"https://www.{clean_name}contracting.com",
        f"https://www.{clean_name}plumbing.com",
        f"https://www.{clean_name}roofing.com",
        # .net variants
        f"https://www.{clean_name}.net",
        f"https://{clean_name}.net",
        f"https://www.{clean_name}{clean_city}.net",
    ]
    if trade_suffix:
        base.insert(3, f"https://www.{clean_name}{trade_suffix}.com")
        base.insert(4, f"https://www.{clean_name}{trade_suffix}.net")
    return base
```

- [ ] **Step 4: Run tests to confirm pass**

```
pytest tests/test_enricher_domain.py -v
```
Expected: 3 passed

- [ ] **Step 5: Wire `_build_domain_candidates` into `_guess_domain`**

Inside `enrich_batch_async`, find the `_guess_domain` inner function and replace its candidate list with a call to `_build_domain_candidates`. The `c.trade` is available in the outer `enrich_one` scope.

Replace the current `_guess_domain` body:

```python
async def _guess_domain(name: str, trade: str, session) -> str:
    clean = re.sub(r"[^a-z0-9]", "", name.lower())
    city_c = re.sub(r"[^a-z0-9]", "", city_hint.lower())
    # pick first trade keyword as suffix (e.g. "plumbing", "hvac")
    trade_kws = TRADE_KW.get(trade, {}).get("ddg", [])
    trade_suffix = re.sub(r"[^a-z0-9]", "", trade_kws[0].lower()) if trade_kws else ""
    candidates = _build_domain_candidates(clean, city_c, trade_suffix)
    if not candidates:
        return ""
    t_short = aiohttp.ClientTimeout(total=3)
    for url in candidates[:8]:  # check first 8; beyond that accuracy drops
        try:
            async with session.head(url, timeout=t_short, ssl=True, allow_redirects=True) as r:
                if r.status in (200, 301, 302, 304):
                    return str(r.url)
        except Exception:
            try:
                async with session.head(
                    url, timeout=t_short, ssl=False, allow_redirects=True
                ) as r:
                    if r.status in (200, 301, 302, 304):
                        return str(r.url)
            except Exception:
                pass
    return ""
```

Also update the call site in `enrich_one` (Step 1 of domain guessing):
```python
if not c.website and c.name:
    guessed = await _guess_domain(c.name, c.trade, session)
    if guessed:
        c.website = guessed
```

- [ ] **Step 6: Update DDG query to exclude listing sites**

Find the DDG lookup in `enrich_one` (Step 2):
```python
q = quote_plus(f'"{c.name}" {loc_hint} contractor')
```

Replace with a query that excludes listing sites (reuses the result URLs that are already filtered by `SKIP_DOMAINS`):
```python
q = quote_plus(f'"{c.name}" "{loc_hint}" -yelp -yellowpages -bbb')
```

- [ ] **Step 7: Gate DDG fallback on score-0 contractors**

Still in `enrich_one`, wrap the DDG lookup (Step 2) with a score gate so it only runs for truly empty results, saving DDG quota for contractors that need it most:

```python
if not c.website and c.name and ddg_count[0] < DDG_CAP and c.quality_score == 0:
    ddg_count[0] += 1
    ...
```

- [ ] **Step 8: Run full test suite**

```
pytest tests/ -v
```
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add enricher.py tests/test_enricher_domain.py
git commit -m "feat: expand domain guessing patterns (.net, trade suffix) and smarter DDG fallback query"
```

---

## Task 7: Push and verify CI

- [ ] **Step 1: Push**

```bash
git push
```

- [ ] **Step 2: Watch CI**

Open the Actions tab on GitHub. Both `lint` and `test` jobs should pass. If lint fails, run `black . && isort . && flake8 .` locally, fix any issues, and push again.

- [ ] **Step 3: Smoke-test the full flow**

Run `python contractor_gui.py`, search "HVAC" in a real city with all sources enabled. Confirm:
- Complete results (3/3) appear at the top
- Ticking "Hide incomplete" removes score-0 rows
- More results have phones than before the fix
