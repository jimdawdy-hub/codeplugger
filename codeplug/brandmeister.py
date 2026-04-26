"""
BrandMeister API client.

Used to verify which repeaters are actually registered on the BrandMeister
network, since RadioID.net's ipsc_network field is self-reported and often
incorrect. Also provides the official BM talkgroup name catalog.

Both device list and talkgroup list are cached indefinitely locally.
Use --refresh-bm to force a fresh download.
"""

import json
import os
import pathlib
import httpx

BM_API_BASE = "https://api.brandmeister.network/v2"
_TIMEOUT = 20.0
_DEVICES_CACHE  = pathlib.Path.home() / ".config" / "dmr-codeplug-bm-devices.json"
_TALKGROUPS_CACHE = pathlib.Path.home() / ".config" / "dmr-codeplug-bm-talkgroups.json"

# BM device status values
STATUS_LINKED = 3   # Both Slots Linked — active repeater
STATUS_DMO    = 4   # Direct Mode / simplex — hotspot or offline


# ---------------------------------------------------------------------------
# Config / auth
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    # Environment variable takes precedence (useful for web deployment)
    env_key = os.environ.get("BM_API_KEY", "")
    if env_key:
        return env_key
    cfg = pathlib.Path.home() / ".config" / "dmr-codeplug.json"
    if cfg.exists():
        data = json.loads(cfg.read_text())
        return data.get("brandmeister_api_key", "")
    return ""


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


# ---------------------------------------------------------------------------
# Device (repeater / hotspot) list
# ---------------------------------------------------------------------------

def _fetch_all_devices(api_key: str) -> list[dict]:
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(f"{BM_API_BASE}/device/", headers=_headers(api_key))
    resp.raise_for_status()
    return resp.json()


def get_all_devices(api_key: str = "", force_refresh: bool = False) -> list[dict]:
    """Return all BM devices, loading from cache unless force_refresh=True."""
    if not api_key:
        api_key = _load_api_key()
    if not api_key:
        return []
    if not force_refresh and _DEVICES_CACHE.exists():
        try:
            return json.loads(_DEVICES_CACHE.read_text())["devices"]
        except Exception:
            pass
    devices = _fetch_all_devices(api_key)
    _DEVICES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _DEVICES_CACHE.write_text(json.dumps({"devices": devices}))
    return devices


def build_repeater_index(devices: list[dict]) -> dict[str, list[dict]]:
    """
    Return callsign → [device records] for actual repeaters only (tx != rx).
    Hotspots (tx == rx) are excluded.
    """
    index: dict[str, list[dict]] = {}
    for d in devices:
        cs = (d.get("callsign") or "").upper().strip()
        if not cs:
            continue
        if d.get("tx", "") == d.get("rx", ""):
            continue  # simplex / hotspot
        index.setdefault(cs, []).append(d)
    return index


def is_on_brandmeister(callsign: str, index: dict[str, list[dict]]) -> bool:
    return callsign.upper() in index


def get_repeater_records(callsign: str, index: dict[str, list[dict]]) -> list[dict]:
    return index.get(callsign.upper(), [])


# ---------------------------------------------------------------------------
# Talkgroup catalog
# ---------------------------------------------------------------------------

def _fetch_all_talkgroups(api_key: str) -> dict[int, str]:
    """Return {tg_id: name} from the BM talkgroup catalog."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(f"{BM_API_BASE}/talkgroup/", headers=_headers(api_key))
    resp.raise_for_status()
    raw = resp.json()  # {str(id): name}
    return {int(k): v for k, v in raw.items()}


def get_all_talkgroups(api_key: str = "", force_refresh: bool = False) -> dict[int, str]:
    """
    Return the BM talkgroup catalog as {tg_id (int): name (str)}.
    Cached indefinitely; use force_refresh=True to re-download.
    """
    if not api_key:
        api_key = _load_api_key()
    if not api_key:
        return {}
    if not force_refresh and _TALKGROUPS_CACHE.exists():
        try:
            raw = json.loads(_TALKGROUPS_CACHE.read_text())
            return {int(k): v for k, v in raw.items()}
        except Exception:
            pass
    tgs = _fetch_all_talkgroups(api_key)
    _TALKGROUPS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TALKGROUPS_CACHE.write_text(json.dumps({str(k): v for k, v in tgs.items()}))
    return tgs


def tg_name(tg_id: int, catalog: dict[int, str]) -> str:
    """Return the official BM name for a talkgroup ID, or empty string if unknown."""
    return catalog.get(tg_id, "")


# ---------------------------------------------------------------------------
# Per-device static talkgroup configuration
# ---------------------------------------------------------------------------

def get_device_talkgroups(device_id: int, api_key: str = "") -> list[dict]:
    """
    Fetch the static talkgroup configuration for a specific BM device.

    Returns list of {talkgroup: int, slot: int, repeaterid: int}.
    Returns [] on any error (device not found, no API key, network error).

    Endpoint: GET /v2/device/{id}/talkgroup/
    """
    if not api_key:
        api_key = _load_api_key()
    if not api_key:
        return []
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(
                f"{BM_API_BASE}/device/{device_id}/talkgroup/",
                headers=_headers(api_key),
            )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json() or []
    except Exception:
        return []
