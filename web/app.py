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

from codeplug import radioid, csv_export, brandmeister
from codeplug.builder import CodeplugBuilder
from codeplug.models import CodeplugRequest, Repeater
from codeplug.defaults import BM_HOTSPOT_TGS

app = FastAPI(title="CODEPLUGGER")

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


class GenerateRequest(BaseModel):
    dmr_id: int
    callsign: str
    city: str
    state: str
    locations: List[Location]
    networks: List[str]
    selected_repeaters: List[str]  # callsigns to include
    hotspot_tg_ids: List[int]
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


@app.post("/api/search-repeaters")
async def search_repeaters(req: SearchRepeatersRequest):
    # Map network aliases for the API query
    network_aliases = {
        "BrandMeister": ["BrandMeister", "Brandmeister", "BM", "bm"],
        "DMR-MARC": ["DMR-MARC", "MARC"],
        "ChicagoLand-CC": ["ChicagoLand-CC", "Chicagoland-CC"],
        "Tristate": ["Tristate", "TriState"],
    }
    api_networks: list[str] = []
    for n in req.networks:
        api_networks.extend(network_aliases.get(n, [n]))

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
    network_aliases = {
        "BrandMeister": ["BrandMeister", "Brandmeister", "BM", "bm"],
        "DMR-MARC": ["DMR-MARC", "MARC"],
        "ChicagoLand-CC": ["ChicagoLand-CC", "Chicagoland-CC"],
        "Tristate": ["Tristate", "TriState"],
    }
    api_networks: list[str] = []
    for n in req.networks:
        api_networks.extend(network_aliases.get(n, [n]))

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

    warnings = codeplug.validate()
    if warnings:
        # Log warnings but don't block
        print("[generate] warnings:", warnings)

    zip_bytes = csv_export.write_zip(codeplug)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="codeplug_{req.callsign}.zip"'},
    )
