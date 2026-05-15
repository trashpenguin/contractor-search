# Result Quality Improvement — Design Spec

**Date:** 2026-05-15
**Problem:** ~50% of search results are "dead data" — real businesses with no phone, email, or website.
**Goal:** Surface complete results first and recover contact info that is already available but being missed.

---

## Section 1 — Result Scoring & Table Filtering

### What
Each `Contractor` gets a `quality_score` (0–3): one point each for having a phone, email, and website.

### How
- Add a `quality_score` computed property to `models.py` — no new stored field, derived from existing fields at read time.
- `gui/table_mixin.py` — sort rows by `quality_score` descending when populating the table so complete results appear first automatically.
- `gui/search_mixin.py` — add a "Hide incomplete" checkbox next to the existing search controls. When checked, rows with `quality_score == 0` are hidden. Default: unchecked.

### Files
| File | Change |
|------|--------|
| `models.py` | Add `quality_score` property |
| `gui/table_mixin.py` | Sort by score on populate; apply hide filter |
| `gui/search_mixin.py` | Add "Hide incomplete" checkbox widget |

### Non-goals
- No visual score column in the table (would clutter the UI).
- Score is not persisted — computed fresh each render.

---

## Section 2 — Deeper Phone Recovery from Listing Pages

### What
Fix three scrapers that drop available phone numbers before website enrichment runs.

### How

**Yelp (`scrapers/yelp.py`)**
The `/biz/` fetch already runs but `__NEXT_DATA__` phone key varies by page version. Add a fallback key walk in priority order: `primaryPhone → phone → formattedPhone`. Stop at the first non-empty value.

**YellowPages (`scrapers/yellowpages.py`)**
Search results page cards are parsed but individual profile pages are skipped. For any contractor returned phone-less from the search pass, fetch its YP profile URL and extract the direct-dial number with the existing phone regex.

**OSM (`scrapers/osm.py`)**
Overpass results include `contact:phone` and `phone` tags that are not read. Add both keys to the tag extraction block alongside the existing `name` and `addr:*` reads.

### Files
| File | Change |
|------|--------|
| `scrapers/yelp.py` | Multi-key phone walk in `__NEXT_DATA__` |
| `scrapers/yellowpages.py` | Fetch profile page for phone-less results |
| `scrapers/osm.py` | Read `contact:phone` and `phone` tags |

### Non-goals
- No new HTTP libraries.
- YP profile fetch is skipped if the result already has a phone to avoid extra requests.

---

## Section 3 — Wider Domain Guessing

### What
Expand the domain pattern list and add a DDG fallback for contractors still without a website after pattern guessing.

### How

**Trade-specific suffix patterns (`enricher.py`)**
Pull trade keywords from the existing `TRADE_KW` constant (already imported). For each trade keyword associated with a contractor, append it as a suffix: `{name}{trade}.com`, plus `.net` variants of the current `.com` patterns. No hardcoding — the suffix list is derived from `TRADE_KW` at runtime.

**DDG fallback lookup (`enricher.py`)**
For contractors with `quality_score == 0` after all pattern guessing, run one DDG search: `"{name}" "{city}" -yelp -yellowpages`. Take the first result URL not in `SKIP_DOMAINS`. Reuses the existing DDG cache — no extra requests for businesses already looked up. Gate this behind the score check so it only runs for truly empty results.

### Files
| File | Change |
|------|--------|
| `enricher.py` | Expand domain pattern list; add DDG fallback gate |

### Non-goals
- No Facebook or LinkedIn scraping in this iteration.
- DDG fallback does not run for contractors that already have any contact field.

---

## Summary

| Section | Files changed | New dependencies |
|---------|--------------|-----------------|
| 1 — Scoring & filter | `models.py`, `gui/table_mixin.py`, `gui/search_mixin.py` | None |
| 2 — Phone recovery | `scrapers/yelp.py`, `scrapers/yellowpages.py`, `scrapers/osm.py` | None |
| 3 — Domain guessing | `enricher.py` | None |

All three sections share zero new external dependencies and build on existing patterns in the codebase.
