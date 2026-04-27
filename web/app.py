"""
CODEPLUGGER Web UI — FastAPI backend

Serves the single-page UI and provides API endpoints for:
  - DMR ID lookup
  - Repeater search
  - Hotspot talkgroup catalog
  - Codeplug generation (ZIP download)
"""

import os
import sys
from pathlib import Path

# Ensure the project root is on the path so we can import codeplug/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List

from codeplug import radioid, csv_export, brandmeister, radioreference
from codeplug import repeater_db
from codeplug import bm_talkgroups as bm_catalog_mod
from codeplug.builder import CodeplugBuilder
from codeplug.models import Channel, CodeplugRequest, Contact, Repeater, Talkgroup, Zone

# Load TG catalog and name map from CSV once at startup
_BM_CATALOG: dict = bm_catalog_mod.load_catalog()
_BM_TG_NAMES: dict[int, str] = bm_catalog_mod.load_tg_names()

app = FastAPI(title="CODEPLUGGER")

# Reverse map of RadioReference stid → state name (used by zip lookup response)
_STID_TO_NAME: dict[int, str] = {v: k for k, v in radioreference._STATE_IDS.items()}

# RadioID ipsc_network spellings are self-reported and wildly inconsistent.
# Each key is the canonical UI label; the list covers all observed variants.
NETWORK_ALIASES: dict[str, list[str]] = {
    "BrandMeister": ["BrandMeister", "Brandmeister", "BRANDMEISTER", "BM", "bm", "Bm",
                     "BrandMesiter", "Brandmister"],
    "DMR-MARC":     ["DMR-MARC", "MARC",
                     "ChicagoLand-CC", "Chicagoland-CC", "ChicagoLand-CC ",
                     "ChicagoLand", "Chicagoland", "Chicago Land", "chicago land cc ",
                     "Chicagoland C-Bridge", "chi-dmr", "DMR-IL"],
    "Tristate":     ["Tristate", "TriState", "TriStateDMR", "TriSTateDMR"],
    "ChicagoLand-CC": [],  # folded into DMR-MARC above; kept for UI compat
}


def _expand_networks(selected: list[str]) -> list[str]:
    """Expand UI network names to all RadioID ipsc_network variants."""
    out: list[str] = []
    for n in selected:
        out.extend(NETWORK_ALIASES.get(n, [n]))
    return out

# Serve static files (the single-page UI)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LookupUserRequest(BaseModel):
    dmr_id: int


class LookupUserResponse(BaseModel):
    dmr_id: int
    callsign: str
    name: str
    city: str
    state: str


class Location(BaseModel):
    city: str
    state: str


class SearchRepeatersRequest(BaseModel):
    locations: List[Location]
    networks: List[str] = ["BrandMeister", "DMR-MARC"]
    country: str = "United States"


class RepeaterInfo(BaseModel):
    callsign: str
    city: str
    state: str
    rx_freq: float
    tx_freq: float
    color_code: int
    network: str
    timeslot_summary: str
    bm_verified: bool
    talkgroup_count: int
    selected: bool = True


class SearchRepeatersResponse(BaseModel):
    repeaters: List[RepeaterInfo]


class ManualTG(BaseModel):
    name: str    # display name, already validated to ≤12 chars by the UI
    tg_id: int


class AnalogRepeaterInfo(BaseModel):
    name:         str
    callsign:     str
    rx_freq:      float
    tx_freq:      float
    ctcss_encode: str
    county_name:  str
    state:        str = ""
    selected:     bool = True


class SearchAnalogRequest(BaseModel):
    locations: List[Location]


class AnalogRepeaterInput(BaseModel):
    name:         str
    callsign:     str
    rx_freq:      float
    tx_freq:      float
    ctcss_encode: str
    state:        str = ""


class GenerateRequest(BaseModel):
    dmr_id: int
    callsign: str
    city: str
    state: str
    locations: List[Location]
    networks: List[str]
    selected_repeaters: List[str]  # callsigns to include
    hotspot_tg_ids: List[int]
    manual_hotspot_tgs: List[ManualTG] = []
    selected_analog: List[AnalogRepeaterInput] = []
    hotspot_freq: float = 433.550
    power: str = "High"
    country: str = "United States"
    initials: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/hotspot-talkgroups")
async def hotspot_talkgroups():
    """Return the BM hotspot talkgroup catalog grouped by category (from CSV)."""
    return {
        "groups": _BM_CATALOG,
        "category_order": bm_catalog_mod.CATEGORY_ORDER,
    }


@app.post("/api/lookup-user")
async def lookup_user(req: LookupUserRequest):
    user = radioid.lookup_user(req.dmr_id)
    if user is None:
        raise HTTPException(status_code=404, detail="DMR ID not found")
    return LookupUserResponse(
        dmr_id=req.dmr_id,
        callsign=user.get("callsign", ""),
        name=f"{user.get('fname', '')} {user.get('name', '')}".strip(),
        city=user.get("city", ""),
        state=user.get("state", ""),
    )


@app.get("/api/lookup-zip/{zip_code}")
async def lookup_zip(zip_code: str):
    """Convert a US zip code to city, state, and coordinates."""
    creds = radioreference.load_credentials()
    if not creds:
        raise HTTPException(status_code=503, detail="RadioReference credentials not configured")
    info = radioreference.get_zip_info(zip_code, creds)
    if not info:
        raise HTTPException(status_code=404, detail=f"Zip code {zip_code} not found")
    # Map RR state ID back to state name
    state_name = _STID_TO_NAME.get(info.stid, "")
    return {"zip": zip_code, "city": info.city, "state": state_name,
            "lat": info.lat, "lon": info.lon, "stid": info.stid, "ctid": info.ctid}


def _city_abbrev(city: str, max_len: int = 12) -> str:
    """Strip punctuation/spaces from a city name, truncate to max_len."""
    import re
    return re.sub(r"['\-\. ]", "", city)[:max_len]


@app.post("/api/search-analog")
async def search_analog(req: SearchAnalogRequest):
    """
    Return analog FM amateur repeaters for the given locations.

    Sources (merged and deduplicated):
      1. Local database (KML/PDF imports — broadest coverage)
      2. RadioReference API county-level search (real-time, where county ID is known)

    Channel names use city name (like DMR repeaters), with a 3-digit frequency
    suffix appended when multiple repeaters share the same city name.
    """
    # Collect raw entries before name assignment
    seen: set[tuple] = set()
    raw: list[dict] = []  # {city, state, callsign, rx, tx, ctcss, region}

    def _add(city: str, state: str, callsign: str, rx: float, tx: float, ctcss: str, region: str):
        # Deduplicate by callsign+freq (catches same repeater in DB and RR).
        # Fall back to freq+state when callsign is unknown, so same-frequency
        # repeaters in different states are NOT collapsed into one.
        if callsign:
            key: tuple = (callsign.upper(), round(rx, 4))
        else:
            key = (round(rx, 4), round(tx, 4), state)
        if key in seen:
            return
        seen.add(key)
        raw.append({"city": city.split(",")[0].strip(), "state": state,
                    "callsign": callsign, "rx": rx, "tx": tx,
                    "ctcss": ctcss or "None", "region": region})

    # --- Source 1: local database ---
    try:
        conn = repeater_db.get_connection()
        unique_states = list(dict.fromkeys(loc.state for loc in req.locations))
        for st in unique_states:
            db_rows = repeater_db.search_analog(conn, state=st)
            for r in db_rows:
                _add(r.city or st, r.state or st, r.callsign, r.rx_freq, r.tx_freq,
                     r.ctcss_encode or "None", r.city or st)
        conn.close()
    except Exception as e:
        print(f"[search-analog] DB error: {e}")

    # --- Source 2: RadioReference API ---
    creds = radioreference.load_credentials()
    if creds:
        try:
            unique_states_rr = list(dict.fromkeys(loc.state for loc in req.locations if loc.state))
            for st in unique_states_rr:
                rr_repeaters = radioreference.search_analog_repeaters(
                    [("", st)], creds
                )
                for r in rr_repeaters:
                    _add(r.county_name or st, st, r.callsign,
                         r.rx_freq, r.tx_freq, r.ctcss_encode or "None", r.county_name)
        except Exception as e:
            print(f"[search-analog] RadioReference error: {e}")

    raw.sort(key=lambda r: (r["state"], r["rx"]))

    # Assign names: city abbreviation, with freq suffix when city has duplicates
    city_counts: dict[str, int] = {}
    for e in raw:
        city_counts[e["city"]] = city_counts.get(e["city"], 0) + 1

    used_names: set[str] = set()
    results: list[AnalogRepeaterInfo] = []
    for e in raw:
        abbrev = _city_abbrev(e["city"])
        if city_counts[e["city"]] > 1:
            freq_suffix = f"{round(e['rx'] % 1 * 1000) % 1000:03d}"
            base = (abbrev[: 12 - len(freq_suffix)] + freq_suffix)
        else:
            base = abbrev[:12]

        # Final collision guard (shouldn't normally fire)
        name, counter = base, 2
        while name in used_names:
            name = f"{base[:12 - len(str(counter))]}{counter}"
            counter += 1
        used_names.add(name)

        results.append(AnalogRepeaterInfo(
            name=name, callsign=e["callsign"], rx_freq=e["rx"], tx_freq=e["tx"],
            ctcss_encode=e["ctcss"], county_name=e["region"], state=e["state"], selected=True,
        ))

    return {"repeaters": results}


@app.post("/api/search-repeaters")
async def search_repeaters(req: SearchRepeatersRequest):
    api_networks = _expand_networks(req.networks)

    # Search by state only — one query per unique state, user selects from results
    # Deduplicate by (callsign, rx_freq) — same trustee can have multiple repeaters
    seen: set[tuple] = set()
    all_repeaters: list[Repeater] = []
    unique_states = list(dict.fromkeys(loc.state for loc in req.locations if loc.state))

    for state in unique_states:
        found = radioid.search_repeaters(
            state=state, country=req.country, networks=api_networks
        )
        for r in found:
            key = (r.callsign.upper(), round(r.rx_freq, 4))
            if key not in seen:
                all_repeaters.append(r)
                seen.add(key)

    # BM verification
    bm_index: dict = {}
    bm_key = brandmeister._load_api_key()
    if bm_key:
        devices = brandmeister.get_all_devices(bm_key)
        if devices:
            bm_index = brandmeister.build_repeater_index(devices)

    # Build response
    result: list[RepeaterInfo] = []
    for r in sorted(all_repeaters, key=lambda x: (x.state, x.city, x.rx_freq)):
        ts_summary = ", ".join(
            f"TS{tg.timeslot}:{tg.id}"
            for tg in r.talkgroups[:5]
        )
        if len(r.talkgroups) > 5:
            ts_summary += f" (+{len(r.talkgroups) - 5} more)"
        if not ts_summary:
            ts_summary = "defaults"

        result.append(RepeaterInfo(
            callsign=r.callsign,
            city=r.city,
            state=r.state,
            rx_freq=r.rx_freq,
            tx_freq=r.tx_freq,
            color_code=r.color_code,
            network=r.network,
            timeslot_summary=ts_summary,
            bm_verified=brandmeister.is_on_brandmeister(r.callsign, bm_index),
            talkgroup_count=len(r.talkgroups),
            selected=True,
        ))

    return {"repeaters": result}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    if not req.initials or len(req.initials.strip()) < 2:
        raise HTTPException(status_code=400, detail="Initials required")

    # Re-fetch repeaters by state only (mirrors search endpoint)
    api_networks = _expand_networks(req.networks)

    seen: set[tuple] = set()
    all_repeaters: list[Repeater] = []
    unique_states = list(dict.fromkeys(loc.state for loc in req.locations if loc.state))

    for state in unique_states:
        found = radioid.search_repeaters(
            state=state, country=req.country, networks=api_networks
        )
        for r in found:
            key = (r.callsign.upper(), round(r.rx_freq, 4))
            if key not in seen:
                all_repeaters.append(r)
                seen.add(key)

    # Filter to selected
    # selected_repeaters is "CALLSIGN:freq" keys (e.g. "N9IAA:444.35000")
    selected_set = {s.upper() for s in req.selected_repeaters}
    repeaters = [
        r for r in all_repeaters
        if f"{r.callsign.upper()}:{r.rx_freq:.5f}" in selected_set
    ]

    if not repeaters:
        raise HTTPException(status_code=400, detail="No repeaters selected")

    # BM data — use CSV catalog as primary TG name source; API for device verification
    bm_talkgroups: dict[int, str] = dict(_BM_TG_NAMES)  # CSV names
    bm_key = brandmeister._load_api_key()
    bm_index: dict = {}
    if bm_key:
        # Merge API names (API wins for any overlap, but CSV covers most)
        api_names = brandmeister.get_all_talkgroups(bm_key)
        bm_talkgroups.update(api_names)
        devices = brandmeister.get_all_devices(bm_key)
        if devices:
            bm_index = brandmeister.build_repeater_index(devices)

    # Enrich BM-verified repeaters that RadioID returned with no talkgroup data.
    # GET /v2/device/{id}/talkgroup/ returns the static TG config the sysop entered.
    if bm_key and bm_index:
        for rep in repeaters:
            if rep.talkgroups:
                continue  # RadioID already gave us TG data — keep it
            bm_records = brandmeister.get_repeater_records(rep.callsign, bm_index)
            for bm_dev in bm_records:
                dev_id = bm_dev.get("id")
                if not dev_id:
                    continue
                raw_tgs = brandmeister.get_device_talkgroups(dev_id, bm_key)
                if raw_tgs:
                    rep.talkgroups = [
                        Talkgroup(
                            id=int(entry["talkgroup"]),
                            timeslot=int(entry.get("slot", 2)),
                            description=bm_talkgroups.get(int(entry["talkgroup"]), ""),
                        )
                        for entry in raw_tgs
                        if entry.get("talkgroup")
                    ]
                    break  # use first device record that has TG data

    # Build request
    primary = req.locations[0] if req.locations else Location(city="", state="")
    cp_req = CodeplugRequest(
        dmr_id=req.dmr_id,
        callsign=req.callsign,
        city=primary.city,
        state=primary.state,
        country=req.country,
        networks=req.networks,
        max_repeaters=9999,  # web UI handles selection
        tx_power=req.power,
        include_hotspot=bool(req.hotspot_tg_ids),
        hotspot_freq=req.hotspot_freq,
        hotspot_talkgroup_ids=req.hotspot_tg_ids,
    )

    builder = CodeplugBuilder(cp_req, bm_talkgroups=bm_talkgroups)
    codeplug = builder.build(repeaters)

    # --- Reorganize hotspot into per-category zones ---
    # The builder created a single "Hotspot" zone; replace it with category zones.
    _tg_category: dict[int, str] = {
        tg["id"]: cat
        for cat, tgs in _BM_CATALOG.items()
        for tg in tgs
    }
    _contact_to_tgid: dict[str, int] = {c.name: c.dmr_id for c in codeplug.contacts}

    hotspot_zone = next((z for z in codeplug.zones if z.name == "Hotspot"), None)
    if hotspot_zone:
        codeplug.zones.remove(hotspot_zone)
        # Group channel names by category, preserving order
        hs_cat_channels: dict[str, list[str]] = {}
        for ch_name in hotspot_zone.channels:
            ch = next((c for c in codeplug.channels if c.name == ch_name), None)
            if ch:
                tg_id = _contact_to_tgid.get(ch.tx_contact)
                cat = _tg_category.get(tg_id, "Wide Area") if tg_id else "Wide Area"
                hs_cat_channels.setdefault(cat, []).append(ch_name)
        # Emit zones in category order, splitting at 64
        for cat in bm_catalog_mod.CATEGORY_ORDER:
            ch_names = hs_cat_channels.get(cat, [])
            if not ch_names:
                continue
            base = bm_catalog_mod.CATEGORY_ZONE_NAMES.get(cat, f"HS {cat}")[:16]
            for page_idx, offset in enumerate(range(0, len(ch_names), 64)):
                suffix = "" if page_idx == 0 else str(page_idx + 1)
                codeplug.zones.append(Zone(
                    name=(base + suffix)[:16],
                    channels=ch_names[offset:offset + 64],
                ))

    # Inject manually entered hotspot talkgroups into "HS Manual TGs"
    if req.manual_hotspot_tgs:
        existing_contact_names = {c.name for c in codeplug.contacts}
        existing_channel_names = {c.name for c in codeplug.channels}
        new_channels: list[str] = []

        for mtg in req.manual_hotspot_tgs:
            name = mtg.name.strip()[:12]
            if not name or mtg.tg_id < 1:
                continue
            if name not in existing_contact_names:
                codeplug.contacts.append(Contact(
                    name=name, dmr_id=mtg.tg_id, call_type="Group Call"
                ))
                existing_contact_names.add(name)
            if name not in existing_channel_names:
                codeplug.channels.append(Channel(
                    name=name,
                    channel_type="Digital",
                    rx_freq=req.hotspot_freq,
                    tx_freq=req.hotspot_freq,
                    color_code=1,
                    timeslot=2,
                    tx_contact=name,
                    rx_group="None",
                    power="Low",
                    tx_admit="Always",
                    dmr_id=req.callsign,
                ))
                existing_channel_names.add(name)
                new_channels.append(name)

        if new_channels:
            for page_idx, offset in enumerate(range(0, len(new_channels), 64)):
                suffix = "" if page_idx == 0 else str(page_idx + 1)
                codeplug.zones.append(Zone(
                    name=f"HS Manual TGs{suffix}"[:16],
                    channels=new_channels[offset:offset + 64],
                ))

    # Inject selected analog repeaters into per-state/band zones
    # Zone naming: "{ST} 2m Analog", "{ST} 70cm Analog"; overflow: "{ST} 2m Analog2"
    if req.selected_analog:
        existing_channel_names = {c.name for c in codeplug.channels}
        # Group channel names by (state_abbrev, band)
        zone_channels: dict[tuple[str, str], list[str]] = {}

        def _state_abbrev(state_full: str) -> str:
            abbrevs = {
                "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR",
                "California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE",
                "Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID",
                "Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS",
                "Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD",
                "Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS",
                "Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV",
                "New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY",
                "North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK",
                "Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC",
                "South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT",
                "Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV",
                "Wisconsin":"WI","Wyoming":"WY","District of Columbia":"DC",
            }
            return abbrevs.get(state_full, state_full[:2].upper())

        for ar in req.selected_analog:
            name = ar.name.strip()[:12]
            if not name:
                continue
            base, counter = name, 2
            while name in existing_channel_names:
                name = f"{base[:12 - len(str(counter))]}{counter}"
                counter += 1
            existing_channel_names.add(name)
            codeplug.channels.append(Channel(
                name         = name,
                channel_type = "Analog",
                rx_freq      = ar.rx_freq,
                tx_freq      = ar.tx_freq,
                color_code   = 0,
                timeslot     = 1,
                tx_contact   = "None",
                rx_group     = "None",
                power        = req.power,
                dmr_id       = req.callsign,
                ctcss_decode = "None",
                ctcss_encode = ar.ctcss_encode,
            ))
            st = _state_abbrev(ar.state) if ar.state else "XX"
            band = "2m" if 144 <= ar.rx_freq < 148 else "70cm"
            zone_channels.setdefault((st, band), []).append(name)

        # Build zones, splitting into pages of 64
        for (st, band), ch_names in sorted(zone_channels.items()):
            for page_idx, offset in enumerate(range(0, len(ch_names), 64)):
                page = ch_names[offset:offset + 64]
                suffix = "" if page_idx == 0 else str(page_idx + 1)
                zone_name = f"{st} {band} Analog{suffix}"
                codeplug.zones.append(Zone(name=zone_name, channels=page))

    warnings = codeplug.validate()
    if warnings:
        print("[generate] warnings:", warnings)

    zip_bytes = csv_export.write_zip(codeplug)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="codeplug_{req.callsign}.zip"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
