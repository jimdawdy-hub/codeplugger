"""
PDF repeater directory importer.

Supports multiple regional directory formats:
  - Iowa Repeater Council   (City Output Call Access Mode Notes)
  - Minnesota RC            (CITY REGION Output Call Club Access Notes Date)
  - Western PA RC (WPRC)   (Output Input Access Location Grid Call Trustee Sponsor Notes)
  - Oregon                 (Freq± PL Location County Callsign Status)
  - Rochester area NY       (CH RECEIVE TRANSMIT TONE TRUSTEE LOCATION COMMENTS)

Each parser returns a list of dicts compatible with repeater_db.insert_repeater().
"""

import re
import pathlib
import pdfplumber

from .repeater_db import get_connection, bulk_insert


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Modes that mean this is a digital/non-FM repeater — skip for analog DB
_DIGITAL_MODES = {"dmr", "d-star", "dstar", "p25", "p-25", "fusion", "nxdn",
                  "ntsc", "aprs", "wires", "c4fm", "m17", "pkt", "packet",
                  "d star", "system fusion"}

# Standard 2m/70cm offsets
def _standard_tx(rx_freq: float, sign: str) -> float:
    """
    Calculate TX freq from output (RX) and sign.
    sign '+' → tx = rx + offset, '-' → tx = rx - offset.
    """
    if 144 <= rx_freq < 148:
        offset = 0.600
    elif 420 <= rx_freq < 450:
        offset = 5.000
    else:
        return 0.0
    return round(rx_freq + (offset if sign == "+" else -offset), 5)


def _is_digital(text: str) -> bool:
    return any(d in text.lower() for d in _DIGITAL_MODES)


def _parse_ctcss(raw: str) -> str | None:
    """Parse a CTCSS field to a numeric string or None."""
    raw = raw.strip()
    if not raw or raw.upper() in ("CSQ", "NONE", "N/A", ""):
        return None
    # DCS codes: D271, D54, D023
    if re.match(r"D\d{2,3}", raw, re.IGNORECASE):
        return None  # DCS — not handling yet
    # Numeric: "127.3", "103.5"
    try:
        val = float(raw)
        return str(val) if val > 0 else None
    except ValueError:
        return None


def _in_band(freq: float) -> bool:
    return 144 <= freq < 148 or 420 <= freq < 450


# ---------------------------------------------------------------------------
# Format: Iowa Repeater Council
#   Columns: City Output Call Access Mode Notes
#   No input freq — derive from standard offset
#   State: Iowa
# ---------------------------------------------------------------------------

def parse_iowa(pdf_path: str | pathlib.Path) -> list[dict]:
    rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                # Frequency is the anchor: a decimal number 3 digits before dot
                m = re.search(r'(\d{3}\.\d+)\s+([A-Z0-9/]{3,8})\s+([\d.]+)?\s+(\w+)', line)
                if not m:
                    continue
                freq_str = m.group(1)
                callsign = m.group(2)
                access   = m.group(3) or ""
                mode     = m.group(4)

                # Skip digital modes
                if _is_digital(mode) or _is_digital(line):
                    continue

                rx_freq = float(freq_str)
                if not _in_band(rx_freq):
                    continue

                # City is everything before the frequency in the line
                city = line[:m.start()].strip()
                # Remove trailing region codes (e.g. " ME", " SC") — not present in Iowa
                city = city.strip()

                # Derive TX freq — Iowa uses standard offsets
                sign = "+" if rx_freq >= 147.0 else "-"
                if 420 <= rx_freq < 450:
                    sign = "+"
                tx_freq = _standard_tx(rx_freq, sign)
                if tx_freq == 0.0:
                    continue

                rows.append({
                    "source":       "pdf:iowa_rc",
                    "callsign":     callsign,
                    "city":         city,
                    "state":        "Iowa",
                    "country":      "United States",
                    "rx_freq":      rx_freq,
                    "tx_freq":      tx_freq,
                    "ctcss_encode": _parse_ctcss(access),
                    "mode":         "FM",
                    "notes":        line[m.end():].strip()[:120],
                })
    return rows


# ---------------------------------------------------------------------------
# Format: Minnesota Repeater Council
#   Columns: CITY REGION Output Call Club Access Notes Date
#   No input freq — derive from standard offset
#   State: Minnesota
# ---------------------------------------------------------------------------

def parse_minnesota(pdf_path: str | pathlib.Path) -> list[dict]:
    rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                # Freq anchor: e.g. "146.70000" or "443.45000"
                m = re.search(r'(\d{3}\.\d{4,5})\s+([A-Z0-9/]{3,8})', line)
                if not m:
                    continue
                freq_str = m.group(1)
                callsign = m.group(2)

                rx_freq = float(freq_str)
                if not _in_band(rx_freq):
                    continue

                # Skip digital — check notes portion
                after = line[m.end():]
                if _is_digital(after):
                    continue

                # CTCSS follows the club name — look for a standalone float like "127.3"
                # or a DCS code "D271"
                ctcss_m = re.search(r'(?<!\d)(\d{2,3}\.\d)\s+', after)
                ctcss = _parse_ctcss(ctcss_m.group(1)) if ctcss_m else None

                # City is before the frequency
                city = line[:m.start()].strip()
                # Strip trailing region code (two uppercase letters like "ME", "NW")
                city = re.sub(r'\s+[A-Z]{2}\s*$', '', city).strip()

                sign = "+" if rx_freq >= 147.0 else "-"
                if 420 <= rx_freq < 450:
                    sign = "+"
                tx_freq = _standard_tx(rx_freq, sign)
                if tx_freq == 0.0:
                    continue

                rows.append({
                    "source":       "pdf:mn_rc",
                    "callsign":     callsign,
                    "city":         city.title(),
                    "state":        "Minnesota",
                    "country":      "United States",
                    "rx_freq":      rx_freq,
                    "tx_freq":      tx_freq,
                    "ctcss_encode": ctcss,
                    "mode":         "FM",
                    "notes":        after.strip()[:120],
                })
    return rows


# ---------------------------------------------------------------------------
# Format: Western Pennsylvania Repeater Council (WPRC)
#   Columns: Output Input Access Location Grid Call Trustee Sponsor Notes
#   Has explicit output AND input frequencies
#   State: Pennsylvania
# ---------------------------------------------------------------------------

def parse_wprc(pdf_path: str | pathlib.Path) -> list[dict]:
    rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                # Two frequencies at start of line
                m = re.match(
                    r'^(\d{2,3}\.\d+)\s+(\d{2,3}\.\d+)\s+'  # output input
                    r'([\d.]+|N/A)?\s*'                       # access (optional)
                    r'(\S.*?)\s+([A-Z]{2}\d{2})\s+'          # location + grid
                    r'([A-Z0-9/]{3,8})',                      # callsign
                    line
                )
                if not m:
                    continue

                rx_freq  = float(m.group(1))
                tx_freq  = float(m.group(2))
                access   = m.group(3) or ""
                location = m.group(4).strip()
                callsign = m.group(6)

                if not _in_band(rx_freq):
                    continue

                # Skip 6m, 220, etc.
                if not _in_band(rx_freq):
                    continue

                # Check notes for digital modes
                notes = line[m.end():].strip()
                if _is_digital(notes) or "D STAR" in notes.upper() or "DSTAR" in notes.upper():
                    continue

                rows.append({
                    "source":       "pdf:wprc",
                    "callsign":     callsign,
                    "city":         location,
                    "state":        "Pennsylvania",
                    "country":      "United States",
                    "rx_freq":      rx_freq,
                    "tx_freq":      tx_freq,
                    "ctcss_encode": _parse_ctcss(access),
                    "mode":         "FM",
                    "notes":        notes[:120],
                })
    return rows


# ---------------------------------------------------------------------------
# Format: All Oregon Repeaters
#   Columns: Freq± PL Location County Callsign Status
#   Sign (+ or -) on freq gives offset direction
#   State: Oregon
# ---------------------------------------------------------------------------

def parse_oregon(pdf_path: str | pathlib.Path) -> list[dict]:
    rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                # Pattern: "145.2700- 110.9 Location County Callsign OPEN"
                m = re.match(
                    r'^(\d{3}\.\d+)([+\-s])\s+'   # freq + sign ('s'=simplex)
                    r'(DGTL|[\d.]+)?\s+'            # PL tone or DGTL
                    r'(.+?)\s+'                     # location (city)
                    r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+'  # county
                    r'([A-Z0-9/]{3,8})\s+'          # callsign
                    r'(OPEN|CLOSED|IN USE)?',        # status
                    line
                )
                if not m:
                    continue

                rx_freq  = float(m.group(1))
                sign     = m.group(2)
                pl_raw   = m.group(3) or ""
                city     = m.group(4).strip()
                callsign = m.group(6)
                status   = m.group(7) or "OPEN"

                if not _in_band(rx_freq):
                    continue
                if status.upper() == "CLOSED":
                    continue
                if pl_raw.upper() == "DGTL":
                    continue  # digital

                # 's' means simplex — skip
                if sign == "s":
                    continue

                tx_freq = _standard_tx(rx_freq, sign)
                if tx_freq == 0.0:
                    continue

                rows.append({
                    "source":       "pdf:oregon",
                    "callsign":     callsign,
                    "city":         city.split(",")[0].strip(),
                    "state":        "Oregon",
                    "country":      "United States",
                    "rx_freq":      rx_freq,
                    "tx_freq":      tx_freq,
                    "ctcss_encode": _parse_ctcss(pl_raw),
                    "mode":         "FM",
                    "notes":        m.group(4).strip()[:120],
                })
    return rows


# ---------------------------------------------------------------------------
# Format: Rochester area NY
#   Columns: [CH] RECEIVE TRANSMIT TONE TRUSTEE LOCATION COMMENTS
#   Explicit receive and transmit frequencies
#   State: New York
# ---------------------------------------------------------------------------

# Band section headers to track current band
_ROC_BAND_HEADERS = re.compile(
    r'^(10 Meters?|6 Meters?|2 Meters?|1\.25|220|70 [Cc]m|440|70cm|UHF)', re.IGNORECASE
)

def parse_rochester(pdf_path: str | pathlib.Path) -> list[dict]:
    rows = []
    in_target_band = False  # True when inside 2m or 70cm section

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()

                # Detect band section headers
                hm = _ROC_BAND_HEADERS.match(line)
                if hm:
                    header = hm.group(1).lower()
                    in_target_band = any(b in header for b in ("2 meter", "70 cm", "440", "uhf"))
                    continue

                if not in_target_band:
                    continue

                # Pattern: [CH] RECEIVE TRANSMIT TONE CALLSIGN LOCATION COMMENTS
                # CH is optional (an integer)
                m = re.match(
                    r'^(?:\d+\s+)?'                   # optional channel number
                    r'(\d{3}\.\d+)\s+'                # receive (rx)
                    r'(\d{3}\.\d+)\s+'                # transmit (tx)
                    r'(CC\d+|D-Star|none|[\d.]+)?\s*' # tone
                    r'([A-Z0-9/]{3,8})\s+'            # callsign (trustee)
                    r'(\S.*?)\s+(NY|PA|OH)\s*',       # location + state
                    line
                )
                if not m:
                    continue

                rx_freq  = float(m.group(1))
                tx_freq  = float(m.group(2))
                tone_raw = m.group(3) or ""
                callsign = m.group(4)
                city     = m.group(5).strip()
                comments = line[m.end():].strip()

                if not _in_band(rx_freq):
                    continue

                # Skip digital
                tone_up = tone_raw.upper()
                if tone_up.startswith("CC") or "D-STAR" in tone_up:
                    continue
                if _is_digital(comments):
                    continue

                rows.append({
                    "source":       "pdf:rochester",
                    "callsign":     callsign,
                    "city":         city,
                    "state":        "New York",
                    "country":      "United States",
                    "rx_freq":      rx_freq,
                    "tx_freq":      tx_freq,
                    "ctcss_encode": _parse_ctcss(tone_raw),
                    "mode":         "FM",
                    "notes":        comments[:120],
                })
    return rows


# ---------------------------------------------------------------------------
# Format auto-detection and unified import
# ---------------------------------------------------------------------------

# Map from detector keyword → (state, parser_fn)
_DETECTORS: list[tuple[str, str, callable]] = [
    ("IOWA REPEATER COUNCIL",          "Iowa",         parse_iowa),
    ("Minnesota Repeater Council",     "Minnesota",    parse_minnesota),
    ("Western Pennsylvania Repeater",  "Pennsylvania", parse_wprc),
    ("All Oregon Repeaters",           "Oregon",       parse_oregon),
    ("Greater Rochester Area",         "New York",     parse_rochester),
]


def detect_and_parse(pdf_path: str | pathlib.Path) -> tuple[str, list[dict]]:
    """
    Auto-detect PDF format and parse it.
    Returns (state_name, rows).
    """
    path = pathlib.Path(pdf_path)
    try:
        with pdfplumber.open(str(path)) as pdf:
            first_page_text = (pdf.pages[0].extract_text() or "").lower()
    except Exception:
        return "Unreadable", []

    for keyword, state, parser_fn in _DETECTORS:
        if keyword.lower() in first_page_text:
            try:
                rows = parser_fn(path)
            except Exception as e:
                print(f"    Parser error: {e}")
                rows = []
            return state, rows

    return "Unknown", []


def import_pdf(pdf_path: str | pathlib.Path, db_path=None, verbose: bool = True) -> int:
    """Import a single PDF into the repeater database. Returns rows inserted."""
    conn = get_connection(db_path) if db_path else get_connection()
    state, rows = detect_and_parse(pdf_path)
    inserted = bulk_insert(conn, rows)
    conn.close()
    if verbose:
        status = "SKIPPED (unreadable/unknown)" if not rows and state in ("Unreadable", "Unknown") else ""
        print(f"  {pathlib.Path(pdf_path).name:50s}  state={state:15s}  "
              f"parsed={len(rows):4d}  inserted={inserted:4d}  {status}")
    return inserted


def import_all_pdfs(directory: str | pathlib.Path, db_path=None, verbose: bool = True) -> int:
    """Import all PDF files in a directory. Returns total rows inserted."""
    total = 0
    for pdf in sorted(pathlib.Path(directory).glob("*.pdf")):
        total += import_pdf(pdf, db_path=db_path, verbose=verbose)
    return total
