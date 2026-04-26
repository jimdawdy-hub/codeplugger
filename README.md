# CODEPLUGGER

Automatic codeplug generation for the **Baofeng DM-32UV** DMR radio.

Queries [RadioID.net](https://radioid.net) for repeater data, cross-references with the
[BrandMeister API](https://api.brandmeister.network/v2) for network verification, and
produces CSV files ready to import into the DM-32UV CPS programming software.

Available as both a **web UI** and a **command-line tool**.

---

## Web UI (CODEPLUGGER)

![CODEPLUGGER](web/static/logo.png)

```bash
pip install -r requirements.txt
python3.12 -m uvicorn web.app:app --port 8000
# Open http://localhost:8000
```

### User flow

1. Enter your DMR ID — callsign and name are fetched automatically from RadioID
2. Add one or more city/state locations to search
3. Select networks (BrandMeister, DMR-MARC, Tristate, ChicagoLand-CC)
4. Browse found repeaters — check/uncheck to include or exclude; ✓BM badge indicates BrandMeister-verified
5. Pick hotspot talkgroups from a grouped catalog
6. Set TX power and hotspot frequency
7. Agree to the disclaimer and click **Generate & Download** — returns a ZIP of 4 CSV files

---

## CLI

```bash
python3.12 main.py \
  --dmr-id 3179879 \
  --city Chicago --state Illinois \
  --locations "Dyer,Indiana" "Gary,Indiana" "Crown Point,Indiana" \
  --networks BrandMeister DMR-MARC Tristate \
  --max 40 \
  --hotspot --hs-tgs 91 93 3117 3118 9 310 312 \
  --out ./my_codeplug

# Dry run (no files written)
python3.12 main.py --dmr-id 3179879 --city Chicago --state Illinois --dry-run

# List available hotspot talkgroups
python3.12 main.py --dmr-id 3179879 --city Chicago --state Illinois --list-hs-tgs

# Force refresh of BrandMeister caches
python3.12 main.py ... --refresh-bm
```

---

## Output

Four CSV files for import into the DM-32UV CPS — **in this order:**

| # | File | Contents |
|---|------|----------|
| 1 | `talk_groups.csv` | Talkgroup list (TX Contact references these by name) |
| 2 | `rx_group_lists.csv` | Receive group lists (empty — not needed with GroupCall Match Off) |
| 3 | `channels.csv` | One channel per talkgroup per repeater, plus a hotspot zone |
| 4 | `zones.csv` | One zone per repeater; one Hotspot zone |

---

## Setup

**Requirements:** Python 3.12, `httpx`, `fastapi`, `uvicorn`

```bash
pip install -r requirements.txt
```

**BrandMeister API key** (optional but recommended — enables network verification and
official talkgroup names):

```bash
# Store in config file:
echo '{"brandmeister_api_key": "YOUR_KEY_HERE"}' > ~/.config/dmr-codeplug.json

# Or set environment variable (preferred for server deployment):
export BM_API_KEY=YOUR_KEY_HERE
```

BM device and talkgroup lists are cached in `~/.config/` after the first fetch.
Use `--refresh-bm` (CLI) to force a re-download.

---

## Features

- **Multi-location search** — search multiple city/state pairs and deduplicate by callsign
- **BrandMeister verification** — cross-references RadioID data against the BM device registry; corrects mislabeled repeaters automatically
- **Official TG names** — uses BM talkgroup catalog for contact names, falls back to RadioID descriptions
- **Automatic disconnect channel** — every repeater and hotspot zone gets a TG 4000 disconnect channel
- **Parrot support** — TG 9990 and 310997 are correctly set as Private Call (required for BM echo test to work)
- **12-char name limit** — all channel, zone, and talkgroup names are capped at 12 characters for clean radio LCD display

---

## Project structure

```
codeplug/
├── models.py       — Dataclasses: Repeater, Channel, Zone, Codeplug, etc.
├── radioid.py      — RadioID.net API client
├── brandmeister.py — BrandMeister API client + caching
├── defaults.py     — TG abbreviations, network prefixes, fallback TG lists
├── builder.py      — CodeplugBuilder: assembles codeplug from repeater data
└── csv_export.py   — Writes the 4 DM-32UV CSV files

web/
├── app.py          — FastAPI backend
└── static/
    └── index.html  — Single-page dark-themed UI (vanilla JS, no build step)

main.py             — CLI entry point (argparse)
```

---

## Notes

- Tested with the **Baofeng DM-32UV** and its CPS software
- RadioID city search is exact-match only (no radius); the web UI shows all results so you can pick what's relevant
- `GroupCall Match = Off` is recommended for ham use — the radio hears all traffic on matching frequency/color code/timeslot regardless of talkgroup
- See `LESSONS_LEARNED.md` for DMR domain knowledge and CPS quirks
- See `ONBOARDING.md` for full architecture and development history

---

*© 2026 James Dawdy, KQ9I — not affiliated with Baofeng, BrandMeister, or RadioID.net*
