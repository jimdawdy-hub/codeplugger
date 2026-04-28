"""
BrandMeister talkgroup catalog loader.

Reads 'Talkgroups BrandMeister.csv' from the project root and categorizes
each TG into one of the groups used for the hotspot zone picker.
"""

import csv
import pathlib

from .paths import ROOT
_CSV_PATH = ROOT / "Talkgroups BrandMeister.csv"

# Category → zone name used in the generated codeplug (≤16 chars)
CATEGORY_ZONE_NAMES: dict[str, str] = {
    "Wide Area":       "HS Wide Area",
    "US States":       "HS State TGs",
    "US Regional":     "HS Regional TGs",
    "Countries":       "HS Country TGs",
    "Language":        "HS Language TGs",
    "Activity":        "HS Activity TGs",
    "Special Interest":"HS SpcInt TGs",
    "Emcomm":          "HS Emcomm TGs",
    "Link":            "HS Link TGs",
}

# Display order for UI categories
CATEGORY_ORDER = [
    "Wide Area", "US States", "US Regional",
    "Countries", "Language", "Activity",
    "Special Interest", "Emcomm", "Link",
]

_EMCOMM = {'emcom', 'ares ', 'races', 'skywarn', 'hurricane', 'civil air patrol',
            'emergency management', 'dem ', 'fema', 'hmasn', 'cap ', 'cap-',
            'severe wx', 'wx net', 'wx tac', 'emrg'}
_ACTIVITY = {'sota', 'pota', 'jota', 'yota', 'amsat', 'wwyl', 'maritime',
              'aviation', 'eurao', 'reddit', 'podcast', 'cafe ', 'manna',
              'chowhound', 'lbgtq', 'wvnet', 'veteran', 'collegiate',
              'hamcation', 'amateur television', 'atv talk', 'ww radio',
              'goodwill', 'pota', 'sota', 'yota'}
_LINK = {'allstar', 'dvswitch', 'irlp', 'c4fm link', 'xrf', 'hoseline',
         'echolink', 'bridge', ' link '}
_LANGUAGE = {'german', 'english', 'spanish', 'portuguese', 'italian', 'dutch',
             'swedish', 'nordic', 'arabic', 'basque', 'francophonie', 'hellenic',
             'panhellenic', 'dach', 'greek', 'nordic', 'nordic chat',
             'worldwide maritime', 'wwyl'}
_WIDE_IDS = {91, 92, 93, 94, 95, 98, 901, 902, 903}


def _categorize(country: str, tg_id: int, name: str) -> str:
    nl = name.lower()

    if any(kw in nl for kw in _EMCOMM):
        return "Emcomm"
    if any(kw in nl for kw in _LINK):
        return "Link"
    if any(kw in nl for kw in _ACTIVITY):
        return "Activity"
    if any(kw in nl for kw in _LANGUAGE):
        return "Language"

    if country == "Global":
        return "Wide Area" if tg_id in _WIDE_IDS else "Special Interest"

    if country == "US":
        if 3101 <= tg_id <= 3156:
            return "US States"
        return "US Regional"

    if len(country) >= 2:
        return "Countries"

    return "Wide Area"


def load_catalog() -> dict[str, list[dict]]:
    """
    Load and categorize all BM talkgroups from the CSV.

    Returns {category: [{"id": int, "name": str, "country": str}, ...]}
    sorted by TG ID within each category.
    """
    if not _CSV_PATH.exists():
        return {}

    catalog: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}

    with open(_CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = (row.get("Country") or "").strip()
            name    = (row.get("Name") or "").strip()
            try:
                tg_id = int(row.get("Talkgroup", ""))
            except ValueError:
                continue

            if not name or tg_id == 4000:
                continue

            cat = _categorize(country, tg_id, name)
            catalog.setdefault(cat, []).append({
                "id": tg_id,
                "name": name,
                "country": country,
            })

    for cat in catalog:
        catalog[cat].sort(key=lambda x: x["id"])

    return catalog


def load_tg_names() -> dict[int, str]:
    """Return {tg_id: name} for all TGs in the CSV."""
    if not _CSV_PATH.exists():
        return {}
    result: dict[int, str] = {}
    with open(_CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            try:
                tg_id = int(row.get("Talkgroup", ""))
            except ValueError:
                continue
            if name and tg_id:
                result[tg_id] = name
    return result
