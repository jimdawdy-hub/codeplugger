# DMR Codeplug Generator — Onboarding Guide

## What This Project Does

Automates generation of DMR radio codeplugs for the **Baofeng DM-32UV** radio.
Queries RadioID.net for repeater data, cross-references with the BrandMeister API
for network verification, and produces CSV files importable into the DM-32UV CPS
programming software.

The **CLI tool** is fully working. The **web interface** (CODEPLUGGER) is built and functional — see Phase 2 section below.

---

## Environment

- **Python**: Must use `python3.12` — the system `python3` is 3.14 and lacks the
  required packages. Run everything as `python3.12`.
- **Dependencies**: `httpx>=0.27.0` (see `requirements.txt`)
- **Install deps**: `pip3 install -r requirements.txt` (installs to 3.12 site-packages)

---

## Project Structure

```
dmr-codeplug/
├── main.py                    # CLI entry point (argparse)
├── requirements.txt           # httpx
├── CHANGELOG.md               # Development history
├── LESSONS_LEARNED.md         # DMR/BM/RadioID domain knowledge
├── ONBOARDING.md              # This file
├── codeplug/
│   ├── __init__.py
│   ├── models.py              # Dataclasses: Talkgroup, Repeater, Channel, Zone, etc.
│   ├── radioid.py             # RadioID.net API client
│   ├── brandmeister.py        # BrandMeister API client + caching
│   ├── defaults.py            # TG abbreviations, network prefixes, fallback TG lists
│   ├── builder.py             # CodeplugBuilder: assembles codeplug from repeater data
│   └── csv_export.py          # Writes the 4 DM-32UV CSV files
└── web/
    ├── app.py                 # FastAPI backend
    └── static/
        ├── index.html           # Single-page dark-themed UI
        └── logo.png             # CODEPLUGGER logo
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

# Dry run (no files written):
python3.12 main.py --dmr-id 3179879 --city Chicago --state Illinois --dry-run

# List available hotspot talkgroups:
python3.12 main.py --dmr-id 3179879 --city Chicago --state Illinois --list-hs-tgs

# Force refresh of BrandMeister caches:
python3.12 main.py ... --refresh-bm
```

---

## Config File

`~/.config/dmr-codeplug.json` — stores the BrandMeister API key:
```json
{
  "brandmeister_api_key": "eyJ0eXAi..."
}
```

**Never commit this file or the API key to source control.**

## Cache Files (auto-managed, never expire unless --refresh-bm)

- `~/.config/dmr-codeplug-bm-devices.json` — all BM devices (~32K entries)
- `~/.config/dmr-codeplug-bm-talkgroups.json` — BM talkgroup catalog (~1,750 entries)

---

## Data Flow

```
RadioID API
    ↓ search_repeaters(state, city, networks)
    ↓ deduplicate by callsign across locations
BrandMeister API (cached)
    ↓ verify network labels (correct mislabeled repeaters)
    ↓ load talkgroup catalog (official names)
CodeplugBuilder
    ↓ build contacts, channels, zones per repeater
    ↓ use BM talkgroup names > RadioID descriptions > TG_ABBREV fallback
csv_export
    ↓ write 4 CSV files
User imports into DM-32UV CPS (contacts → RX groups → channels → zones)
```

---

## Key Design Decisions

### RX Groups Are Generated But Not Populated
`rx_group = "None"` on all channels. RX group building code exists in `builder.py`
as commented-out blocks. This is intentional — with `GroupCall Match = Off` (the
recommended ham setting), RX groups are ignored by the radio. Re-enable when
per-repeater receive filtering is needed.

### Network Correction Logic
- RadioID `ipsc_network` is self-reported and unreliable.
- Any repeater confirmed in the BM device list (tx≠rx) gets its network field
  corrected to "BrandMeister" automatically.
- RadioID entries claiming BM that aren't in the BM registry get a warning but
  are kept as-is (they may be temporarily offline).

### Name Length Limits
| Field | Limit | Notes |
|-------|-------|-------|
| Channel name | 16 chars | Displayed on radio LCD |
| Zone name | 16 chars | Display only |
| RX Group name | 11 chars | CPS silently drops refs >11 chars |
| Contact name | 16 chars | Display in CPS |

### One Zone Per Repeater
Each repeater gets its own zone. Zone name format: `{city}{freq_suffix} {network_prefix}`
e.g. "Chicago975 BM", "Skokie BM".

### Talkgroup Name Priority
1. Official BM catalog name (from BM API)
2. RadioID description field
3. `TG_ABBREV` dictionary in `defaults.py`
4. `T{id}` fallback (truncated to 6 chars)

---

---

## Phase 2: Web Interface (CODEPLUGGER) — **BUILT**

### Status
The web interface is **complete and functional**. It is a single-page application
served by FastAPI, with a dark theme and orange accent matching the logo.

### Running the Web App
```bash
cd /home/jim/dmr-codeplug
pip3 install -r requirements.txt   # installs fastapi + uvicorn
python3.12 -m uvicorn web.app:app --reload --port 8000
# Open http://localhost:8000
```

### User Flow
1. **DMR ID lookup** — enter DMR ID, app fetches callsign/name/location from RadioID
2. **Locations** — add one or more city/state pairs (multi-location search)
3. **Networks** — checkbox selection (BrandMeister, DMR-MARC, Tristate, ChicagoLand-CC)
4. **Find Repeaters** — searches RadioID, shows table with:
   - Checkboxes for selection
   - BM verification badge (✓BM = confirmed on BrandMeister API)
   - Talkgroup summary per repeater
5. **Hotspot Talkgroups** — accordion-grouped catalog with search filter
6. **Options** — TX power, hotspot frequency
7. **Legal Disclaimer** — checkbox + initials required before download
8. **Generate & Download** — returns ZIP with 4 CSV files

### API Endpoints
```
GET  /                          → Serves index.html
GET  /api/hotspot-talkgroups    → Grouped BM TG catalog for UI
POST /api/lookup-user           → { dmr_id } → { callsign, name, city, state }
POST /api/search-repeaters      → { locations, networks } → [repeater list]
POST /api/generate              → { dmr_id, callsign, locations, networks,
                                    selected_repeaters, hotspot_tg_ids, power,
                                    hotspot_freq, initials }
                                 → ZIP download (application/zip)
```

### Web UI Features
- **No build step** — vanilla JS, single HTML file
- **Dark theme** with CSS variables (`--bg: #0a0a0f`, `--accent: #ff6b35`)
- **Responsive** — mobile-friendly repeater table with `hide-mobile` columns
- **Collapsible TG picker** — accordion groups with expand/collapse and live search
- **BM verification badges** — green ✓BM for confirmed, yellow — for unverified
- **Legal disclaimer** with checkbox + 2+ character initials requirement
- **Ad space placeholder** and copyright footer (© 2026 James Dawdy, KQ9I)
- **Logo** displayed at top (`/static/logo.png`)

### Backend Architecture
- `web/app.py` — FastAPI app, UI-agnostic business logic reused from `codeplug/`
- Repeater search uses same `radioid.search_repeaters()` + dedup logic as CLI
- BM verification uses same `brandmeister.build_repeater_index()` as CLI
- Codeplug generation uses same `CodeplugBuilder` + `csv_export.write_zip()` as CLI
- **No per-state max cap in web UI** — user selects repeaters manually, so all found
  repeaters are displayed and the user picks what they want

---

## Major Changes to Python Scripts (April 2025)

### 1. Talk Groups.csv Replaces Digital Contacts for TX Contact Lookups
**Critical discovery:** The DM-32UV CPS has **two separate tables**:
- **Talk Groups.csv** — group-call talkgroups that `TX Contact` references **by name**
- **Digital Contacts.csv** — personal address book for **private calls** (ham operators)

We were generating `digital_contacts.csv` with talkgroup entries, but the CPS looks
in **Talk Groups** for `TX Contact` lookups. Since no `Talk Groups.csv` was generated,
every `TX Contact` defaulted to `"None"`.

**Fix:** `csv_export.py` now generates `talk_groups.csv` (No., Name, ID, Type) with
all referenced talkgroups. `digital_contacts.csv` is no longer included in the ZIP
output (the function still exists but is not called by `write_zip()`).

**Import order:** Talk Groups → RX Group Lists → Channels → Zones

### 2. Per-State `--max` Distribution (CLI only)
**Problem:** Illinois state fallback returned 42+ repeaters, consuming all `--max`
slots before Indiana ever got a look. With `--max 40` and 2 states, Illinois got
everything and Indiana was truncated to zero.

**Fix:** `args.max` is divided across unique states in `main.py`. With 2 states and
`--max 40`, each gets 20 slots. The web UI does not use this cap — user selects
repeaters manually.

### 3. Channel Name Cleanup — T1/T2 Suffix Removed
**Problem:** Channel names included `T1` or `T2` suffix (e.g. `Chicago975 T1 WW`).
This consumed 3 characters of the 16-char limit with redundant information.

**Fix:** Removed timeslot suffix from all channel names in `builder.py`. The timeslot
is stored in the `Time Slot` column; the suffix was display noise. Now:
- `Chicago975 WW` instead of `Chicago975 T1 WW`
- `Chicago975 Local` instead of `Chicago975 T2 Local`

### 4. Automatic Disconnect Channel (TG 4000)
**Problem:** No way to disconnect from reflectors/talkgroups without manually
programming a TG 4000 channel.

**Fix:** Every repeater and hotspot now gets an automatic disconnect channel on
**TS2** unless TG 4000 is already present in the repeater's talkgroup list:
- Repeater: e.g. `"Chicago450 Disc"` (contact: `"BM Disc 4000"`)
- Hotspot: e.g. `"HS Disc 4000"`
- Uses BM catalog name "Disconnect", abbreviated to "Disc" (fits 16-char limit)
- TG 4000 works on both BrandMeister and DMR-MARC networks

### 5. BM API Key from Environment Variable
**Change:** `brandmeister.py` now checks `os.environ.get("BM_API_KEY")` **before**
falling back to `~/.config/dmr-codeplug.json`. This allows the web app to run on
servers without a config file — just set `BM_API_KEY` in the environment.

### 6. Logo and Web Assets
- Added `logo.png` to `web/static/`
- Orange accent color `#ff6b35` matches the logo
- Ad space placeholder with contact email
- Copyright footer: "© 2026 James Dawdy, KQ9I"

---

## Known Issues / TODOs for Claude Code

### 1. ~~Parrot TG Should Be Private Call~~ — **FIXED**
**Resolution:** The BrandMeister Parrot is a diagnostic tool that repeats your
transmission back to you. It **only works as a Private Call** — as a Group Call
it is silently ignored by BM.

**Correct IDs (both must be Private Call):**
- **9990** — Primary worldwide BM Parrot
- **310997** — US regional Parrot (MCC 310 + suffix 997); verified working with
  Private Call in the DM-32UV CPS
- **9998** — Legacy alias kept in TG_ABBREV for compatibility; 9990/310997 preferred

**What changed:**
- `defaults.py`: Added `PRIVATE_CALL_TGS = {9990, 9998, 310997}`
- `builder.py`: Contact creation uses `"Private Call"` for any TG in that set
- `BM_HOTSPOT_TGS`: Replaced the 9998 entry with 9990 and 310997 entries
- `TG_ABBREV`: all three → `"Parrot"` — human-readable, no trailing ID needed
- `builder.py` naming rule: ID is appended only for short abbreviations (≤3 chars,
  e.g. WW, NA, IL); longer abbreviations are self-identifying words and omit the ID

**Import note:** `talk_groups.csv` now shows `Type = Private Call` for these
entries. The CPS must have the Talk Group entry present before importing channels.

### 2. Disconnect Channel May Need TS1 Variant
**Issue:** The automatic disconnect channel is hardcoded to **TS2**. On some
repeaters (especially DMR-MARC), the disconnect may need to be on the same
timeslot as the talkgroup you're trying to disconnect from. Currently if a
repeater has all its TGs on TS1, the disconnect is still on TS2.

**Consideration:** Should the disconnect channel follow the "majority" timeslot
of the repeater? Or should there be two disconnect channels (one per TS)?
BrandMeister convention puts disconnect on TS2, but this may not be universal.

### 3. Digital Contacts.csv — Optional Private-Call Address Book
**Issue:** The current output excludes `digital_contacts.csv` entirely. Some users
may want a personal address book of ham operators for private calls. This should
be an **optional** feature (checkbox in web UI, flag in CLI).

**Implementation idea:** Add a `--contacts` CLI flag and a web UI checkbox. When
enabled, generate `digital_contacts.csv` with known ham operators (possibly from
a user-supplied list or from the DMR ID database).

### 4. Channel Name Collisions on Multi-Repeater Cities
**Issue:** When a city has multiple repeaters on different frequencies, the
disconnect channel names can collide. The current code has a disambiguation
counter (`disc_ch_name2`, `disc_ch_name3`, etc.), but this looks ugly.

**Example:** Two Chicago repeaters (443.450 and 442.100) both get disconnect
channels. The second one becomes `Chicago450 Disc2` or similar.

**Better approach:** Include the frequency suffix in the disconnect channel name
when there are multiple repeaters in the same city, e.g. `Chicago450 Disc` and
`Chicago100 Disc`.

### 5. Web UI Enhancements Needed
- **Loading states:** Some operations (repeater search, generate) have minimal
  loading feedback beyond button text changes.
- **Error handling:** Network errors during repeater search could show more
  helpful messages.
- **Export individual CSVs:** Currently only ZIP download is supported. Some users
  may want individual files.
- **Preview before download:** Show a summary of what will be generated
  (channel count, zone count, etc.) before the user clicks Generate.
- **Save/load configurations:** Let users save their location/network/TG selections
  as a preset (localStorage or server-side).

### 6. TX Contact Field Verification
**Issue:** The exact format the CPS expects for `TX Contact` matching against the
Talk Group list has been verified to work, but we should test edge cases:
- Talkgroup names with special characters (parentheses, slashes)
- Very long talkgroup names that get truncated
- Unicode characters in BM catalog names

### 7. RX Group Lists — Currently All "None"
**Current state:** All channels use `rx_group="None"`. This is correct when
`GroupCall Match = Off` (recommended ham setting). If a user wants to enable
`GroupCall Match = On`, they would need per-repeater RX groups.

**Future enhancement:** Add a CLI flag `--rx-groups` and web UI checkbox to
enable RX group generation. The commented-out code in `builder.py` can be
re-enabled for this.

### 8. Network-Specific Default Talkgroups
**Issue:** The fallback talkgroup lists (`BM_DEFAULTS`, `MARC_DEFAULTS`) are
hardcoded in `defaults.py`. These may not be appropriate for all regions.

**Enhancement:** Allow users to customize default talkgroups per network, or
fetch them from a config file.

---

## Domain Contacts / Resources

- **RadioID API docs**: https://radioid.net/api/
- **BrandMeister API**: https://api.brandmeister.network/v2
- **BM network status**: https://brandmeister.network/?page=lh
- **User callsign**: KQ9I (DMR ID: 3179879), Dyer, Indiana
- **User's hotspot**: 433.550 MHz simplex, registered on BM as KQ9I
