"""
Tests for web API generate endpoint and DMR ID referential integrity.

Verifies that all channels generated via web API (repeater channels,
hotspot catalog channels, hotspot disconnect channels, manual hotspot channels,
and analog channels) have their DMR ID column correctly set to match the Radio Name
in dmr_id.csv. Also tests hotspot-only and analog-only generation.
"""

import csv
import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codeplug.models import Channel, Codeplug, Repeater, Talkgroup, Zone
from web.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_web_generate_dmr_id_referential_integrity(client):
    """
    Every channel in channels.csv — whether repeater, hotspot catalog,
    hotspot disconnect, manual hotspot, or analog — must have its DMR ID
    column set to the user's callsign, matching the Radio Name in dmr_id.csv.
    """
    mock_rep = [
        Repeater(
            callsign="W9XYZ", city="Chicago", state="Illinois",
            country="United States", rx_freq=442.0625, offset=5.0,
            color_code=1, network="BrandMeister", status="on-air",
            talkgroups=[Talkgroup(3122, 1, "Illinois")],
        )
    ]

    req_data = {
        "dmr_id": 3179879,
        "callsign": "KQ9I",
        "city": "Chicago",
        "state": "Illinois",
        "locations": [{"city": "Chicago", "state": "Illinois"}],
        "networks": ["BrandMeister"],
        "selected_repeaters": ["W9XYZ:442.06250"],
        "hotspot_tg_ids": [91, 93],
        "manual_hotspot_tgs": [{"tg_id": 12345, "name": "Custom TG"}],
        "selected_analog": [{
            "callsign": "W9TET",
            "name": "W9TET Analog",
            "city": "Chicago",
            "state": "Illinois",
            "rx_freq": 146.760,
            "tx_freq": 146.160,
            "ctcss_encode": "107.2",
        }],
        "hotspot_freq": 433.550,
        "power": "High",
        "country": "United States",
        "initials": "JD",
    }

    with patch("codeplug.radioid.search_repeaters", return_value=mock_rep):
        resp = client.post("/api/generate", json=req_data)

    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))

    # dmr_id.csv must exist and have the user's Radio ID and Callsign
    assert "dmr_id.csv" in zf.namelist()
    dmr_rows = list(csv.DictReader(io.StringIO(zf.read("dmr_id.csv").decode("utf-8"))))
    assert len(dmr_rows) == 1
    assert dmr_rows[0]["Radio ID"] == "3179879"
    assert dmr_rows[0]["Radio Name"] == "KQ9I"
    valid_radio_names = {r["Radio Name"] for r in dmr_rows}

    # channels.csv check
    channels_csv = zf.read("channels.csv").decode("utf-8")
    channel_rows = list(csv.DictReader(io.StringIO(channels_csv)))
    assert len(channel_rows) > 0

    channel_names = {c["Channel Name"] for c in channel_rows}
    # Check that hotspot and manual channels are present
    assert any("HS" in name for name in channel_names)
    assert "Custom TG" in channel_names
    assert "W9TET Analog" in channel_names

    # Check DMR ID on every channel
    for ch in channel_rows:
        dmr_id = ch["DMR ID"]
        assert dmr_id, f"Channel '{ch['Channel Name']}' has empty DMR ID"
        assert dmr_id in valid_radio_names, (
            f"Channel '{ch['Channel Name']}' has DMR ID '{dmr_id}', not in dmr_id.csv"
        )


def test_web_generate_hotspot_only(client):
    """Users with only a hotspot (no repeaters selected) should get a valid codeplug."""
    req_data = {
        "dmr_id": 3179879,
        "callsign": "KQ9I",
        "city": "Chicago",
        "state": "Illinois",
        "locations": [{"city": "Chicago", "state": "Illinois"}],
        "networks": ["BrandMeister"],
        "selected_repeaters": [],
        "hotspot_tg_ids": [91, 93],
        "manual_hotspot_tgs": [{"tg_id": 9999, "name": "Local HS"}],
        "selected_analog": [],
        "hotspot_freq": 433.550,
        "power": "Low",
        "country": "United States",
        "initials": "JD",
    }

    resp = client.post("/api/generate", json=req_data)
    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))

    channel_rows = list(csv.DictReader(io.StringIO(zf.read("channels.csv").decode("utf-8"))))
    assert len(channel_rows) > 0
    for ch in channel_rows:
        assert ch["DMR ID"] == "KQ9I"


def test_web_generate_analog_only(client):
    """Users selecting only analog repeaters should get a valid codeplug."""
    req_data = {
        "dmr_id": 3179879,
        "callsign": "KQ9I",
        "city": "Chicago",
        "state": "Illinois",
        "locations": [{"city": "Chicago", "state": "Illinois"}],
        "networks": ["BrandMeister"],
        "selected_repeaters": [],
        "hotspot_tg_ids": [],
        "manual_hotspot_tgs": [],
        "selected_analog": [{
            "callsign": "W9TET",
            "name": "W9TET Analog",
            "city": "Chicago",
            "state": "Illinois",
            "rx_freq": 146.760,
            "tx_freq": 146.160,
            "ctcss_encode": "107.2",
        }],
        "hotspot_freq": 433.550,
        "power": "High",
        "country": "United States",
        "initials": "JD",
    }

    resp = client.post("/api/generate", json=req_data)
    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))

    channel_rows = list(csv.DictReader(io.StringIO(zf.read("channels.csv").decode("utf-8"))))
    assert len(channel_rows) == 1
    assert channel_rows[0]["Channel Name"] == "W9TET Analog"
    assert channel_rows[0]["DMR ID"] == "KQ9I"


def test_web_generate_no_selection_raises_400(client):
    """If nothing at all is selected, /api/generate returns 400."""
    req_data = {
        "dmr_id": 3179879,
        "callsign": "KQ9I",
        "city": "Chicago",
        "state": "Illinois",
        "locations": [{"city": "Chicago", "state": "Illinois"}],
        "networks": ["BrandMeister"],
        "selected_repeaters": [],
        "hotspot_tg_ids": [],
        "manual_hotspot_tgs": [],
        "selected_analog": [],
        "hotspot_freq": 433.550,
        "power": "High",
        "country": "United States",
        "initials": "JD",
    }

    resp = client.post("/api/generate", json=req_data)
    assert resp.status_code == 400
    assert "No repeaters or talkgroups selected" in resp.json()["detail"]


def test_codeplug_validate_catches_dmr_id_issues():
    """Codeplug.validate() should flag missing radio_name and mismatched dmr_id."""
    ch_ok = Channel(
        name="Ch1", channel_type="Digital", rx_freq=442.0, tx_freq=447.0,
        color_code=1, timeslot=1, tx_contact="TG1", rx_group="None",
        dmr_id="KQ9I",
    )
    ch_mismatch = Channel(
        name="Ch2", channel_type="Digital", rx_freq=442.0, tx_freq=447.0,
        color_code=1, timeslot=1, tx_contact="TG1", rx_group="None",
        dmr_id="OTHER",
    )

    cp_no_radio = Codeplug(
        contacts=[], rx_groups=[], channels=[ch_ok], zones=[],
        radio_id=0, radio_name="",
    )
    warnings = cp_no_radio.validate()
    assert any("no radio_name set" in w for w in warnings)

    cp_mismatch = Codeplug(
        contacts=[], rx_groups=[], channels=[ch_ok, ch_mismatch], zones=[],
        radio_id=3179879, radio_name="KQ9I",
    )
    warnings = cp_mismatch.validate()
    assert any("does not match radio_name" in w for w in warnings)


def test_web_generate_pipe_and_comma_sanitization(client):
    """Manual hotspot talkgroup names with '|' or ',' must be sanitized."""
    req_data = {
        "dmr_id": 3179879,
        "callsign": "KQ9I",
        "city": "Chicago",
        "state": "Illinois",
        "locations": [{"city": "Chicago", "state": "Illinois"}],
        "networks": ["BrandMeister"],
        "selected_repeaters": [],
        "hotspot_tg_ids": [],
        "manual_hotspot_tgs": [{"tg_id": 12345, "name": "TG|Pipe,Comma"}],
        "selected_analog": [],
        "hotspot_freq": 433.550,
        "power": "High",
        "country": "United States",
        "initials": "JD",
    }

    resp = client.post("/api/generate", json=req_data)
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))

    channels_csv = zf.read("channels.csv").decode("utf-8")
    zones_csv = zf.read("zones.csv").decode("utf-8")

    assert "TGPipeComma" in channels_csv
    assert "|" not in [c["Channel Name"] for c in csv.DictReader(io.StringIO(channels_csv))]
    # Zone members split by '|' should cleanly resolve
    zone_rows = list(csv.DictReader(io.StringIO(zones_csv)))
    for z in zone_rows:
        members = z["Channel Members"].split("|")
        assert "TGPipeComma" in members


def test_web_generate_safe_filename_header(client):
    """Content-Disposition header should be sanitized against header injection."""
    req_data = {
        "dmr_id": 3179879,
        "callsign": 'KQ9I"\r\nX-Injected: Bad',
        "city": "Chicago",
        "state": "Illinois",
        "locations": [{"city": "Chicago", "state": "Illinois"}],
        "networks": ["BrandMeister"],
        "selected_repeaters": [],
        "hotspot_tg_ids": [91],
        "manual_hotspot_tgs": [],
        "selected_analog": [],
        "hotspot_freq": 433.550,
        "power": "High",
        "country": "United States",
        "initials": "JD",
    }

    resp = client.post("/api/generate", json=req_data)
    assert resp.status_code == 200
    cd = resp.headers.get("Content-Disposition", "")
    assert "\r" not in cd and "\n" not in cd
    assert 'filename="codeplug_KQ9IX-InjectedBad.zip"' == cd.split(" ")[-1]


def test_builder_zone_name_disambiguation():
    """Duplicate zone names from different repeaters must be disambiguated."""
    from codeplug.builder import CodeplugBuilder
    from codeplug.models import CodeplugRequest, Repeater, Talkgroup

    # Two repeaters in different cities that would yield identical zone names
    rep1 = Repeater(
        callsign="W9AAA", city="Springfield", state="Illinois",
        country="United States", rx_freq=444.000, offset=5.0,
        color_code=1, network="BrandMeister", status="on-air",
        talkgroups=[Talkgroup(3122, 1, "Illinois")],
    )
    rep2 = Repeater(
        callsign="W9BBB", city="Springfield", state="Missouri",
        country="United States", rx_freq=444.000, offset=5.0,
        color_code=1, network="BrandMeister", status="on-air",
        talkgroups=[Talkgroup(3129, 1, "Missouri")],
    )

    req = CodeplugRequest(
        dmr_id=3179879, callsign="KQ9I", city="Springfield", state="Illinois",
        include_hotspot=False,
    )
    codeplug = CodeplugBuilder(req).build([rep1, rep2])
    zone_names = [z.name for z in codeplug.zones]
    assert len(zone_names) == 2
    assert len(set(zone_names)) == 2

