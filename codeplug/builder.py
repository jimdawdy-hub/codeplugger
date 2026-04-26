"""
Core codeplug builder.

Takes a CodeplugRequest and produces a Codeplug containing the four
lists needed for DM-32UV CSV import:
    contacts  →  Digital Contacts
    rx_groups →  Digital RX Group Lists
    channels  →  Channels
    zones     →  Zones
"""

import re
from .models import Channel, Codeplug, CodeplugRequest, Contact, Repeater, RXGroup, Talkgroup, Zone
from .defaults import (
    BM_HOTSPOT_TGS,
    PRIVATE_CALL_TGS,
    defaults_for_network,
    network_prefix,
    tg_abbrev,
)


# ---------------------------------------------------------------------------
# Name generation helpers
# ---------------------------------------------------------------------------

# Strict display limit for channel names, zone names, and contact/talkgroup names.
# The DM-32UV hardware allows 16 chars, but 12 keeps names readable on the radio LCD
# and consistent across all three name fields.
# Note: RX group names are capped at 11 by a separate CPS bug (see make_rx_group_name).
MAX_NAME_LEN = 12

# US state abbreviations used in contact names
_STATE_ABBREV: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT",
    "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
    "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC",
}


def _city_abbrev(city: str, max_len: int = 9) -> str:
    """Produce a city abbreviation ≤ max_len chars (strip spaces/punctuation)."""
    # Remove common noise words and punctuation
    clean = re.sub(r"['\-\. ]", "", city)
    return clean[:max_len]


def _freq_suffix(rx_freq: float) -> str:
    """Return the 3-digit fractional suffix used in channel names, e.g. '975'."""
    frac = round(rx_freq % 1 * 1000) % 1000
    return f"{frac:03d}"


def make_channel_name(city: str, rx_freq: float, tg_id: int, timeslot: int,
                      use_freq: bool = True, tg_desc: str = "") -> str:
    """
    Build a channel name ≤ MAX_NAME_LEN chars.

    Format: {city}{freq} {tg}  (with freq only when use_freq=True)

    The city abbreviation is shortened as needed to fit all components.
    """
    tg_sfx = " " + tg_abbrev(tg_id, tg_desc)        # 1 + ≤6 chars

    available_for_city_freq = MAX_NAME_LEN - len(tg_sfx)
    freq_str = _freq_suffix(rx_freq) if use_freq else ""
    city_max = available_for_city_freq - len(freq_str)
    city_part = _city_abbrev(city, max(1, city_max))

    return (city_part + freq_str + tg_sfx)[:MAX_NAME_LEN]


def make_zone_name(city: str, rx_freq: float, network: str,
                   use_freq: bool = True) -> str:
    """Zone name for display — up to MAX_NAME_LEN chars."""
    prefix = network_prefix(network)
    freq_str = _freq_suffix(rx_freq) if use_freq else ""
    # 1 for the space between freq/city and prefix
    avail_city = MAX_NAME_LEN - len(freq_str) - 1 - len(prefix)
    city_part = _city_abbrev(city, max(1, avail_city))
    name = f"{city_part}{freq_str} {prefix}" if use_freq else f"{city_part} {prefix}"
    return name[:MAX_NAME_LEN]


def make_rx_group_name(city: str, rx_freq: float, network: str,
                       use_freq: bool = True) -> str:
    """
    RX Group name — hard limit of 11 chars.

    The DM-32UV CPS silently drops any RX Group reference whose name
    exceeds 11 characters, writing None to the channel instead.

    Format with freq:   {city}{freq}{prefix_short}  e.g. 'Chi975BM'
    Format without:     {city} {prefix}              e.g. 'Skokie BM'
    """
    prefix = network_prefix(network)  # 'BM' or 'MARC'
    MAX = 11

    if use_freq:
        freq_str = _freq_suffix(rx_freq)          # 3 digits
        # No spaces — pack city+freq+prefix into ≤11 chars
        avail_city = MAX - len(freq_str) - len(prefix)
        city_part = _city_abbrev(city, max(1, avail_city))
        name = city_part + freq_str + prefix
    else:
        # {city} {prefix}
        avail_city = MAX - 1 - len(prefix)        # 1 for space
        city_part = _city_abbrev(city, max(1, avail_city))
        name = f"{city_part} {prefix}"

    return name[:MAX]


# ---------------------------------------------------------------------------
# Contact name construction
# ---------------------------------------------------------------------------

def make_contact_name(prefix: str, tg_id: int, tg_desc: str = "") -> str:
    """
    Build a contact/talkgroup name ≤ MAX_NAME_LEN chars.

    The ID is appended only for short abbreviations (≤3 chars, e.g. WW, NA, IL)
    that need the number for disambiguation.  Longer abbreviations are real words
    that identify themselves ("Parrot", "Disc", "TriSt") — no ID needed.
    Exception: abbreviations that already encode the ID ("TAC310") skip it via
    the endsWith check, regardless of length.
    """
    abbr = tg_abbrev(tg_id, tg_desc)
    if abbr.endswith(str(tg_id)) or len(abbr) > 3:
        name = f"{prefix} {abbr}"
    else:
        name = f"{prefix} {abbr} {tg_id}"
    return name[:MAX_NAME_LEN]


def make_hotspot_contact_name(tg_id: int) -> str:
    """Build a hotspot contact/channel name ≤ MAX_NAME_LEN chars."""
    abbr = tg_abbrev(tg_id)
    if abbr.endswith(str(tg_id)) or len(abbr) > 3:
        return f"HS {abbr}"[:MAX_NAME_LEN]
    return f"HS {abbr} {tg_id}"[:MAX_NAME_LEN]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

class CodeplugBuilder:
    def __init__(self, request: CodeplugRequest, bm_talkgroups: dict[int, str] | None = None):
        self.req = request
        self.bm_talkgroups: dict[int, str] = bm_talkgroups or {}
        self._contacts: dict[str, Contact] = {}  # name → Contact (deduplication)
        self._rx_groups: list[RXGroup] = []
        self._channels: list[Channel] = []
        self._zones: list[Zone] = []

    def build(self, repeaters: list[Repeater]) -> Codeplug:
        # Sort by city for predictable output; stable within a city by frequency
        repeaters_sorted = sorted(repeaters, key=lambda r: (r.city, r.rx_freq))

        # Detect cities with multiple repeaters (need freq suffix in names)
        city_counts: dict[str, int] = {}
        for r in repeaters_sorted:
            city_counts[r.city] = city_counts.get(r.city, 0) + 1

        for rep in repeaters_sorted:
            use_freq = city_counts[rep.city] > 1
            self._process_repeater(rep, use_freq=use_freq)

        if self.req.include_hotspot and self.req.hotspot_talkgroup_ids:
            self._build_hotspot_zone()

        # Renumber everything 1-based
        contacts = list(self._contacts.values())
        codeplug = Codeplug(
            contacts=contacts,
            rx_groups=self._rx_groups,
            channels=self._channels,
            zones=self._zones,
        )
        return codeplug

    # -----------------------------------------------------------------------

    def _process_repeater(self, rep: Repeater, use_freq: bool) -> None:
        """Build contacts, RX group, channels, and zone for one repeater."""
        prefix = network_prefix(rep.network)

        # Use API talkgroups if available, otherwise fall back to network defaults
        tgs = rep.talkgroups if rep.talkgroups else defaults_for_network(rep.network)

        if not tgs:
            return  # Nothing to program

        # --- Contacts ---
        contact_names: list[str] = []
        for tg in tgs:
            # Prefer official BM name over RadioID description
            bm_name = self.bm_talkgroups.get(tg.id, "")
            desc = bm_name or tg.description
            cname = make_contact_name(prefix, tg.id, desc)
            if cname not in self._contacts:
                self._contacts[cname] = Contact(
                    name=cname,
                    dmr_id=tg.id,
                    call_type="Private Call" if tg.id in PRIVATE_CALL_TGS else "Group Call",
                )
            if cname not in contact_names:
                contact_names.append(cname)

        zone_name = make_zone_name(rep.city, rep.rx_freq, rep.network, use_freq)

        # --- RX Group (one per repeater, one contact per talkgroup) ---
        # Currently unused: a single shared RX group works fine when GroupCall
        # Match is Off (the radio hears all traffic on freq/CC/timeslot).
        # Uncomment to generate per-repeater RX groups for GroupCall Match = On.
        #
        # rx_group_name = make_rx_group_name(rep.city, rep.rx_freq, rep.network, use_freq)
        # rx_group = RXGroup(
        #     name=rx_group_name,
        #     contacts=contact_names[:32],
        # )
        # self._rx_groups.append(rx_group)

        # --- Channels (one per talkgroup) ---
        channel_names: list[str] = []
        tg_ids_seen: set[int] = set()
        for tg in tgs:
            bm_name = self.bm_talkgroups.get(tg.id, "")
            desc = bm_name or tg.description
            cname = make_contact_name(prefix, tg.id, desc)
            ch_name = make_channel_name(rep.city, rep.rx_freq, tg.id, tg.timeslot, use_freq, desc)

            # Disambiguate duplicate channel names (shouldn't happen normally)
            base = ch_name
            counter = 2
            while ch_name in [c.name for c in self._channels]:
                ch_name = base[:MAX_NAME_LEN - len(str(counter))] + str(counter)
                counter += 1

            ch = Channel(
                name=ch_name,
                channel_type="Digital",
                rx_freq=rep.rx_freq,
                tx_freq=rep.tx_freq,
                color_code=rep.color_code,
                timeslot=tg.timeslot,
                tx_contact=cname,
                rx_group="None",
                power=self.req.tx_power,
                dmr_id=self.req.callsign,
            )
            self._channels.append(ch)
            channel_names.append(ch_name)
            tg_ids_seen.add(tg.id)

        # --- Disconnect channel (TG 4000) ---
        # Always add a disconnect channel unless TG 4000 is already present.
        # TG 4000 is "Disconnect" in the BrandMeister catalog and disconnects
        # reflectors/talkgroups on both BrandMeister and DMR-MARC.
        DISCONNECT_TG = 4000
        if DISCONNECT_TG not in tg_ids_seen:
            disc_cname = make_contact_name(prefix, DISCONNECT_TG, "Disconnect")
            if disc_cname not in self._contacts:
                self._contacts[disc_cname] = Contact(
                    name=disc_cname,
                    dmr_id=DISCONNECT_TG,
                    call_type="Group Call",
                )
            disc_ch_name = make_channel_name(rep.city, rep.rx_freq, DISCONNECT_TG, 2, use_freq, "Disconnect")
            # Disambiguate
            base = disc_ch_name
            counter = 2
            while disc_ch_name in [c.name for c in self._channels]:
                disc_ch_name = base[:MAX_NAME_LEN - len(str(counter))] + str(counter)
                counter += 1

            self._channels.append(Channel(
                name=disc_ch_name,
                channel_type="Digital",
                rx_freq=rep.rx_freq,
                tx_freq=rep.tx_freq,
                color_code=rep.color_code,
                timeslot=2,
                tx_contact=disc_cname,
                rx_group="None",
                power=self.req.tx_power,
                dmr_id=self.req.callsign,
            ))
            channel_names.append(disc_ch_name)

        # --- Zone ---
        self._zones.append(Zone(name=zone_name, channels=channel_names[:64]))

    # -----------------------------------------------------------------------

    def _build_hotspot_zone(self) -> None:
        """Add a Hotspot zone using the user-selected talkgroups."""
        rx_freq = self.req.hotspot_freq
        tx_freq = self.req.hotspot_freq  # hotspot is simplex

        contact_names: list[str] = []
        channel_names: list[str] = []
        hs_tg_ids_seen: set[int] = set()

        for tg_id in self.req.hotspot_talkgroup_ids:
            cname = make_hotspot_contact_name(tg_id)
            if cname not in self._contacts:
                self._contacts[cname] = Contact(
                    name=cname,
                    dmr_id=tg_id,
                    call_type="Private Call" if tg_id in PRIVATE_CALL_TGS else "Group Call",
                )
            if cname not in contact_names:
                contact_names.append(cname)

            ch_name = cname  # hotspot channel name matches contact name
            if ch_name not in [c.name for c in self._channels]:
                self._channels.append(Channel(
                    name=ch_name,
                    channel_type="Digital",
                    rx_freq=rx_freq,
                    tx_freq=tx_freq,
                    color_code=1,
                    timeslot=2,
                    tx_contact=cname,
                    rx_group="None",
                    power="Low",
                    tx_admit="Always",
                    dmr_id=self.req.callsign,
                ))
                channel_names.append(ch_name)
            hs_tg_ids_seen.add(tg_id)

        # --- Hotspot disconnect channel (TG 4000) ---
        DISCONNECT_TG = 4000
        if DISCONNECT_TG not in hs_tg_ids_seen:
            disc_cname = make_hotspot_contact_name(DISCONNECT_TG)
            if disc_cname not in self._contacts:
                self._contacts[disc_cname] = Contact(
                    name=disc_cname,
                    dmr_id=DISCONNECT_TG,
                    call_type="Group Call",
                )
            disc_ch_name = disc_cname  # same naming convention
            if disc_ch_name not in [c.name for c in self._channels]:
                self._channels.append(Channel(
                    name=disc_ch_name,
                    channel_type="Digital",
                    rx_freq=rx_freq,
                    tx_freq=tx_freq,
                    color_code=1,
                    timeslot=2,
                    tx_contact=disc_cname,
                    rx_group="None",
                    power="Low",
                    tx_admit="Always",
                    dmr_id=self.req.callsign,
                ))
                channel_names.append(disc_ch_name)

        if not channel_names:
            return

        # hs_rx_group = RXGroup(name="Hotspot", contacts=contact_names[:32])
        # self._rx_groups.append(hs_rx_group)
        self._zones.append(Zone(name="Hotspot", channels=channel_names[:64]))
