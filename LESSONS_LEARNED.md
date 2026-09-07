# Lessons Learned — DMR, BrandMeister, RadioID, and the DM-32UV

## DMR Fundamentals

### Codeplug Build Order (Bottom-Up)
The CSV files must be imported in this exact order:
1. `dmr_id.csv` — the radio's own Radio ID table; channels reference it by name
2. `talk_groups.csv` — talkgroups; channels reference these via TX Contact
3. `rx_group_lists.csv` — receive group lists (talkgroup filters, usually unused)
4. `channels.csv` — channels reference contacts and RX groups by name
5. `zones.csv` — zones reference channels by name

If you import channels before contacts, the TX Contact field silently becomes None.
**However**: this dependency only applies to named references. With `GroupCall Match = Off`
and `rx_group = "None"`, channels work correctly without any contacts or RX groups imported.

### Contacts CSV Is a Personal Address Book
The `digital_contacts.csv` file is NOT for talkgroups. It is a lookup table for
**private calls** — it stores individual ham operators' DMR IDs and callsigns so the
radio can display their name/callsign when they call you. It has nothing to do with
which talkgroups you monitor or transmit to.

The working contacts file (`tst.csv`) contains only ham operator entries with
`Remark = "Private Call"`. Talkgroup entries are not needed here.

### TX Contact Field
The `TX Contact` field in a channel row specifies **what talkgroup the radio calls
when you press PTT**. It is a named reference to an entry in the Talk Group list
(separate from the CSV contacts / personal address book). With the current setup
it stores a string name like "BM WW 91".

### RX Group List
The RX Group List filters which incoming group calls open the squelch on a channel.
- With `GroupCall Match = Off`: RX Group is completely ignored. Radio hears all
  group calls on the correct frequency/color code/timeslot. This is the recommended
  setting for ham use.
- With `GroupCall Match = On`: Radio only opens squelch for talkgroups listed in
  the channel's assigned RX group.
- A channel can reference `None` as its RX group — this is valid and means no filtering.

### The Channel "DMR ID" Column Is a Name, Not a Number
This one cost a user a working codeplug and took a while to find.

The `DMR ID` column in `channels.csv` is a **name reference into the radio's
Radio ID table** (`DMR-ID.csv`: `No., Radio ID, Radio Name`). It is not the
numeric DMR ID. A factory-fresh CPS document ships that table pre-populated
with placeholders — `Radio 1`, `Radio 2`, and so on.

Write a callsign there without also supplying the Radio ID table and every
channel references a name the CPS has never seen. The channels do not bind.
Nothing is reported. The damage only becomes visible one step later, when
`zones.csv` is imported and the zone members have nothing to resolve against,
so the radio shows `Null Ch.` for everything.

It is invisible to whoever built the codeplug, because their own CPS document
already has a Radio ID entry named after their callsign. Always generate
`dmr_id.csv` and import it first.

### TX Admit: "Channel Idle" / "Allow TX"
The DM-32 wire values are `Channel Idle` and `Allow TX`. `Color Code Free` is
the **AnyTone** spelling and the DM-32 CPS does not accept it. Confirmed
against a CPS v1.60 export, which only ever emits those two values.

### Power Ladder: High / Middle / Low
Not "Medium". The CPS writes `Middle`.

### Verifying the CSV Format
The CPS is closed source and reports nothing on a bad import — it accepts the
file, drops the rows it cannot parse, and lets you discover the damage on the
radio. The only reliable way to check the format is to diff generated output
against a real CPS export. Two useful references:

- `github.com/pskillen/codeplug-tool` — `sample-exports/Baofeng DM32 CPS v1.60/`
  has genuine exports of all eight CSV files, plus a documented column reference
- `github.com/mrshadowsys/Quansheng-DM32UV-Chirp-to-DM32-channel-list-` — a
  working CHIRP converter, useful as a second opinion on channel columns

`tests/test_dm32_format.py` encodes what those exports establish. Extend it
before changing anything in `csv_export.py`.

### RX Group Name Limit: 11 Characters
The DM-32UV CPS silently drops any RX Group List reference in a channel if the
group's name exceeds 11 characters, writing `None` instead. This is a CPS bug,
not a radio limitation. Always keep RX group names ≤ 11 chars.

### Channel Name Limit: 16 Characters
Channel names are hard-capped at 16 characters. The DM-32UV displays this on its
2" LCD screen.

### Zone Name Limit: 16 Characters
Zone names are also 16 characters max (display only, not referenced by other tables).

### TX Admit (values)
- `Channel Idle`: radio transmits only when the channel is not in use.
- `Allow TX`: radio transmits regardless (used for hotspot channels).
- Earlier notes here claimed the CPS accepted `Color Code Free` / `Always` and
  normalized them on export. A v1.60 export shows only `Channel Idle` and
  `Allow TX`, so those earlier values were wrong — see the TX Admit note above.

### Color Code
Analogous to CTCSS in analog. Must match the repeater's color code (0–15).
Mismatch = no communication. Most repeaters use CC1.

### Time Slot
DMR is TDMA — two time slots (TS1, TS2) share a single frequency.
- BrandMeister convention: TS1 = wide-area (WW, NA, state); TS2 = local/tactical
- MARC/Tristate convention: TS1 = regional (TriState); TS2 = local, WW, NA

### Hotspot Channels
- TX freq = RX freq (simplex)
- TX Admit = Always
- Power = Low
- Color Code = 1 (standard for BM hotspots)
- Time Slot = 2 (BM hotspot convention)

---

## RadioID.net

### API Base
`https://radioid.net/api/`

### Key Endpoints
- `GET /dmr/user/?id={dmr_id}` — look up a user by DMR ID
- `GET /dmr/repeater/` — search repeaters (paginated, 200/page)
  - Params: `state`, `city`, `country`
  - Filter by `ipsc_network` client-side (not a query param)

### The ipsc_network Problem
The `ipsc_network` field is **self-reported by the repeater owner** and is highly
unreliable for BrandMeister identification in the Chicago/Midwest area:

- Many repeaters are labeled "BrandMeister" or "Brandmeister" in RadioID but are
  NOT registered on the BrandMeister network at all.
- Some true BM repeaters are labeled "BM" (short form) — these were previously
  being filtered out because the alias list didn't include "BM".
- The BrandMeister API is the authoritative source. Cross-reference always.

### Network Name Variations in RadioID
All of these refer to the same BrandMeister network:
- "BrandMeister", "Brandmeister", "BM"

The builder's `NETWORK_PREFIX` and the CLI's `network_aliases` both normalize these.

### City Search Is Exact String Match
RadioID has no radius/distance search. Searching "Chicago" only returns repeaters
literally registered with city="Chicago". Suburbs (Skokie, Hickory Hills, Oak Park,
etc.) are separate entries. State-level fallback is used when city returns < 3 results,
but this brings in distant repeaters (Murphysboro, Peoria, etc.).

**Solution in web UI**: Let the user select from a list of discovered repeaters
rather than automatically including all state results.

### Repeater Offset Parsing
The `offset` field comes as a string like "+5.000" or "-0.600". Parse as float.
TX freq = RX freq + offset. Some historical codeplug data had wrong TX frequencies
due to incorrect offset values in RadioID.

---

## BrandMeister API

### Base URL
`https://api.brandmeister.network/v2`

### Authentication
Bearer token in `Authorization` header. Key stored in `~/.config/dmr-codeplug.json`.
**Never commit the API key to source control.**

### Key Endpoints Used
- `GET /v2/device/` — returns all ~32,000 BM devices (repeaters + hotspots) in one call
- `GET /v2/talkgroup/` — returns `{str(tg_id): name}` for ~1,750 official talkgroups

### Distinguishing Repeaters from Hotspots
In the `/v2/device/` response:
- **Hotspot**: `tx == rx` (simplex, same frequency both ways), `status = 4` (DMO)
- **Repeater**: `tx != rx` (offset), `status = 3` (Both Slots Linked)

Do not confuse the two. A hotspot operator's callsign may appear in the device list
but that doesn't mean they have a repeater.

### Device Status Values
- `3` = "Both Slots Linked" — active repeater
- `4` = "DMO" — Direct Mode Operation / simplex / hotspot

### BM Device ID = DMR ID
The `id` field in a BM device record is the device's DMR radio ID (e.g., 3179879
for KQ9I's hotspot). This is useful for cross-referencing.

### Caching Strategy
Both the device list and talkgroup catalog are cached indefinitely to avoid
abusing the BM API. Use `--refresh-bm` flag to force a fresh download.
Cache files: `~/.config/dmr-codeplug-bm-devices.json` and
`~/.config/dmr-codeplug-bm-talkgroups.json`.

### Talkgroup Catalog Coverage
The BM catalog has ~1,750 named talkgroups. Many local/regional TGs used by
specific repeaters are NOT in the catalog and will fall back to the RadioID
description or the `TG_ABBREV` dictionary in `defaults.py`.

---

## DM-32UV CPS Quirks

### Import Order Is Critical
Always import: contacts → RX groups → channels → zones.

### Silent Failures
The CPS silently writes `None` instead of erroring when:
- A referenced contact name doesn't exist in the loaded contacts list
- An RX Group name exceeds 11 characters
- A referenced RX Group doesn't exist

**Always verify import results by exporting back from CPS and comparing.**

### TX Admit Normalization
CPS exports all digital channels as `TX Admit = Always` regardless of what was
imported. "Color Code Free" is accepted on import but not preserved.

### GroupCall Match and PrivateCall Match Settings
Both found in: Settings → Radio Settings → (18) PrivateCall Match / (19) GroupCall Match
- **PrivateCall Match = On**: Only respond to private calls addressed to your DMR ID.
- **GroupCall Match = Off**: Hear ALL group calls on matching freq/CC/timeslot,
  regardless of talkgroup. Recommended for ham use.
- **GroupCall Match = On**: Only hear talkgroups listed in the channel's RX Group.

### Multiple DMR IDs
The DM-32UV supports multiple DMR IDs (one per channel). Useful for commercial vs
amateur use on the same radio.

---

## Chicago-Area Specific Knowledge

### True BM Repeaters (confirmed via BM API)
As of development time, the following are confirmed on BrandMeister in the
greater Chicago/NW Indiana area (tx≠rx, status=Both Slots Linked):
- **N9ZD** — Oak Forest, IL (443.275 MHz, CC1)
- **KT9Y** — Trivoli, IL (442.100 MHz, CC12) — farther away
- **WF1RES** — O'Fallon, IL (farther south)
- Various others identified via BM API verification

Most repeaters labeled "BrandMeister" in RadioID for the Chicago area are actually
on DMR-MARC, Tristate, or ChicagoLand-CC networks.

### Network Reality
The Chicago area is heavily DMR-MARC dominated (Motorola's Schaumburg campus is
the hub). Many repeaters were historically labeled as BrandMeister in RadioID
when they're actually MARC-based.
