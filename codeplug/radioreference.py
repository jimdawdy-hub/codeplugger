"""
RadioReference.com SOAP API client.

Used primarily for:
  1. Zip code → city/state/lat/lon lookup (web UI convenience)
  2. County-level amateur radio frequency cross-reference

Important limitations discovered during integration:
  - DMR-specific fields (colorCode, tg, slot) are populated only for commercial/
    public-safety entries, not for ham radio subcategories in the Chicagoland area.
  - RadioID.net remains the authoritative source for DMR repeater metadata.
  - All API calls require the user's own RadioReference Premium account credentials.

Credentials are stored in ~/.config/dmr-codeplug.json:
  {
    "radioreference_app_key": "a476798c-...",
    "radioreference_username": "kc7rcy",
    "radioreference_password": "your_password"
  }

Or via environment variables:
  RR_APP_KEY, RR_USERNAME, RR_PASSWORD
"""

import json
import os
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

SOAP_URL = "http://api.radioreference.com/soap2/"
_TIMEOUT = 20.0
_CONFIG  = pathlib.Path.home() / ".config" / "dmr-codeplug.json"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@dataclass
class RRCredentials:
    app_key:  str
    username: str
    password: str


def load_credentials() -> RRCredentials | None:
    """Load RR credentials from env vars or config file. Returns None if absent."""
    app_key  = os.environ.get("RR_APP_KEY", "")
    username = os.environ.get("RR_USERNAME", "")
    password = os.environ.get("RR_PASSWORD", "")

    if not (app_key and username and password) and _CONFIG.exists():
        try:
            cfg = json.loads(_CONFIG.read_text())
            app_key  = app_key  or cfg.get("radioreference_app_key", "")
            username = username or cfg.get("radioreference_username", "")
            password = password or cfg.get("radioreference_password", "")
        except Exception:
            pass

    if app_key and username and password:
        return RRCredentials(app_key=app_key, username=username, password=password)
    return None


# ---------------------------------------------------------------------------
# SOAP transport
# ---------------------------------------------------------------------------

def _soap_call(method: str, inner_xml: str, creds: RRCredentials) -> ET.Element:
    """Make a SOAP call and return the parsed response root element."""
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope
    xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ns1="http://www.radioreference.com/soap2">
  <SOAP-ENV:Body>
    <ns1:{method}>
      {inner_xml}
      <authInfo>
        <appKey>{creds.app_key}</appKey>
        <username>{creds.username}</username>
        <password>{creds.password}</password>
        <version>latest</version>
      </authInfo>
    </ns1:{method}>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            SOAP_URL,
            content=body.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": method},
        )
    resp.raise_for_status()
    return ET.fromstring(resp.text)


def _text(element: ET.Element, tag: str) -> str:
    el = element.find(tag)
    return (el.text or "").strip() if el is not None else ""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ZipInfo:
    zip_code: str
    city:     str
    lat:      float
    lon:      float
    stid:     int   # RadioReference state ID
    ctid:     int   # RadioReference county ID


@dataclass
class RRFrequency:
    output_freq: float       # MHz (transmit from repeater)
    input_freq:  float       # MHz (0 if simplex or unknown)
    callsign:    str
    alpha_tag:   str
    description: str
    tone:        str
    mode:        str         # "1"=FM, "2"=P25, "8"=D-STAR, "11"=DMR, etc.
    color_code:  str         # DMR color code (often empty for ham entries)
    talkgroup:   str         # DMR talkgroup (often empty)
    slot:        str         # DMR slot (often empty)
    county_id:   int
    subcat_id:   int


@dataclass
class CountyAmateurInfo:
    ctid:       int
    county:     str
    state_id:   int
    subcat_ids: list[int] = field(default_factory=list)  # Amateur Radio subcat IDs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_zip_info(zip_code: str, creds: RRCredentials) -> ZipInfo | None:
    """
    Convert a US zip code to city, state ID, county ID, and coordinates.
    Returns None if the zip is not found.
    """
    try:
        root = _soap_call("getZipcodeInfo", f"<zipcode>{zip_code}</zipcode>", creds)
        ret  = root.find(".//return")
        if ret is None:
            return None
        return ZipInfo(
            zip_code = zip_code,
            city     = _text(ret, "city"),
            lat      = float(_text(ret, "lat") or 0),
            lon      = float(_text(ret, "lon") or 0),
            stid     = int(_text(ret, "stid") or 0),
            ctid     = int(_text(ret, "ctid") or 0),
        )
    except Exception:
        return None


def get_state_id(state_name: str, creds: RRCredentials) -> int | None:
    """
    Look up the RadioReference numeric state ID for a state name.
    Uses a hardcoded map for the 50 states + DC — no API call needed.
    """
    return _STATE_IDS.get(state_name.strip().title())


def get_county_amateur_subcats(ctid: int, creds: RRCredentials) -> CountyAmateurInfo | None:
    """
    Return the Amateur Radio subcategory IDs for a county.
    These can be passed to get_subcat_frequencies().
    """
    try:
        root   = _soap_call("getCountyInfo", f"<ctid>{ctid}</ctid>", creds)
        county = _text(root.find(".//return") or root, "countyName")
        stid   = int(_text(root.find(".//return") or root, "stid") or 0)

        scids: list[int] = []
        for cat in root.findall(".//cats//item"):
            name = _text(cat, "cName").lower()
            if "amateur" in name or "ham" in name:
                for sc in cat.findall(".//subcats//item"):
                    scid_text = _text(sc, "scid")
                    if scid_text:
                        scids.append(int(scid_text))

        return CountyAmateurInfo(ctid=ctid, county=county, state_id=stid, subcat_ids=scids)
    except Exception:
        return None


def get_subcat_frequencies(scid: int, creds: RRCredentials) -> list[RRFrequency]:
    """Return all frequency entries for a given subcategory ID."""
    try:
        root  = _soap_call("getSubcatFreqs", f"<scid>{scid}</scid>", creds)
        freqs = []
        for item in root.findall(".//item"):
            out_str = _text(item, "out")
            in_str  = _text(item, "in")
            if not out_str:
                continue
            try:
                out_freq = float(out_str)
                in_freq  = float(in_str) if in_str else 0.0
            except ValueError:
                continue

            freqs.append(RRFrequency(
                output_freq = out_freq,
                input_freq  = in_freq,
                callsign    = _text(item, "callsign"),
                alpha_tag   = _text(item, "alpha"),
                description = _text(item, "descr"),
                tone        = _text(item, "tone"),
                mode        = _text(item, "mode"),
                color_code  = _text(item, "colorCode"),
                talkgroup   = _text(item, "tg"),
                slot        = _text(item, "slot"),
                county_id   = int(_text(item, "ctid") or 0),
                subcat_id   = scid,
            ))
        return freqs
    except Exception:
        return []


def get_amateur_frequencies_in_county(ctid: int, creds: RRCredentials) -> list[RRFrequency]:
    """
    Convenience: return all amateur radio frequencies in a county by
    discovering Amateur Radio subcategories then fetching each one.
    """
    info = get_county_amateur_subcats(ctid, creds)
    if not info:
        return []
    results: list[RRFrequency] = []
    for scid in info.subcat_ids:
        results.extend(get_subcat_frequencies(scid, creds))
    return results


def verify_user(creds: RRCredentials) -> dict | None:
    """Check that credentials are valid; return user info dict or None."""
    try:
        root = _soap_call("getUserData", "", creds)
        ret  = root.find(".//return")
        if ret is None:
            return None
        return {
            "username":       _text(ret, "username"),
            "sub_expire":     _text(ret, "subExpireDate"),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# State ID lookup table (RadioReference internal IDs)
# ---------------------------------------------------------------------------

_STATE_IDS: dict[str, int] = {
    "Alabama": 1, "Alaska": 2, "Arizona": 3, "Arkansas": 4,
    "California": 5, "Colorado": 6, "Connecticut": 7, "Delaware": 8,
    "Florida": 9, "Georgia": 10, "Hawaii": 11, "Idaho": 12,
    "Illinois": 17, "Indiana": 18, "Iowa": 19, "Kansas": 20,
    "Kentucky": 21, "Louisiana": 22, "Maine": 23, "Maryland": 24,
    "Massachusetts": 25, "Michigan": 26, "Minnesota": 27, "Mississippi": 28,
    "Missouri": 29, "Montana": 30, "Nebraska": 31, "Nevada": 32,
    "New Hampshire": 33, "New Jersey": 34, "New Mexico": 35, "New York": 36,
    "North Carolina": 37, "North Dakota": 38, "Ohio": 39, "Oklahoma": 40,
    "Oregon": 41, "Pennsylvania": 42, "Rhode Island": 43, "South Carolina": 44,
    "South Dakota": 45, "Tennessee": 46, "Texas": 47, "Utah": 48,
    "Vermont": 49, "Virginia": 51, "Washington": 53, "West Virginia": 54,
    "Wisconsin": 55, "Wyoming": 56, "District Of Columbia": 9,
}
