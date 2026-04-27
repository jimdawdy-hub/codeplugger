"""
KML/KMZ importer for the Google Earth Ham Repeaters project.

Source: https://drive.google.com/drive/folders/10Lvzkdtox8vG7iNkpQHSOIUfn8yUNV5b
Data originally from RepeaterBook.com, organized by state and band.

ZIP structure expected:
  {State}/2 Meters/{State} 2M.kml
  {State}/70 Centimeters/{State} 70CM.kml

Each KML Placemark contains:
  <name>CALLSIGN</name>
  <description>City <br> FREQ+/- CTCSS <br> On-air: Yes/No ...</description>
  <Point><coordinates>lon,lat,0</coordinates></Point>

FREQ suffix: + means input = output + standard_offset
             - means input = output - standard_offset
             2m offset = 0.600 MHz, 70cm offset = 5.000 MHz
"""

import re
import xml.etree.ElementTree as ET
import zipfile
import pathlib
from typing import Optional

from .repeater_db import get_connection, bulk_insert

# Bands we care about
_BANDS = ["2 Meters", "70 Centimeters"]

# Standard offsets by band
_OFFSET = {
    "2 Meters": 0.600,
    "70 Centimeters": 5.000,
}


def _parse_description(desc: str) -> tuple[str, float, Optional[str], bool]:
    """
    Parse a KML description string.

    Returns (city, rx_freq, ctcss).
    rx_freq = 0.0 if unparseable.
    """
    # Strip CDATA and HTML tags
    text = re.sub(r'<!\[CDATA\[.*?\]\]>', ' ', desc, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # "City  147.03000+ 103.5  On-air: Yes ..."
    freq_match = re.search(r'(\d{2,3}\.\d+)([+-])\s*([\d.]+)?', text)
    if not freq_match:
        return text[:40], 0.0, None

    rx_freq   = float(freq_match.group(1))
    ctcss_raw = (freq_match.group(3) or "").strip()

    # City is everything before the frequency
    city = text[:freq_match.start()].strip().split('<br>')[0].strip()
    city = city.split()[0] if len(city.split()) > 4 else city  # sanity cap

    ctcss = ctcss_raw if ctcss_raw and float(ctcss_raw) > 0 else None

    return city, rx_freq, ctcss


def _parse_kml_content(kml_text: str, state: str, band: str, source_tag: str) -> list[dict]:
    """Parse KML XML text and return list of repeater dicts."""
    offset = _OFFSET.get(band, 0.0)
    rows: list[dict] = []

    try:
        root = ET.fromstring(kml_text)
    except ET.ParseError:
        return []

    for pm in root.iter("Placemark"):
        name_el = pm.find("name")
        desc_el = pm.find("description")
        coord_el = pm.find(".//coordinates")

        if name_el is None or desc_el is None:
            continue

        callsign = (name_el.text or "").strip()
        city, rx_freq, ctcss = _parse_description(desc_el.text or "")

        if rx_freq == 0.0:
            continue

        # Calculate tx freq from sign embedded in description
        desc_text = desc_el.text or ""
        sign_match = re.search(r'\d{2,3}\.\d+([+-])', desc_text)
        if sign_match:
            sign = sign_match.group(1)
            tx_freq = round(rx_freq + (offset if sign == "+" else -offset), 5)
        else:
            continue  # can't determine offset direction

        # Band sanity check
        if band == "2 Meters" and not (144 <= rx_freq < 148):
            continue
        if band == "70 Centimeters" and not (420 <= rx_freq < 450):
            continue

        rows.append({
            "source":       source_tag,
            "callsign":     callsign,
            "city":         city,
            "state":        state,
            "country":      "United States",
            "rx_freq":      rx_freq,
            "tx_freq":      tx_freq,
            "ctcss_encode": ctcss,
            "mode":         "FM",
            "notes":        "",
        })

    return rows


def import_kml_zip(
    zip_path: str | pathlib.Path,
    db_path=None,
    states: Optional[list[str]] = None,
    verbose: bool = True,
) -> int:
    """
    Import 2m and 70cm repeaters from the Google Earth Ham Repeaters ZIP.

    Args:
        zip_path: Path to the downloaded Google Drive ZIP file
        db_path:  Override default DB path (for testing)
        states:   If given, only import these states (e.g. ['Illinois', 'Indiana'])
        verbose:  Print progress

    Returns:
        Total number of new records inserted
    """
    conn = get_connection(db_path) if db_path else get_connection()
    total = 0

    with zipfile.ZipFile(str(zip_path)) as zf:
        names = zf.namelist()
        for band in _BANDS:
            kml_files = [n for n in names if f"/{band}/" in n and n.endswith(".kml")]
            for kml_path in sorted(kml_files):
                # State is the first path component
                state = kml_path.split("/")[0]
                if states and state not in states:
                    continue

                try:
                    kml_text = zf.read(kml_path).decode("utf-8", errors="replace")
                except Exception:
                    continue

                source_tag = f"kml:{state.lower().replace(' ', '_')}"
                rows = _parse_kml_content(kml_text, state, band, source_tag)
                inserted = bulk_insert(conn, rows)
                total += inserted

                if verbose and rows:
                    print(f"  {state:20s} {band:20s}  {len(rows):4d} parsed  {inserted:4d} inserted")

    conn.close()
    return total
