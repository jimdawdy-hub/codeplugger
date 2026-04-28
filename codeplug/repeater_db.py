"""
Local repeater database — SQLite-backed, multi-source.

Data flows in from:
  - KML/KMZ imports (Google Earth Ham Repeaters project — RepeaterBook data)
  - PDF imports (Iowa RC, MN RC, WPRC, Oregon, Rochester area, etc.)

Queried by state for analog repeater search.
"""

import sqlite3
import pathlib
from dataclasses import dataclass
from typing import Optional

from .paths import ROOT
DB_PATH = ROOT / "data" / "repeaters.db"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repeaters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,        -- e.g. 'pdf:iowa_rc', 'kml:illinois'
    callsign      TEXT,
    city          TEXT,
    state         TEXT,
    country       TEXT    DEFAULT 'United States',
    rx_freq       REAL    NOT NULL,        -- MHz — what user receives (repeater TX)
    tx_freq       REAL    NOT NULL,        -- MHz — what user transmits (repeater RX)
    ctcss_encode  TEXT,                   -- PL tone as string e.g. '131.8', or NULL
    mode          TEXT    DEFAULT 'FM',   -- FM, DMR, Fusion, P25, DSTAR, APRS
    notes         TEXT,
    imported_at   TEXT    DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repeater_key
    ON repeaters(rx_freq, tx_freq, COALESCE(callsign,''), COALESCE(state,''));

CREATE INDEX IF NOT EXISTS idx_state       ON repeaters(state);
CREATE INDEX IF NOT EXISTS idx_mode        ON repeaters(mode);
CREATE INDEX IF NOT EXISTS idx_rx_freq     ON repeaters(rx_freq);
"""


def get_connection(db_path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def insert_repeater(
    conn: sqlite3.Connection,
    *,
    source: str,
    callsign: str = "",
    city: str = "",
    state: str = "",
    country: str = "United States",
    rx_freq: float,
    tx_freq: float,
    ctcss_encode: Optional[str] = None,
    mode: str = "FM",
    notes: str = "",
) -> bool:
    """Insert a repeater; silently skip duplicates. Returns True if inserted."""
    try:
        conn.execute(
            """INSERT OR IGNORE INTO repeaters
               (source, callsign, city, state, country, rx_freq, tx_freq,
                ctcss_encode, mode, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source, callsign or "", city or "", state or "", country,
             rx_freq, tx_freq, ctcss_encode, mode, notes or ""),
        )
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False


def bulk_insert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert many rows; return number actually inserted."""
    inserted = 0
    for r in rows:
        if insert_repeater(conn, **r):
            inserted += 1
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@dataclass
class RepeaterRecord:
    id:           int
    source:       str
    callsign:     str
    city:         str
    state:        str
    country:      str
    rx_freq:      float
    tx_freq:      float
    ctcss_encode: Optional[str]
    mode:         str
    notes:        str


def _row_to_record(row: sqlite3.Row) -> RepeaterRecord:
    return RepeaterRecord(
        id           = row["id"],
        source       = row["source"],
        callsign     = row["callsign"],
        city         = row["city"],
        state        = row["state"],
        country      = row["country"],
        rx_freq      = row["rx_freq"],
        tx_freq      = row["tx_freq"],
        ctcss_encode = row["ctcss_encode"],
        mode         = row["mode"],
        notes        = row["notes"],
    )


def search_analog(
    conn: sqlite3.Connection,
    *,
    state: Optional[str] = None,
    city: Optional[str] = None,
    min_freq: float = 144.0,
    max_freq: float = 450.0,
) -> list[RepeaterRecord]:
    """Return FM repeaters matching state/city, in 2m/70cm bands only."""
    clauses = [
        "mode = 'FM'",
        "rx_freq >= ?",
        "rx_freq <= ?",
        "NOT (rx_freq >= 148 AND rx_freq < 420)",  # exclude 222 MHz band
    ]
    params: list = [min_freq, max_freq]

    if state:
        clauses.append("LOWER(state) = LOWER(?)")
        params.append(state)
    if city:
        clauses.append("LOWER(city) LIKE LOWER(?)")
        params.append(f"%{city}%")

    sql = f"SELECT * FROM repeaters WHERE {' AND '.join(clauses)} ORDER BY state, city, rx_freq"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(r) for r in rows]


def get_stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT mode, COUNT(*) as cnt FROM repeaters GROUP BY mode ORDER BY cnt DESC"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM repeaters").fetchone()[0]
    states = conn.execute(
        "SELECT COUNT(DISTINCT state) FROM repeaters WHERE state != ''"
    ).fetchone()[0]
    sources = conn.execute(
        "SELECT COUNT(DISTINCT source) FROM repeaters"
    ).fetchone()[0]
    return {
        "total": total,
        "states": states,
        "sources": sources,
        "by_mode": {r["mode"]: r["cnt"] for r in rows},
    }


def list_states(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT state FROM repeaters WHERE state != '' ORDER BY state"
    ).fetchall()
    return [r["state"] for r in rows]
