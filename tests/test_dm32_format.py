"""
Conformance tests for the DM-32UV CPS CSV wire format.

Why this file exists
--------------------
Every generated CSV is a *wire format* consumed by closed-source Windows
software.  The CPS does not report errors: it accepts a malformed file,
silently drops the rows it cannot parse, and the user discovers the damage
later as "Null Ch." on the radio.  There is no feedback loop, so the format
has to be pinned down by tests instead.

Provenance of the constants below
---------------------------------
The header list and the accepted enum values were read off a genuine
Baofeng DM-32 CPS v1.60 export (Channels.csv / Zones.csv / Talkgroups.csv /
RXGroupLists.csv / DMR-ID.csv) and cross-checked against a known-working
CHIRP -> DM-32UV converter.  Only the facts of the format are recorded here;
no vendor file is redistributed.

  - github.com/pskillen/codeplug-tool  (sample-exports/Baofeng DM32 CPS v1.60)
  - github.com/mrshadowsys/Quansheng-DM32UV-Chirp-to-DM32-channel-list-

The referential-integrity tests are the important ones.  Four of the five
files are joined by *name*, not by index, and a dangling name is exactly the
failure mode that produces "Null Ch.".
"""

import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codeplug import csv_export
from codeplug.builder import CodeplugBuilder
from codeplug.models import CodeplugRequest, Repeater, Talkgroup


# ---------------------------------------------------------------------------
# The format, as observed in a real CPS v1.60 export
# ---------------------------------------------------------------------------

CPS_CHANNEL_HEADERS = [
    "No.", "Channel Name", "Channel Type",
    "RX Frequency[MHz]", "TX Frequency[MHz]",
    "Power", "Band Width", "Scan List", "TX Admit", "Emergency System",
    "Squelch Level", "APRS Report Type", "Forbid TX", "APRS Receive",
    "Forbid Talkaround", "Auto Scan", "Lone Work", "Emergency Indicator",
    "Emergency ACK", "Analog APRS PTT Mode", "Digital APRS PTT Mode",
    "TX Contact", "RX Group List", "Color Code", "Time Slot",
    "Encryption", "Encryption ID", "APRS Report Channel", "Direct Dual Mode",
    "Private Confirm", "Short Data Confirm", "DMR ID",
    "CTC/DCS Decode", "CTC/DCS Encode", "Scramble", "RX Squelch Mode",
    "Signaling Type", "PTT ID", "VOX Function", "PTT ID Display",
]

CPS_ZONE_HEADERS = ["No.", "Zone Name", "Channel Members"]
CPS_TALK_GROUP_HEADERS = ["No.", "Name", "ID", "Type"]
CPS_RX_GROUP_HEADERS = ["No.", "RX Group Name", "Contact Members"]
CPS_DMR_ID_HEADERS = ["No.", "Radio ID", "Radio Name"]

# "Color Code Free" is the AnyTone spelling and is NOT accepted here.
VALID_TX_ADMIT = {"Channel Idle", "Allow TX"}
VALID_POWER = {"High", "Middle", "Low"}
VALID_CHANNEL_TYPE = {"Analog", "Digital", "Fixed Analog", "Fixed Digital"}
VALID_BAND_WIDTH = {"12.5KHz", "25KHz"}
VALID_TIME_SLOT = {"Slot 1", "Slot 2"}
VALID_CALL_TYPE = {"Group Call", "Private Call"}

NAME_LIMIT = 16          # channel and zone names
RX_GROUP_NAME_LIMIT = 11  # CPS silently drops longer references


# ---------------------------------------------------------------------------
# Fixture: a codeplug exercising every code path (multi-repeater city,
# single-repeater city, two networks, hotspot zone, disconnect channels)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def codeplug():
    repeaters = [
        Repeater(
            callsign="W9XYZ", city="Chicago", state="Illinois",
            country="United States", rx_freq=442.0625, offset=5.0,
            color_code=1, network="BrandMeister", status="on-air",
            talkgroups=[
                Talkgroup(3122, 1, "Illinois"),
                Talkgroup(91, 1, "Worldwide"),
                Talkgroup(9990, 2, "Parrot"),
                Talkgroup(31012, 2, "TAC 310"),
            ],
        ),
        Repeater(
            callsign="W9ABC", city="Chicago", state="Illinois",
            country="United States", rx_freq=443.975, offset=5.0,
            color_code=3, network="BrandMeister", status="on-air",
            talkgroups=[Talkgroup(3122, 1, "Illinois"), Talkgroup(93, 1, "North America")],
        ),
        Repeater(
            callsign="K4DEF", city="Shelby", state="North Carolina",
            country="United States", rx_freq=147.150, offset=0.6,
            color_code=1, network="DMR-MARC", status="on-air",
            talkgroups=[Talkgroup(3137, 1, "North Carolina")],
        ),
    ]
    request = CodeplugRequest(
        dmr_id=3122107, callsign="KQ9I", city="Chicago", state="Illinois",
        include_hotspot=True, hotspot_talkgroup_ids=[91, 93, 3122],
    )
    return CodeplugBuilder(request).build(repeaters)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


@pytest.fixture(scope="module")
def files(codeplug):
    return {
        "channels": _rows(csv_export.write_channels_csv(codeplug)),
        "zones": _rows(csv_export.write_zones_csv(codeplug)),
        "talk_groups": _rows(csv_export.write_talk_groups_csv(codeplug)),
        "rx_groups": _rows(csv_export.write_rx_groups_csv(codeplug)),
        "dmr_ids": _rows(csv_export.write_dmr_id_csv(codeplug)),
    }


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("writer,expected", [
    (csv_export.write_channels_csv, CPS_CHANNEL_HEADERS),
    (csv_export.write_zones_csv, CPS_ZONE_HEADERS),
    (csv_export.write_talk_groups_csv, CPS_TALK_GROUP_HEADERS),
    (csv_export.write_rx_groups_csv, CPS_RX_GROUP_HEADERS),
    (csv_export.write_dmr_id_csv, CPS_DMR_ID_HEADERS),
])
def test_headers_match_cps_exactly(codeplug, writer, expected):
    """Column order is positional in the CPS parser; a shifted column is fatal."""
    header = next(csv.reader(io.StringIO(writer(codeplug))))
    assert header == expected


# ---------------------------------------------------------------------------
# Referential integrity — the "Null Ch." class of bug
# ---------------------------------------------------------------------------

def test_every_zone_member_resolves_to_a_channel(files):
    """An unresolvable zone member is what the radio displays as 'Null Ch.'."""
    names = {c["Channel Name"] for c in files["channels"]}
    dangling = [
        (z["Zone Name"], m)
        for z in files["zones"]
        for m in z["Channel Members"].split("|")
        if m not in names
    ]
    assert dangling == []


def test_every_channel_dmr_id_resolves_to_a_radio_name(files):
    """
    The channel 'DMR ID' column is a name reference into the radio's Radio ID
    table, not a DMR ID number.  Shipping a name that is not in dmr_id.csv
    leaves every channel pointing at nothing on a stock CPS document.
    """
    radio_names = {r["Radio Name"] for r in files["dmr_ids"]}
    dangling = {c["DMR ID"] for c in files["channels"]} - radio_names
    assert dangling == set()


def test_every_tx_contact_resolves_to_a_talk_group(files):
    known = {t["Name"] for t in files["talk_groups"]} | {"None"}
    dangling = {c["TX Contact"] for c in files["channels"]} - known
    assert dangling == set()


def test_every_rx_group_reference_resolves(files):
    known = {g["RX Group Name"] for g in files["rx_groups"]} | {"None"}
    dangling = {c["RX Group List"] for c in files["channels"]} - known
    assert dangling == set()


def test_every_rx_group_member_resolves_to_a_talk_group(files):
    known = {t["Name"] for t in files["talk_groups"]}
    dangling = [
        m for g in files["rx_groups"]
        for m in g["Contact Members"].split("|") if m and m not in known
    ]
    assert dangling == []


# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("column,valid", [
    ("TX Admit", VALID_TX_ADMIT),
    ("Power", VALID_POWER),
    ("Channel Type", VALID_CHANNEL_TYPE),
    ("Band Width", VALID_BAND_WIDTH),
    ("Time Slot", VALID_TIME_SLOT),
])
def test_channel_enum_columns(files, column, valid):
    assert {c[column] for c in files["channels"]} <= valid


def test_talk_group_call_types(files):
    assert {t["Type"] for t in files["talk_groups"]} <= VALID_CALL_TYPE


def test_numeric_ranges(files):
    for c in files["channels"]:
        assert 0 <= int(c["Color Code"]) <= 15, c["Channel Name"]
        assert 0 <= int(c["Squelch Level"]) <= 9, c["Channel Name"]
        assert float(c["RX Frequency[MHz]"]) > 0, c["Channel Name"]
        assert float(c["TX Frequency[MHz]"]) > 0, c["Channel Name"]


def test_frequencies_use_five_decimal_places(files):
    for c in files["channels"]:
        for col in ("RX Frequency[MHz]", "TX Frequency[MHz]"):
            assert c[col].split(".")[1] and len(c[col].split(".")[1]) == 5, c[col]


# ---------------------------------------------------------------------------
# Name constraints
# ---------------------------------------------------------------------------

def test_names_within_length_limits(files):
    for c in files["channels"]:
        assert 0 < len(c["Channel Name"]) <= NAME_LIMIT, c["Channel Name"]
    for z in files["zones"]:
        assert 0 < len(z["Zone Name"]) <= NAME_LIMIT, z["Zone Name"]
    for g in files["rx_groups"]:
        assert len(g["RX Group Name"]) <= RX_GROUP_NAME_LIMIT, g["RX Group Name"]


def test_channel_names_are_unique(files):
    names = [c["Channel Name"] for c in files["channels"]]
    assert len(names) == len(set(names))


def test_zone_names_are_unique(files):
    names = [z["Zone Name"] for z in files["zones"]]
    assert len(names) == len(set(names))


def test_no_pipe_in_names(files):
    """'|' is the member separator in zones.csv and rx_group_lists.csv."""
    for c in files["channels"]:
        assert "|" not in c["Channel Name"]
    for t in files["talk_groups"]:
        assert "|" not in t["Name"]


def test_names_have_no_leading_or_trailing_whitespace(files):
    """The CPS trims on import; an untrimmed name in zones.csv then misses."""
    for c in files["channels"]:
        assert c["Channel Name"] == c["Channel Name"].strip()
    for z in files["zones"]:
        assert z["Zone Name"] == z["Zone Name"].strip()


# ---------------------------------------------------------------------------
# ZIP packaging
# ---------------------------------------------------------------------------

def test_zip_contains_expected_files(codeplug):
    import zipfile
    with zipfile.ZipFile(io.BytesIO(csv_export.write_zip(codeplug))) as zf:
        names = set(zf.namelist())
    assert {"channels.csv", "zones.csv", "talk_groups.csv",
            "dmr_id.csv", "README.txt"} <= names


def test_zip_omits_rx_group_file_when_empty(codeplug):
    """
    Importing a header-only CSV asks the CPS to apply an empty table.  When no
    RX groups are generated the file should not be shipped at all.
    """
    import zipfile
    assert codeplug.rx_groups == []
    with zipfile.ZipFile(io.BytesIO(csv_export.write_zip(codeplug))) as zf:
        assert "rx_group_lists.csv" not in zf.namelist()


def test_csv_uses_crlf_line_endings(codeplug):
    assert csv_export.write_channels_csv(codeplug).endswith("\r\n")
