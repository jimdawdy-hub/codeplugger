"""
RadioID.net REST API client.

Docs: https://radioid.net/api/
"""

import httpx
from .models import Repeater, Talkgroup


BASE_URL = "https://radioid.net/api"
_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict) -> dict:
    url = f"{BASE_URL}{path}"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def _paginate(path: str, params: dict) -> list[dict]:
    """Fetch all pages for a paginated endpoint (max 200 per page)."""
    params = dict(params)
    params["per_page"] = 200
    params["page"] = 1
    results = []
    while True:
        data = _get(path, params)
        results.extend(data.get("results", []))
        if data.get("page", 1) >= data.get("pages", 1):
            break
        params["page"] += 1
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_user(dmr_id: int) -> dict | None:
    """
    Return user record for the given DMR ID, or None if not found.

    Returned keys include: id, callsign, fname, city, state, country,
    has_valid_callsign.
    """
    data = _get("/dmr/user/", {"id": dmr_id})
    results = data.get("results", [])
    return results[0] if results else None


def search_repeaters(
    *,
    state: str = "",
    city: str = "",
    country: str = "United States",
    networks: list[str] | None = None,
) -> list[Repeater]:
    """
    Return a list of on-air DMR repeaters matching the given filters.

    RadioID does not have a radius search, so we filter by state/city and
    optionally restrict to specific networks.  The caller applies further
    distance-based sorting if needed.
    """
    params: dict = {"country": country}
    if state:
        params["state"] = state
    if city:
        params["city"] = city

    raw_list = _paginate("/dmr/repeater/", params)

    # Filter to on-air and requested networks
    network_set = {n.lower() for n in (networks or [])} if networks else None

    repeaters: list[Repeater] = []
    for r in raw_list:
        if r.get("status", "").lower() != "on-air":
            continue
        if network_set:
            net = r.get("ipsc_network", "")
            if net.lower() not in network_set:
                continue

        repeaters.append(_parse_repeater(r))

    return repeaters


def get_repeater_by_id(locator_id: int) -> Repeater | None:
    """Return a single repeater by its RadioID locator ID."""
    data = _get("/dmr/repeater/", {"id": locator_id})
    results = data.get("results", [])
    return _parse_repeater(results[0]) if results else None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_repeater(r: dict) -> Repeater:
    talkgroups = [
        Talkgroup(
            id=int(tg["talkgroup"]),
            timeslot=int(tg.get("timeslot", 1)),
            description=tg.get("description", ""),
        )
        for tg in r.get("talkgroups", [])
        if tg.get("talkgroup") is not None
    ]

    freq = float(r.get("frequency", 0))
    offset_str = str(r.get("offset", "+5.000")).strip()

    # Parse offset: "+5.000" or "-0.600" etc.
    try:
        offset = float(offset_str)
    except ValueError:
        offset = 5.0

    return Repeater(
        callsign=r.get("callsign", ""),
        city=r.get("city", ""),
        state=r.get("state", ""),
        country=r.get("country", ""),
        rx_freq=freq,
        offset=offset,
        color_code=int(r.get("color_code", 1)),
        network=r.get("ipsc_network", ""),
        status=r.get("status", ""),
        talkgroups=talkgroups,
        locator=r.get("locator"),
    )
