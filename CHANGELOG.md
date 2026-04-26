# DMR Codeplug Generator — Development Changelog

## Session 1 — Initial Architecture

### Goals
Build a Python CLI tool that queries RadioID.net for DMR repeater data and generates
CSV files importable into the Baofeng DM-32UV CPS (Customer Programming Software).

### Decisions Made
- Python backend first, web UI deferred to Phase 2
- Target radio: Baofeng DM-32UV
- Networks: BrandMeister, DMR-MARC, Tristate, ChicagoLand-CC
- Use `httpx` for HTTP (async-ready, clean API)
- Output: 4 CSV files matching exact DM-32UV CPS import format

### Files Created
- `codeplug/models.py` — dataclasses: Talkgroup, Repeater, Contact, Channel, RXGroup, Zone, CodeplugRequest, Codeplug
- `codeplug/radioid.py` — RadioID.net REST API client with pagination
- `codeplug/defaults.py` — TG abbreviations, network prefix map, fallback TG lists, BM hotspot TG catalog
- `codeplug/builder.py` — CodeplugBuilder: assembles contacts, channels, zones from repeater data
- `codeplug/csv_export.py` — writes the 4 CSV files in exact DM-32UV CPS format
- `main.py` — argparse CLI

### Key CLI Arguments
```
--dmr-id        Your DMR ID (looks up callsign from RadioID)
--city          Primary city
--state         Primary state
--locations     Additional "City,State" pairs for multi-location search
--networks      BrandMeister DMR-MARC Tristate ChicagoLand-CC
--max           Max repeaters (applied after dedup across all locations)
--power         TX power: High / Medium / Low
--hotspot       Include a hotspot zone
--hs-freq       Hotspot simplex frequency (default 433.550)
--hs-tgs        Hotspot talkgroup IDs
--list-hs-tgs   Print available hotspot TG catalog and exit
--out           Output directory for CSV files
--dry-run       Print summary without writing files
--refresh-bm    Force re-download of BrandMeister device + TG caches
```

---

## Session 1 (continued) — Bug Fixes from Real CPS Import Testing

### Bug: RX Group Names Silently Dropped
- **Root cause**: DM-32UV CPS silently discards any RX Group reference whose name
  exceeds 11 characters, writing `None` to the channel instead.
- **Fix**: Created `make_rx_group_name()` with hard 11-char limit.
- **Status**: RX group generation later commented out (see below).

### Bug: Contact CSV Format Wrong
- **Root cause**: Our format was `No.,Name,ID,Type` (4 columns).
  Actual CPS format is `No.,ID,Repeater,Name,City,Province,Country,Remark,Type,Alert Call` (10 columns).
- **Fix**: Updated `CONTACTS_HEADERS` and `_contact_row()` in `csv_export.py`.

### Bug: Contacts CSV Not Needed for Talkgroups
- **Discovery**: The contacts CSV (`digital_contacts.csv`) is a personal address book
  for private calls (ham operators and callsigns). It has nothing to do with talkgroups.
  The radio works fine without talkgroup entries in the contacts list.
- **Fix**: Contacts CSV is still generated (harmless) but not required for import.

### Bug: RX Group CSV Format Wrong (34 columns vs 3)
- **Root cause**: We were generating `No., Group Name, Contact 1 ... Contact 32`.
  Actual CPS export format is `No., RX Group Name, Contact Members` (3 columns,
  pipe-separated members in a single field, same pattern as zones).
- **Fix**: Updated headers and `_rx_group_row()`.

### Decision: RX Group Generation Commented Out
- With `GroupCall Match = Off` (recommended for ham use), the RX Group List is
  completely ignored — the radio receives all traffic on the correct
  frequency/color code/timeslot regardless.
- A channel must reference an RX group by name, but the group can be empty and
  `rx_group="None"` is a valid value.
- All channels now use `rx_group="None"`.
- The RX group building code remains in `builder.py` as commented-out blocks for
  future re-enablement if per-repeater receive filtering is desired.

### Bug: Duplicate/Redundant Contact Names
- **Example**: TG 310 had abbrev "TAC310", so contact name was "BM TAC310 310".
- **Fix**: `make_contact_name()` skips appending the ID if the abbreviation already
  ends with it.

### Bug: TG Abbreviation Conflicts
- TG 1 and TG 9 both mapped to "Local", causing channel name collisions.
- **Fix**: TG 1 → "Loc1", TG 9 → "Local".

---

## Session 1 (continued) — Multi-Location Search

### Feature: Multiple Cities Across Multiple States
- Added `--locations "City,State"` nargs argument alongside existing `--city`/`--state`.
- Deduplication by callsign across all location searches.
- State-level fallback (when city returns < 3 results) fires at most once per state
  to avoid redundant API calls.
- `--max` is applied globally after all locations are searched.

### Bug: "BM" Network Alias Missing
- RadioID stores some repeaters as `ipsc_network = "BM"` instead of "BrandMeister".
- Our network filter used `{"brandmeister"}` and silently dropped these.
- **Fix**: Added "BM" to the BrandMeister alias list in `network_aliases`.
- **Impact**: N9ZD (Oak Forest — confirmed BM) was previously missing from results.

---

## Session 1 (continued) — BrandMeister API Integration

### Feature: BM Device Verification
- Added `codeplug/brandmeister.py` with BM API v2 client.
- API key stored in `~/.config/dmr-codeplug.json` (never in source code).
- Downloads full device list (~32,000 entries) and caches to
  `~/.config/dmr-codeplug-bm-devices.json` indefinitely.
- `build_repeater_index()` filters to actual repeaters only (`tx != rx`).
  Hotspots have identical TX and RX frequencies and are excluded.

### Feature: Automatic Network Label Correction
- If BM confirms a repeater IS registered (tx≠rx, appears in device list),
  its `network` field is corrected to "BrandMeister" regardless of RadioID label.
- If RadioID claims BM but BM doesn't confirm: warn, keep as-is (repeater may be
  temporarily offline).

### Feature: BM Talkgroup Catalog
- `GET /v2/talkgroup/` returns `{str(id): name}` for ~1,750 official BM talkgroups.
- Cached to `~/.config/dmr-codeplug-bm-talkgroups.json` indefinitely.
- Builder uses official BM names for contact/channel name generation, falling back
  to RadioID description, then to the `TG_ABBREV` dictionary.
- Use `--refresh-bm` to force re-download of both caches.

---

## What's Next (Phase 2) — Web Interface

Replace the CLI with a FastAPI web application. See `ONBOARDING.md` for full spec.
