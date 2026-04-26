# CODEPLUGGER — Onboarding Guide

## What This Project Does

Automates generation of DMR radio codeplugs for the **Baofeng DM-32UV** radio.
Pulls repeater data from multiple sources (RadioID, BrandMeister, RadioReference,
local SQLite database built from KML + PDFs), and produces a ZIP of CSV files
importable into the DM-32UV CPS programming software.

Both a **CLI tool** and a **web interface** (CODEPLUGGER) are fully working.

---

## Environment

- **Python**: Must use `python3.12` — the system `python3` is 3.14 and lacks the
  required packages. Run everything as `python3.12`.
- **Install deps**: `pip3 install -r requirements.txt`
- **Key deps**: `httpx`, `fastapi`, `uvicorn`, `pdfplumber`

---

## Project Structure

```
dmr-codeplug/
├── main.py                      # CLI entry point (argparse)
├── import_data.py               # Repeater DB import tool (KML, PDF, HearHam)
├── requirements.txt
├── CHANGELOG.md
├── LESSONS_LEARNED.md
├── ONBOARDING.md                # This file
├── data/
│   └── repeaters.db             # SQLite repeater database (gitignored, rebuild with import_data.py)
├── codeplug/
│   ├── __init__.py
│   ├── models.py                # Dataclasses: Talkgroup, Repeater, Channel, Zone, etc.
│   ├── radioid.py               # RadioID.net API client
│   ├── brandmeister.py          # BrandMeister API client + caching
│   ├── radioreference.py        # RadioReference.com SOAP API client
│   ├── repeater_db.py           # SQLite repeater DB (analog + digital repeaters)
│   ├── kml_import.py            # KML/KMZ parser for Google Earth ham repeater data
│   ├── pdf_import.py            # PDF parser for regional repeater directories
│   ├── hearham_import.py        # HearHam.com DMR talkgroup scraper
│   ├── defaults.py              # TG abbreviations, network prefixes, fallback TG lists
│   ├── builder.py               # CodeplugBuilder: assembles codeplug from repeater data
│   └── csv_export.py            # Writes the 4 DM-32UV CSV files + README.txt
└── web/
    ├── app.py                   # FastAPI backend
    └── static/
        ├── index.html           # Single-page dark-themed UI
        └── logo.png             # CODEPLUGGER logo
```

---

## Running the Web App

```bash
cd /home/jim/dmr-codeplug
python3.12 -m uvicorn web.app:app --reload --port 8000
# Open http://localhost:8000
```

---

## Running the CLI

```bash
python3.12 main.py \
  --dmr-id 3179879 \
  --city "Chicago" --state Illinois \
  --locations "Dyer,Indiana" "Gary,Indiana" "Crown Point,Indiana" "Valparaiso,Indiana" \
  --networks BrandMeister DMR-MARC Tristate \
  --max 40 \
  --hotspot --hs-tgs 91 93 3117 3118 9 310 312 \
  --out ./my_codeplug
```

---

## Repeater Database

`data/repeaters.db` is a local SQLite database used to supplement the live API calls.
It is **gitignored** — rebuild it with `import_data.py`.

### Tables

- **`repeaters`** — analog + digital repeaters from KML/PDF sources
  - `(rx_freq, tx_freq, callsign, state)` UNIQUE constraint
  - fields: source, callsign, city, state, country, rx_freq, tx_freq, ctcss_encode, mode, notes
- **`dmr_repeaters`** — DMR repeaters from HearHam with color code
  - `hearham_id` UNIQUE
  - fields: hearham_id, callsign, city, state, rx_freq, tx_freq, color_code, network
- **`dmr_talkgroups`** — per-repeater static TG list from HearHam
  - FK: `repeater_id → dmr_repeaters.id`
  - fields: timeslot, tg_id, tg_name

### Import Tool

```bash
# Show DB stats
python3.12 import_data.py --stats

# Import KML from Google Drive ZIP (auto-discovers drive-download*.zip)
python3.12 import_data.py

# Import only specific states from KML
python3.12 import_data.py --states IL IN WI

# Import HearHam DMR TG data (be polite — 0.6s delay between requests)
python3.12 import_data.py --hearham IL IN WI   # specific states
python3.12 import_data.py --hearham             # all 50 states + DC + territories

# Import a specific PDF
python3.12 import_data.py --pdf Iowa_RC.pdf

# Import all PDFs in a directory
python3.12 import_data.py --pdf-dir /path/to/pdfs/
```

### KML Source

Download the Google Earth Ham Repeaters KML ZIP from the Google Drive link shown
when no ZIP is present. Place `drive-download*.zip` in the project root and run
`import_data.py`. This contains RepeaterBook data for all 50 states, organized as:
```
{State}/2 Meters/{State} 2M.kml
{State}/70 Centimeters/{State} 70CM.kml
```

### PDF Sources Supported

Format auto-detected from first-page text:

| Organization | State | Columns |
|---|---|---|
| Iowa Repeater Council | Iowa | City Output Call Access Mode Notes |
| Minnesota Repeater Council | Minnesota | CITY REGION Output Call Club Access Notes Date |
| Western Pennsylvania RC (WPRC) | Pennsylvania | Output Input Access Location Grid Call Trustee Sponsor Notes |
| All Oregon Repeaters | Oregon | Freq± PL Location County Callsign Status |
| Greater Rochester Area | New York | CH RECEIVE TRANSMIT TONE TRUSTEE LOCATION COMMENTS |

### HearHam Coverage Note

HearHam.com aggregates DMR repeaters with color code visible from the state listing.
Only ~5% have manually-entered talkgroup lists on their detail pages. Most repeaters
show callsign/freq/CC but no TG data. Useful for color code lookup; TG data is sparse.

---

## Config File

`~/.config/dmr-codeplug.json` — API credentials:
```json
{
  "brandmeister_api_key": "eyJ0eXAi...",
  "radioreference_app_key": "a476798c-40db-11f1-bb32-0ef97433b5f9",
  "radioreference_username": "...",
  "radioreference_password": "..."
}
```

**Never commit this file.** BM API key is also read from env var `BM_API_KEY`.

## BrandMeister Cache Files (auto-managed)

- `~/.config/dmr-codeplug-bm-devices.json` — all BM devices (~32K entries)
- `~/.config/dmr-codeplug-bm-talkgroups.json` — BM talkgroup catalog (~1,750 entries)

Use `--refresh-bm` (CLI) to force refresh.

---

## Data Flow

```
RadioID API
    ↓ search_repeaters(state, city, networks)
    ↓ network alias expansion (NETWORK_ALIASES covers all ipsc_network spellings)
    ↓ deduplicate by callsign across locations
BrandMeister API (cached)
    ↓ verify repeater is on BM (build_repeater_index)
    ↓ load official talkgroup catalog
    ↓ GET /v2/device/{bm_id}/talkgroup/ — per-device static TG config (future)
RadioReference SOAP API
    ↓ zip-code → city/state/coordinates
    ↓ county amateur frequencies (FM, 2m/70cm only)
Local repeater DB (data/repeaters.db)
    ↓ analog repeater search by state
    ↓ HearHam DMR TG lookup by callsign + frequency
CodeplugBuilder
    ↓ build contacts, channels, zones per repeater
    ↓ TG name: BM catalog > RadioID description > TG_ABBREV fallback > T{id}
    ↓ enforce MAX_NAME_LEN = 12 on all names
csv_export
    ↓ write 4 CSV files + README.txt → ZIP
User imports: Talk Groups → RX Group Lists → Channels → Zones
```

---

## Key Design Decisions

### Name Length Limit: 12 Characters

All channel names, zone names, contact names, and talkgroup names are capped at
**12 characters** (`MAX_NAME_LEN = 12` in `builder.py`). This is stricter than
the radio's actual limit to keep names readable on the small LCD.

**Naming rules:**
- Channel name: `{city_abbr}{freq_suffix} {tg_abbr}` — e.g. `ChiPtWav BM`
- Zone name: `{city}{freq_suffix} {network_prefix}` — e.g. `Chicago975 BM`
- Contact/TG name: `{abbr}` or `{abbr} {id}` — ID appended only when `len(abbr) ≤ 3`
  (short abbreviations like `WW`, `NA`, `IL` need the ID to distinguish similar TGs;
  longer words like `Parrot`, `Local`, `Calling` are self-identifying)
- Disambiguation: counter appended as `{base[:12-len(str(n))]}{n}`

### Parrot TG Must Be Private Call

BrandMeister Parrot (diagnostic echo-back tool) is **silently ignored as a Group Call**.
It only works as a **Private Call**.

- **9990** — worldwide BM Parrot (primary)
- **310997** — US regional Parrot (MCC 310 + suffix 997); also Private Call
- **9998** — legacy alias; kept in TG_ABBREV for compat

`PRIVATE_CALL_TGS = {9990, 9998, 310997}` in `defaults.py`. Contacts for these IDs
use `call_type="Private Call"` in `builder.py`.

### Network Alias Expansion

RadioID `ipsc_network` is self-reported with inconsistent spellings. `NETWORK_ALIASES`
in `web/app.py` maps canonical UI labels to all observed variants:

- **BrandMeister**: "BrandMeister", "Brandmeister", "BRANDMEISTER", "BM", etc.
- **DMR-MARC**: "DMR-MARC", "MARC", "ChicagoLand-CC", "Chicagoland-CC", "chi-dmr",
  "DMR-IL", "Chicagoland C-Bridge", "Chicago Land", "chicago land cc ", etc.
- **Tristate**: "Tristate", "TriState", "TriStateDMR", "TriSTateDMR"

Without this expansion, searching for DMR-MARC returns ~8 IL results instead of ~43.

### Analog Repeaters

- Sourced from: local repeater DB (KML/PDF) + RadioReference SOAP API
- Filtered to 2m (144-148 MHz) and 70cm (420-450 MHz) only — DM-32UV can't TX on 6m or 220
- CTCSS encode-only (no decode) — standard ham practice unless directory says otherwise
- All grouped into a single "Analog" zone in the codeplug

### RX Groups

RX groups are generated (3-column CSV: No., RX Group Name, Contact Members pipe-separated)
but all channels use `rx_group="None"`. This is correct for `GroupCall Match = Off`
(the recommended ham setting). Re-enable when per-repeater RX filtering is needed.

---

## Web UI User Flow

1. **DMR ID** — enter DMR ID, fetches callsign/name/location from RadioID
2. **Locations** — add city/state pairs; also supports US zip code lookup
3. **Networks** — BrandMeister, DMR-MARC, Tristate checkboxes
4. **Find Repeaters** — searches RadioID with network alias expansion; shows BM verification
5. **Analog Repeaters** — searches local DB + RadioReference; checkable table
6. **Hotspot Talkgroups** — BM catalog accordion + manual TG entry (name + TG number)
7. **Options** — TX power, hotspot frequency
8. **Legal Disclaimer** — checkbox + initials required
9. **Generate & Download** — returns `codeplug_{callsign}.zip`

### API Endpoints

```
GET  /                          → Serves index.html
GET  /api/hotspot-talkgroups    → Grouped BM TG catalog
POST /api/lookup-user           → { dmr_id } → { callsign, name, city, state }
GET  /api/lookup-zip/{zip}      → { city, state, lat, lon } via RadioReference
POST /api/search-repeaters      → { locations, networks } → [DMR repeater list]
POST /api/search-analog         → { locations } → [analog repeater list]
POST /api/generate              → full generate request → ZIP download
```

---

## DM-32UV CSV Import Order

**Critical:** The CPS requires this exact import sequence:

1. **Talk Groups** (`talk_groups.csv`)
2. **RX Group Lists** (`rx_group_lists.csv`)
3. **Channels** (`channels.csv`)
4. **Zones** (`zones.csv`)

Importing in wrong order causes `TX Contact` fields to show "None".

The downloaded ZIP includes `README.txt` with this info and a legal disclaimer.

---

## Known Issues / TODOs

### BM Per-Device TG Endpoint (Next Up)

`GET /v2/device/{bm_id}/talkgroup/` returns `[{talkgroup, slot, repeaterid}]` —
the static TG configuration for a BM-verified repeater. This should be wired in
as a fallback when RadioID has no TG data for BM repeaters.

Tested manually:
- N9ZD (312361): TG 31172 TS1, TG 312361 TS2
- KD9COF (310963): TG 310963 TS2, TG 3219369 TS2
- N9GPY (311690): TG 31673 TS2, TG 311690 TS2

### Disconnect Channel May Need TS1 Variant

The automatic TG 4000 disconnect channel is hardcoded to TS2. On some repeaters
(especially DMR-MARC), the active TGs may all be on TS1. Should consider following
the "majority" timeslot or generating two disconnect channels.

### HearHam Coverage is Sparse

Only ~5% of HearHam's DMR repeaters have manually entered TG lists. HearHam is useful
for color code discovery but not reliable as a TG data source.

### BM Last-Heard Not Available via REST

The BrandMeister v2 REST API does not expose last-heard data. That data is only
available via the real-time WebSocket feed. Last-heard cannot be used as a
filter to rank repeaters without a streaming connection.

---

## Domain Contacts / Resources

- **RadioID API**: https://radioid.net/api/
- **BrandMeister API v2**: https://api.brandmeister.network/v2
- **BM per-device TGs**: `GET https://api.brandmeister.network/v2/device/{id}/talkgroup/`
- **HearHam state page**: `https://hearham.com/repeaters/state/{ST}`
- **RadioReference WSDL**: `http://api.radioreference.com/soap2/?wsdl&v=latest`
- **Google Earth ham repeaters**: https://drive.google.com/drive/folders/10Lvzkdtox8vG7iNkpQHSOIUfn8yUNV5b
- **User**: KQ9I (DMR ID: 3179879), Dyer, Indiana
- **User hotspot**: 433.550 MHz simplex, registered on BM as KQ9I
