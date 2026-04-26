"""
HearHam.com scraper for DMR repeater talkgroup data.

HearHam (hearham.com) aggregates repeater data including structured talkgroup
lists with timeslot assignments — the data CODEPLUGGER needs but RadioID
often lacks. HearHam allows fetching with a proper User-Agent.

Scraping approach:
  1. Fetch /repeaters/state/{ST} — lists all repeaters with color code (CC)
     for DMR entries; extracts hearham_id, callsign, freq, offset, color_code, city
  2. Fetch /repeaters/{id}/ for each DMR repeater — parses TG list from the
     HTML-encoded description block:
       "2\t9990\tParrott Mode&lt;br&gt;1\t91\tWW&lt;br&gt;..."

Results are stored in dmr_repeaters + dmr_talkgroups tables in repeaters.db.
"""

import re
import time
import sqlite3
import pathlib
import httpx
from typing import Optional

from .repeater_db import get_connection, DB_PATH

_UA = "CODEPLUGGER/1.0 (codeplugger.radio, kq9i@arrl.net)"
_BASE = "https://hearham.com"
_DELAY = 0.6  # seconds between requests — be polite

# US state abbreviation → full name mapping for DB storage
_STATE_ABBREV = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "GU": "Guam", "PR": "Puerto Rico", "VI": "Virgin Islands",
}

# Reverse: full name → abbreviation (for lookups)
_STATE_NAME_TO_ABBREV = {v: k for k, v in _STATE_ABBREV.items()}


# ---------------------------------------------------------------------------
# DB schema for DMR repeater + talkgroup tables
# ---------------------------------------------------------------------------

_DMR_SCHEMA = """
CREATE TABLE IF NOT EXISTS dmr_repeaters (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hearham_id   INTEGER UNIQUE,
    source       TEXT DEFAULT 'hearham',
    callsign     TEXT,
    city         TEXT,
    state        TEXT,
    rx_freq      REAL,
    tx_freq      REAL,
    color_code   INTEGER,
    network      TEXT,
    imported_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dmr_talkgroups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    repeater_id  INTEGER REFERENCES dmr_repeaters(id) ON DELETE CASCADE,
    timeslot     INTEGER,
    tg_id        INTEGER,
    tg_name      TEXT
);

CREATE INDEX IF NOT EXISTS idx_dmr_state    ON dmr_repeaters(state);
CREATE INDEX IF NOT EXISTS idx_dmr_callsign ON dmr_repeaters(callsign);
CREATE INDEX IF NOT EXISTS idx_dmr_freq     ON dmr_repeaters(rx_freq);
CREATE INDEX IF NOT EXISTS idx_dmr_tg_rep   ON dmr_talkgroups(repeater_id);
CREATE INDEX IF NOT EXISTS idx_dmr_tg_id    ON dmr_talkgroups(tg_id);
"""


def _ensure_schema(conn: sqlite3.Connection):
    conn.executescript(_DMR_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get(url: str, client: httpx.Client) -> str:
    r = client.get(url, timeout=20, follow_redirects=True)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# State page parser — returns list of DMR repeater stubs
# ---------------------------------------------------------------------------

_ROW_PATTERN = re.compile(
    r'data-id="(\d+)"[^>]*>.*?'          # hearham_id
    r'href="/repeaters/\d+/">([A-Z0-9/]+)</a></td>\s*'  # callsign
    r'<td>([\d.]+)Mhz</td>\s*'            # rx_freq
    r'<td>([+-]?[\d.]+)Mhz</td>\s*'       # offset
    r'<td>(CC\d+|[\d.]+|)</td>\s*'        # encode (CC = DMR, numeric = CTCSS)
    r'<td>[^<]*</td>\s*'                  # decode
    r'<td>([^<]*)</td>',                  # nearest city
    re.DOTALL
)


def _parse_state_page(html: str, state_abbrev: str) -> list[dict]:
    """Extract DMR repeater rows from a HearHam state listing page."""
    state_name = _STATE_ABBREV.get(state_abbrev.upper(), state_abbrev)
    rows = []
    for m in _ROW_PATTERN.finditer(html):
        hearham_id = int(m.group(1))
        callsign   = m.group(2)
        rx_freq    = float(m.group(3))
        offset     = float(m.group(4))
        encode     = m.group(5).strip()
        city_raw   = m.group(6).strip()

        # Only DMR entries have CC color code
        if not encode.startswith("CC"):
            continue

        # Skip out-of-band freqs (only 2m and 70cm)
        if not (144 <= rx_freq < 148 or 420 <= rx_freq < 450):
            continue

        color_code = int(encode[2:])  # "CC1" → 1
        tx_freq = round(rx_freq + offset, 5)

        # Parse "Chicago, IL USA" → city
        city = city_raw.split(",")[0].strip() if city_raw else ""

        rows.append({
            "hearham_id": hearham_id,
            "callsign":   callsign,
            "city":       city,
            "state":      state_name,
            "rx_freq":    rx_freq,
            "tx_freq":    tx_freq,
            "color_code": color_code,
        })
    return rows


# ---------------------------------------------------------------------------
# Detail page parser — extracts TG list and network
# ---------------------------------------------------------------------------

_TG_ENTRY = re.compile(r'(\d+)\t(\d+)\t([^\&<\t]+?)&lt;br&gt;')
_NETWORK_RE = re.compile(r'Network:\s*(\w[\w\s\-]*?)(?:\n|<)', re.IGNORECASE)
_BM_ID_RE   = re.compile(r'brandmeister\.network/\?page=repeater&(?:amp;)?id=(\d+)')


def _parse_detail_page(html: str) -> dict:
    """Parse TG list and network from a HearHam repeater detail page."""
    talkgroups = []

    # TG data: "slot\ttg_id\tname&lt;br&gt;"
    tg_block = re.search(r'((?:\d+\t\d+\t[^\&<\t]+?&lt;br&gt;)+)', html)
    if tg_block:
        for m in _TG_ENTRY.finditer(tg_block.group()):
            talkgroups.append({
                "timeslot": int(m.group(1)),
                "tg_id":    int(m.group(2)),
                "tg_name":  m.group(3).strip(),
            })

    network = ""
    nm = _NETWORK_RE.search(html)
    if nm:
        network = nm.group(1).strip()

    return {"talkgroups": talkgroups, "network": network}


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _upsert_repeater(conn: sqlite3.Connection, stub: dict, detail: dict) -> int | None:
    """Insert or update a DMR repeater + its talkgroups. Returns row id."""
    try:
        cur = conn.execute(
            """INSERT INTO dmr_repeaters
               (hearham_id, callsign, city, state, rx_freq, tx_freq, color_code, network)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(hearham_id) DO UPDATE SET
                 network = excluded.network,
                 imported_at = datetime('now')""",
            (stub["hearham_id"], stub["callsign"], stub["city"], stub["state"],
             stub["rx_freq"], stub["tx_freq"], stub["color_code"],
             detail.get("network", "")),
        )
        rep_id = cur.lastrowid

        # Replace talkgroups for this repeater
        conn.execute("DELETE FROM dmr_talkgroups WHERE repeater_id = ?", (rep_id,))
        for tg in detail.get("talkgroups", []):
            conn.execute(
                "INSERT INTO dmr_talkgroups (repeater_id, timeslot, tg_id, tg_name) VALUES (?,?,?,?)",
                (rep_id, tg["timeslot"], tg["tg_id"], tg["tg_name"]),
            )
        conn.commit()
        return rep_id
    except Exception:
        conn.rollback()
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def already_imported(conn: sqlite3.Connection, hearham_id: int) -> bool:
    """True if this repeater has TG data already in the DB."""
    row = conn.execute(
        "SELECT id FROM dmr_repeaters WHERE hearham_id = ?", (hearham_id,)
    ).fetchone()
    if not row:
        return False
    tg_count = conn.execute(
        "SELECT COUNT(*) FROM dmr_talkgroups WHERE repeater_id = ?", (row[0],)
    ).fetchone()[0]
    return tg_count > 0


def import_state(
    state_abbrev: str,
    conn: sqlite3.Connection,
    client: httpx.Client,
    verbose: bool = True,
    skip_existing: bool = True,
) -> tuple[int, int]:
    """
    Import DMR repeater TG data for one US state.
    Returns (repeaters_found, tg_records_inserted).
    """
    # Fetch state page
    url = f"{_BASE}/repeaters/state/{state_abbrev.upper()}"
    try:
        html = _get(url, client)
    except Exception as e:
        if verbose:
            print(f"  {state_abbrev}: fetch failed — {e}")
        return 0, 0

    stubs = _parse_state_page(html, state_abbrev)
    if verbose:
        print(f"  {state_abbrev}: {len(stubs)} DMR repeaters on listing page")

    tg_total = 0
    for stub in stubs:
        hid = stub["hearham_id"]
        if skip_existing and already_imported(conn, hid):
            continue

        time.sleep(_DELAY)
        try:
            detail_html = _get(f"{_BASE}/repeaters/{hid}/", client)
        except Exception:
            continue

        detail = _parse_detail_page(detail_html)
        _upsert_repeater(conn, stub, detail)

        tg_count = len(detail.get("talkgroups", []))
        tg_total += tg_count
        if verbose and tg_count > 0:
            print(f"    {stub['callsign']:10s}  {stub['rx_freq']:.4f}  "
                  f"CC{stub['color_code']}  {tg_count} TGs  ({detail.get('network','')})")

    return len(stubs), tg_total


def import_hearham(
    states: Optional[list[str]] = None,
    db_path=None,
    verbose: bool = True,
    skip_existing: bool = True,
) -> dict:
    """
    Import DMR TG data from HearHam for the given states (or all states).

    Args:
        states:        List of 2-letter abbreviations e.g. ['IL', 'IN', 'WI']
                       If None, imports all 50 states + DC + territories.
        db_path:       Override default DB path.
        verbose:       Print progress.
        skip_existing: Skip repeaters already in the DB with TG data.

    Returns:
        {'states': N, 'repeaters': N, 'talkgroups': N}
    """
    target_states = states or list(_STATE_ABBREV.keys())
    conn = get_connection(db_path) if db_path else get_connection()
    _ensure_schema(conn)

    total_reps = 0
    total_tgs  = 0

    with httpx.Client(headers={"User-Agent": _UA}) as client:
        for abbrev in target_states:
            reps, tgs = import_state(
                abbrev, conn, client, verbose=verbose, skip_existing=skip_existing
            )
            total_reps += reps
            total_tgs  += tgs
            time.sleep(_DELAY)

    conn.close()
    return {"states": len(target_states), "repeaters": total_reps, "talkgroups": total_tgs}


# ---------------------------------------------------------------------------
# Query: find TG data for a specific repeater
# ---------------------------------------------------------------------------

def get_talkgroups(
    callsign: str,
    rx_freq: float,
    db_path=None,
    freq_tolerance: float = 0.010,
) -> list[dict]:
    """
    Look up stored talkgroup data for a repeater by callsign + frequency.
    Returns list of {timeslot, tg_id, tg_name, color_code, network}.
    """
    conn = get_connection(db_path) if db_path else get_connection()
    _ensure_schema(conn)

    row = conn.execute(
        """SELECT id, color_code, network FROM dmr_repeaters
           WHERE UPPER(callsign) = UPPER(?)
             AND ABS(rx_freq - ?) < ?""",
        (callsign, rx_freq, freq_tolerance),
    ).fetchone()

    if not row:
        conn.close()
        return []

    rep_id, color_code, network = row["id"], row["color_code"], row["network"]
    tgs = conn.execute(
        "SELECT timeslot, tg_id, tg_name FROM dmr_talkgroups WHERE repeater_id = ? ORDER BY timeslot, tg_id",
        (rep_id,),
    ).fetchall()
    conn.close()

    return [
        {"timeslot": t["timeslot"], "tg_id": t["tg_id"],
         "tg_name": t["tg_name"], "color_code": color_code, "network": network}
        for t in tgs
    ]


def get_dmr_stats(db_path=None) -> dict:
    conn = get_connection(db_path) if db_path else get_connection()
    _ensure_schema(conn)
    reps  = conn.execute("SELECT COUNT(*) FROM dmr_repeaters").fetchone()[0]
    tgs   = conn.execute("SELECT COUNT(*) FROM dmr_talkgroups").fetchone()[0]
    states = conn.execute("SELECT COUNT(DISTINCT state) FROM dmr_repeaters").fetchone()[0]
    conn.close()
    return {"repeaters": reps, "talkgroups": tgs, "states": states}
