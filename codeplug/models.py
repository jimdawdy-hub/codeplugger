from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Talkgroup:
    id: int
    timeslot: int           # 1 or 2
    description: str = ""


@dataclass
class Repeater:
    callsign: str
    city: str
    state: str
    country: str
    rx_freq: float          # MHz
    offset: float           # signed offset in MHz, e.g. +5.0 or -0.600
    color_code: int
    network: str            # e.g. "BrandMeister", "DMR-MARC", "ChicagoLand-CC"
    status: str             # "on-air", "off-air", etc.
    talkgroups: list[Talkgroup] = field(default_factory=list)
    locator: Optional[int] = None

    @property
    def tx_freq(self) -> float:
        return round(self.rx_freq + self.offset, 5)


@dataclass
class Contact:
    """A digital contact (talkgroup or private call) for the contacts list."""
    name: str       # exactly as referenced by Channel.tx_contact
    dmr_id: int
    call_type: str  # "Group Call" or "Private Call"


@dataclass
class Channel:
    name: str           # max 16 chars
    channel_type: str   # "Digital" or "Analog"
    rx_freq: float
    tx_freq: float
    color_code: int     # 0 for analog
    timeslot: int       # 1 or 2
    tx_contact: str     # must exactly match a Contact.name
    rx_group: str       # must exactly match an RXGroup.name, or "" for analog
    power: str = "High"
    tx_admit: str = "Color Code Free"  # Digital default
    squelch: int = 3
    dmr_id: str = ""    # user callsign string

    # Analog-only fields
    ctcss_decode: str = "None"
    ctcss_encode: str = "None"


@dataclass
class RXGroup:
    name: str
    contacts: list[str]  # Contact.name values, max 32


@dataclass
class Zone:
    name: str
    channels: list[str]  # Channel.name values, max 64


@dataclass
class CodeplugRequest:
    dmr_id: int
    callsign: str           # populated from RadioID lookup
    city: str
    state: str
    country: str = "United States"
    networks: list[str] = field(default_factory=lambda: ["BrandMeister", "DMR-MARC"])
    max_repeaters: int = 25
    tx_power: str = "High"
    # Hotspot config
    include_hotspot: bool = True
    hotspot_freq: float = 433.550
    hotspot_talkgroup_ids: list[int] = field(default_factory=list)


@dataclass
class Codeplug:
    contacts: list[Contact]
    rx_groups: list[RXGroup]
    channels: list[Channel]
    zones: list[Zone]

    # Radio limits for DM-32UV
    MAX_CHANNELS = 4000
    MAX_ZONES = 250
    MAX_CONTACTS = 1000
    MAX_RX_GROUPS = 250
    MAX_CHANNELS_PER_ZONE = 64
    MAX_CONTACTS_PER_GROUP = 32

    def validate(self) -> list[str]:
        warnings = []
        if len(self.channels) > self.MAX_CHANNELS:
            warnings.append(f"Channel count {len(self.channels)} exceeds radio limit {self.MAX_CHANNELS}")
        if len(self.zones) > self.MAX_ZONES:
            warnings.append(f"Zone count {len(self.zones)} exceeds radio limit {self.MAX_ZONES}")
        if len(self.contacts) > self.MAX_CONTACTS:
            warnings.append(f"Contact count {len(self.contacts)} exceeds radio limit {self.MAX_CONTACTS}")
        if len(self.rx_groups) > self.MAX_RX_GROUPS:
            warnings.append(f"RX group count {len(self.rx_groups)} exceeds radio limit {self.MAX_RX_GROUPS}")
        for z in self.zones:
            if len(z.channels) > self.MAX_CHANNELS_PER_ZONE:
                warnings.append(f"Zone '{z.name}' has {len(z.channels)} channels, max is {self.MAX_CHANNELS_PER_ZONE}")
        for g in self.rx_groups:
            if len(g.contacts) > self.MAX_CONTACTS_PER_GROUP:
                warnings.append(f"RX group '{g.name}' has {len(g.contacts)} contacts, max is {self.MAX_CONTACTS_PER_GROUP}")
        return warnings
