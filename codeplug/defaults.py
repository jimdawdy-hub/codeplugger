"""
Default talkgroup lists used when a repeater has no TG data in RadioID.net.
Also contains the full Brandmeister TG catalog for hotspot zone generation.
"""

from .models import Talkgroup


# ---------------------------------------------------------------------------
# TG abbreviations for channel name generation (max 6 chars)
# ---------------------------------------------------------------------------
TG_ABBREV: dict[int, str] = {
    1:     "Loc1",    # BM Local 1 / MARC WW 1
    2:     "Clstr",   # BM/MARC Cluster
    3:     "NA",      # MARC NA
    8:     "TriSt",   # MARC TriState / BM Regional
    9:     "Local",   # BM Local 9 / MARC Talk 9
    13:    "WWEng",   # MARC WW English
    33:    "TG33",
    81:    "TriSt",   # Tristate
    85:    "FRRL",
    88:    "TG88",
    91:    "WW",      # BM Worldwide
    93:    "NA",      # BM North America
    98:    "Test",
    99:    "TG99",
    113:   "Eng",
    123:   "Eng",
    260:   "TG260",
    310:   "TAC310",
    311:   "TAC311",
    312:   "TAC312",
    313:   "TAC313",
    314:   "TAC314",
    315:   "TAC315",
    316:   "TAC316",
    317:   "TAC317",
    318:   "TAC318",
    319:   "TAC319",
    401:   "Kazakh",
    438:   "Mongol",
    440:   "Japan",
    901:   "WWTac1",
    902:   "WWTac2",
    911:   "TAC911",
    999:   "WI",
    1776:  "USA",
    2404:  "SM4",
    2600:  "TG2600",
    3100:  "USABrg",
    3104:  "AZ",
    3106:  "CA",
    3111:  "DC",
    3112:  "FL",
    3113:  "GA",
    3117:  "IL",
    3118:  "IN",
    3119:  "IA",
    3121:  "KY",
    3124:  "MD",
    3125:  "MA",
    3126:  "MI",
    3127:  "MN",
    3129:  "MO",
    3137:  "NC",
    3139:  "OH",
    3140:  "OK",
    3142:  "PA",
    3146:  "SD",
    3147:  "TN",
    3148:  "TX",
    3151:  "VA",
    3153:  "WA",
    3155:  "WI",
    3166:  "DVSwit",
    3167:  "Allstr",
    3169:  "MidWst",
    3172:  "NERegn",
    3173:  "MidAtl",
    3174:  "SERegn",
    3175:  "SPlns",
    3176:  "SWRegn",
    3177:  "Mtn",
    3181:  "POTA",
    3199:  "Hurrnt",
    4000:  "Disc",
    5000:  "Stat",
    5555:  "TG5555",
    6666:  "TG6666",
    7777:  "Stroke",
    8001:  "TG8001",
    8205:  "TG8205",
    8790:  "P25",
    8888:  "TG8888",
    8951:  "TAC1",
    9480:  "ICQ",
    9911:  "EmcmUS",
    9912:  "EmCom",
    9990:  "Parrot",   # BM Parrot — Private Call only
    9998:  "Parrot",   # Legacy parrot alias — same function as 9990
    9999:  "TG9999",
    9101:  "Maritm",
    9102:  "Aviatn",
    9112:  "EmCom",
    27000: "Deact",
    31000: "EmComm",
    31014: "T31014",
    31122: "T31122",
    31171: "ILLink",
    31172: "ChiNet",
    31173: "NILEcm",
    31175: "Astro",
    31176: "ChiMet",
    31180: "INTac",
    31181: "INLink",
    31183: "INWxOp",
    31264: "MITac",
    31268: "UPTG",
    31292: "STLMet",
    31488: "T31488",
    31550: "WITac",
    31551: "WIFus",
    31555: "T31555",
    31665: "Campfr",
    46600: "T46600",
    48778: "T48778",
    63951: "T63951",
    310997: "Parrot",   # US regional Parrot (MCC 310 + 997) — Private Call only
}


def tg_abbrev(tg_id: int, description: str = "") -> str:
    """Return a ≤6-char abbreviation for a talkgroup ID."""
    if tg_id in TG_ABBREV:
        return TG_ABBREV[tg_id]
    if description:
        # Use first word of the description, cleaned of non-alphanum chars
        import re
        word = re.sub(r"[^A-Za-z0-9]", "", description.split()[0]) if description.split() else ""
        if word:
            return word[:6]
    return f"T{tg_id}"[:6]


# ---------------------------------------------------------------------------
# Talkgroups that require Private Call type instead of Group Call.
#
# BrandMeister Parrot works ONLY as a Private Call — as a Group Call it is
# silently ignored.  Verified IDs:
#   9990   — Primary BM Parrot (worldwide)
#   310997 — US regional Parrot (MCC 310 + 997)
#   9998   — Legacy alias; kept for compatibility but 9990/310997 are preferred
# ---------------------------------------------------------------------------
PRIVATE_CALL_TGS: set[int] = {9990, 9998, 310997}


# ---------------------------------------------------------------------------
# Network-prefix mapping  (RadioID ipsc_network → short prefix)
# ---------------------------------------------------------------------------
NETWORK_PREFIX: dict[str, str] = {
    "BrandMeister":    "BM",
    "Brandmeister":    "BM",
    "BM":              "BM",
    "DMR-MARC":        "MARC",
    "MARC":            "MARC",
    "ChicagoLand-CC":  "BM",   # uses BM-style TG numbering
    "Chicagoland-CC":  "BM",
    "Tristate":        "MARC",  # uses MARC-style TG numbering
    "TriState":        "MARC",
}


def network_prefix(network: str) -> str:
    """Return the short contact name prefix for a network string."""
    return NETWORK_PREFIX.get(network, "BM")


# ---------------------------------------------------------------------------
# Fallback TG lists used when RadioID has no talkgroups for a repeater
# ---------------------------------------------------------------------------

# Standard Brandmeister minimal loadout (TS1 wide-area, TS2 local/tactical)
BM_DEFAULTS: list[Talkgroup] = [
    Talkgroup(id=91,   timeslot=1, description="Worldwide"),
    Talkgroup(id=93,   timeslot=1, description="North America"),
    Talkgroup(id=3117, timeslot=1, description="Illinois"),
    Talkgroup(id=3118, timeslot=1, description="Indiana"),
    Talkgroup(id=9,    timeslot=2, description="Local"),
    Talkgroup(id=310,  timeslot=2, description="TAC 310"),
    Talkgroup(id=311,  timeslot=2, description="TAC 311"),
    Talkgroup(id=312,  timeslot=2, description="TAC 312"),
]

# DMR-MARC standard loadout (Tristate/MARC networks follow same TG plan)
MARC_DEFAULTS: list[Talkgroup] = [
    Talkgroup(id=8,    timeslot=1, description="TriState"),
    Talkgroup(id=1,    timeslot=2, description="Worldwide"),
    Talkgroup(id=3,    timeslot=2, description="North America"),
    Talkgroup(id=9,    timeslot=2, description="Talk"),
    Talkgroup(id=13,   timeslot=2, description="WW English"),
    Talkgroup(id=4000, timeslot=2, description="Disconnect"),
    Talkgroup(id=5000, timeslot=2, description="Status"),
]

# Simple Brandmeister-only repeater (minimal — WW/NA + local/TAC)
BM_SIMPLE_DEFAULTS: list[Talkgroup] = [
    Talkgroup(id=91,  timeslot=1, description="Worldwide"),
    Talkgroup(id=93,  timeslot=1, description="North America"),
    Talkgroup(id=9,   timeslot=2, description="Local"),
    Talkgroup(id=310, timeslot=2, description="TAC 310"),
    Talkgroup(id=312, timeslot=2, description="TAC 312"),
]

NETWORK_DEFAULTS: dict[str, list[Talkgroup]] = {
    "BM":   BM_DEFAULTS,
    "MARC": MARC_DEFAULTS,
}


def defaults_for_network(network: str) -> list[Talkgroup]:
    prefix = network_prefix(network)
    return NETWORK_DEFAULTS.get(prefix, BM_SIMPLE_DEFAULTS)


# ---------------------------------------------------------------------------
# Brandmeister hotspot TG catalog — common/useful TGs a user might want
# Grouped for display in the web UI
# ---------------------------------------------------------------------------

BM_HOTSPOT_TGS: list[dict] = [
    # --- Wide area ---
    {"id": 91,    "name": "Worldwide",        "group": "Wide Area"},
    {"id": 93,    "name": "North America",    "group": "Wide Area"},
    {"id": 1776,  "name": "USA 1776",         "group": "Wide Area"},
    {"id": 3100,  "name": "USA Bridge",       "group": "Wide Area"},
    # --- US regions ---
    {"id": 3172,  "name": "Northeast",        "group": "US Regions"},
    {"id": 3173,  "name": "Mid-Atlantic",     "group": "US Regions"},
    {"id": 3174,  "name": "Southeast",        "group": "US Regions"},
    {"id": 3169,  "name": "Midwest",          "group": "US Regions"},
    {"id": 3175,  "name": "South Plains",     "group": "US Regions"},
    {"id": 3176,  "name": "Southwest",        "group": "US Regions"},
    {"id": 3177,  "name": "Mountain",         "group": "US Regions"},
    # --- US states ---
    {"id": 3104,  "name": "Arizona",          "group": "US States"},
    {"id": 3106,  "name": "California",       "group": "US States"},
    {"id": 3111,  "name": "DC",               "group": "US States"},
    {"id": 3112,  "name": "Florida",          "group": "US States"},
    {"id": 3113,  "name": "Georgia",          "group": "US States"},
    {"id": 3117,  "name": "Illinois",         "group": "US States"},
    {"id": 3118,  "name": "Indiana",          "group": "US States"},
    {"id": 3119,  "name": "Iowa",             "group": "US States"},
    {"id": 3121,  "name": "Kentucky",         "group": "US States"},
    {"id": 3124,  "name": "Maryland",         "group": "US States"},
    {"id": 3125,  "name": "Massachusetts",    "group": "US States"},
    {"id": 3126,  "name": "Michigan",         "group": "US States"},
    {"id": 3127,  "name": "Minnesota",        "group": "US States"},
    {"id": 3129,  "name": "Missouri",         "group": "US States"},
    {"id": 3137,  "name": "North Carolina",   "group": "US States"},
    {"id": 3139,  "name": "Ohio",             "group": "US States"},
    {"id": 3140,  "name": "Oklahoma",         "group": "US States"},
    {"id": 3142,  "name": "Pennsylvania",     "group": "US States"},
    {"id": 3146,  "name": "South Dakota",     "group": "US States"},
    {"id": 3147,  "name": "Tennessee",        "group": "US States"},
    {"id": 3148,  "name": "Texas",            "group": "US States"},
    {"id": 3151,  "name": "Virginia",         "group": "US States"},
    {"id": 3153,  "name": "Washington",       "group": "US States"},
    {"id": 3155,  "name": "Wisconsin",        "group": "US States"},
    # --- Local/Illinois area ---
    {"id": 31171, "name": "IL Link",          "group": "IL/Midwest"},
    {"id": 31172, "name": "Chicago Net",      "group": "IL/Midwest"},
    {"id": 31173, "name": "N IL EmComm",      "group": "IL/Midwest"},
    {"id": 31176, "name": "Chicago Metro",    "group": "IL/Midwest"},
    {"id": 31268, "name": "Upper MI",         "group": "IL/Midwest"},
    {"id": 31292, "name": "STL Metro",        "group": "IL/Midwest"},
    {"id": 31551, "name": "WI Fusion",        "group": "IL/Midwest"},
    {"id": 31665, "name": "Campfire",         "group": "IL/Midwest"},
    # --- TAC ---
    {"id": 310,   "name": "TAC 310",          "group": "TAC"},
    {"id": 311,   "name": "TAC 311",          "group": "TAC"},
    {"id": 312,   "name": "TAC 312",          "group": "TAC"},
    {"id": 313,   "name": "TAC 313",          "group": "TAC"},
    {"id": 317,   "name": "TAC 317",          "group": "TAC"},
    # --- Activity/utility ---
    {"id": 3167,  "name": "Allstar",          "group": "Activity"},
    {"id": 3166,  "name": "DVSwitch",         "group": "Activity"},
    {"id": 3181,  "name": "POTA",             "group": "Activity"},
    {"id": 3199,  "name": "Hurricane Net",    "group": "Activity"},
    {"id": 31000, "name": "EmComm",           "group": "Activity"},
    {"id": 9990,   "name": "Parrot (Private Call)",    "group": "Activity"},
    {"id": 310997, "name": "Parrot US (Private Call)", "group": "Activity"},
    {"id": 27000, "name": "Deactivate TG",    "group": "Activity"},
    # --- Local/simplex ---
    {"id": 9,     "name": "Local",            "group": "Local"},
    {"id": 1,     "name": "Local (alt)",      "group": "Local"},
]
