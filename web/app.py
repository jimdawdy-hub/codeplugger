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
from codeplug.builder import CodeplugBuilder
from codeplug.models import Channel, CodeplugRequest, Contact, Repeater, Zone
from codeplug.defaults import BM_HOTSPOT_TGS

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
    selected:     bool = True


class SearchAnalogRequest(BaseModel):
    locations: List[Location]


class AnalogRepeaterInput(BaseModel):
    name:         str
    callsign:     str
    rx_freq:      float
    tx_freq:      float
    ctcss_encode: str


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
    """Return the BM hotspot talkgroup catalog grouped by category."""
    groups: dict[str, list[dict]] = {}
    for tg in BM_HOTSPOT_TGS:
        g = tg["group"]
        groups.setdefault(g, []).append({"id": tg["id"], "name": tg["name"]})
    return {"groups": groups}


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


@app.post("/api/search-analog")
async def search_analog(req: SearchAnalogRequest):
    """Return analog FM amateur repeaters for the given locations via RadioReference."""
    creds = radioreference.load_credentials()
    if not creds:
        raise HTTPException(status_code=503, detail="RadioReference credentials not configured")

    locations = [(loc.city, loc.state) for loc in req.locations]
    repeaters = radioreference.search_analog_repeaters(locations, creds)

    if not repeaters:
        # Return empty list with a note if no county mapping found
        unknown = [
            f"{loc.city}, {loc.state}"
            for loc in req.locations
            if radioreference.get_ctid_for_location(loc.city, loc.state, creds) is None
        ]
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=f"No county data for: {', '.join(unknown)}. Try adding locations via zip code lookup."
            )

    return {"repeaters": [
        AnalogRepeaterInfo(
            name         = r.name,
            callsign     = r.callsign,
            rx_freq      = r.rx_freq,
            tx_freq      = r.tx_freq,
            ctcss_encode = r.ctcss_encode,
            county_name  = r.county_name,
            selected     = True,
        )
        for r in repeaters
    ]}


@app.post("/api/search-repeaters")
async def search_repeaters(req: SearchRepeatersRequest):
    api_networks = _expand_networks(req.networks)

    # Search repeaters per location (no per-state caps in web UI — user selects)
    seen_callsigns: set[str] = set()
    state_searched: set[str] = set()
    all_repeaters: list[Repeater] = []

    for loc in req.locations:
        city, state = loc.city, loc.state
        found = radioid.search_repeaters(
            state=state, city=city, country=req.country, networks=api_networks
        )
        # State fallback when city returns < 3
        if len(found) < 3 and state not in state_searched:
            state_found = radioid.search_repeaters(
                state=state, country=req.country, networks=api_networks
            )
            state_searched.add(state)
            for r in state_found:
                if r.callsign not in seen_callsigns:
                    found.append(r)
        for r in found:
            if r.callsign not in seen_callsigns:
                all_repeaters.append(r)
                seen_callsigns.add(r.callsign)

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

    # Re-fetch repeaters (same logic as search)
    api_networks = _expand_networks(req.networks)

    seen_callsigns: set[str] = set()
    state_searched: set[str] = set()
    all_repeaters: list[Repeater] = []

    for loc in req.locations:
        found = radioid.search_repeaters(
            state=loc.state, city=loc.city, country=req.country, networks=api_networks
        )
        if len(found) < 3 and loc.state not in state_searched:
            state_found = radioid.search_repeaters(
                state=loc.state, country=req.country, networks=api_networks
            )
            state_searched.add(loc.state)
            for r in state_found:
                if r.callsign not in seen_callsigns:
                    found.append(r)
        for r in found:
            if r.callsign not in seen_callsigns:
                all_repeaters.append(r)
                seen_callsigns.add(r.callsign)

    # Filter to selected
    selected_set = {c.upper() for c in req.selected_repeaters}
    repeaters = [r for r in all_repeaters if r.callsign.upper() in selected_set]

    if not repeaters:
        raise HTTPException(status_code=400, detail="No repeaters selected")

    # BM data
    bm_talkgroups: dict[int, str] = {}
    bm_key = brandmeister._load_api_key()
    if bm_key:
        bm_talkgroups = brandmeister.get_all_talkgroups(bm_key)

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

    # Inject manually entered hotspot talkgroups
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

        # Add to the Hotspot zone, or create it if none exists yet
        if new_channels:
            hotspot_zone = next((z for z in codeplug.zones if z.name == "Hotspot"), None)
            if hotspot_zone:
                hotspot_zone.channels.extend(new_channels)
            else:
                codeplug.zones.append(Zone(name="Hotspot", channels=new_channels))

    # Inject selected analog repeaters into an "Analog" zone
    if req.selected_analog:
        existing_channel_names = {c.name for c in codeplug.channels}
        analog_channel_names: list[str] = []
        for ar in req.selected_analog:
            name = ar.name.strip()[:12]
            if not name:
                continue
            # Disambiguate duplicate names
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
            analog_channel_names.append(name)
        if analog_channel_names:
            codeplug.zones.append(Zone(name="Analog", channels=analog_channel_names[:64]))

    warnings = codeplug.validate()
    if warnings:
        print("[generate] warnings:", warnings)

    zip_bytes = csv_export.write_zip(codeplug)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="codeplug_{req.callsign}.zip"'},
    )
