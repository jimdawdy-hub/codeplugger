#!/usr/bin/env python3
"""
DMR Codeplug Generator — CLI

Usage:
    python main.py --dmr-id 3122107 --city Chicago --state Illinois
    python main.py --dmr-id 3122107 --city Aurora --state Illinois --networks BrandMeister DMR-MARC
    python main.py --dmr-id 3122107 --city Chicago --state Illinois --hotspot --hs-tgs 91 93 3117 9 310 312
"""

import argparse
import sys
from codeplug import radioid, csv_export, brandmeister
from codeplug.builder import CodeplugBuilder
from codeplug.models import CodeplugRequest
from codeplug.defaults import BM_HOTSPOT_TGS


def main():
    parser = argparse.ArgumentParser(
        description="Generate a DM-32UV codeplug from RadioID.net data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dmr-id",   type=int, required=True, help="Your DMR ID (e.g. 3122107)")
    parser.add_argument("--callsign", type=str, default="",    help="Override callsign (auto-looked up if omitted)")
    parser.add_argument("--city",      type=str, default="",   help="Primary city to search for repeaters")
    parser.add_argument("--state",     type=str, default="",   help="State for --city (full name, e.g. 'Illinois')")
    parser.add_argument("--locations", nargs="+", default=[],
                        metavar="CITY,STATE",
                        help="Additional locations as 'City,State' pairs, e.g. 'Dyer,Indiana' 'Gary,Indiana'")
    parser.add_argument("--country",   type=str, default="United States")
    parser.add_argument("--networks", nargs="+",
                        default=["BrandMeister", "DMR-MARC"],
                        help="Networks to include (BrandMeister DMR-MARC ChicagoLand-CC Tristate)")
    parser.add_argument("--max",      type=int, default=25,    help="Max repeaters to include")
    parser.add_argument("--power",    type=str, default="High", choices=["High", "Low", "Medium"])
    parser.add_argument("--hotspot",  action="store_true",     help="Include a hotspot zone")
    parser.add_argument("--hs-freq",  type=float, default=433.550, help="Hotspot simplex frequency (default 433.550)")
    parser.add_argument("--hs-tgs",   type=int, nargs="+", default=[],
                        help="Hotspot talkgroup IDs (e.g. 91 93 3117 9 310 312)")
    parser.add_argument("--list-hs-tgs", action="store_true", help="List available hotspot TGs and exit")
    parser.add_argument("--out",      type=str, default="output", help="Output directory for CSV files")
    parser.add_argument("--dry-run",    action="store_true", help="Show summary without writing files")
    parser.add_argument("--refresh-bm", action="store_true", help="Force re-download of BrandMeister device list")

    args = parser.parse_args()

    # List hotspot TGs and exit
    if args.list_hs_tgs:
        print("\nAvailable Brandmeister hotspot talkgroups:")
        current_group = None
        for tg in BM_HOTSPOT_TGS:
            if tg["group"] != current_group:
                current_group = tg["group"]
                print(f"\n  [{current_group}]")
            print(f"    {tg['id']:>7}  {tg['name']}")
        print()
        return

    # --- Step 1: Look up user ---
    print(f"\nLooking up DMR ID {args.dmr_id}...")
    user = radioid.lookup_user(args.dmr_id)
    if user is None:
        print(f"ERROR: DMR ID {args.dmr_id} not found in RadioID.net")
        sys.exit(1)

    callsign = args.callsign or user.get("callsign", "")
    if not callsign:
        print("ERROR: Could not determine callsign. Use --callsign to override.")
        sys.exit(1)

    print(f"  Found: {callsign} — {user.get('fname', '')} {user.get('name', '')} "
          f"({user.get('city', '')}, {user.get('state', '')})")

    # --- Step 2: Search for repeaters ---
    # Map common network aliases for the API query
    network_aliases = {
        "BrandMeister": ["BrandMeister", "Brandmeister", "BM"],
        "DMR-MARC":     ["DMR-MARC"],
        "ChicagoLand-CC": ["ChicagoLand-CC", "Chicagoland-CC"],
        "Tristate":     ["Tristate", "TriState"],
    }
    api_networks: list[str] = []
    for n in args.networks:
        api_networks.extend(network_aliases.get(n, [n]))

    # Build list of (city, state) locations to search
    locations: list[tuple[str, str]] = []
    if args.city and args.state:
        locations.append((args.city, args.state))
    elif args.city or args.state:
        print("ERROR: --city and --state must be used together.")
        sys.exit(1)
    for loc in args.locations:
        if "," not in loc:
            print(f"ERROR: --locations entry '{loc}' must be in 'City,State' format.")
            sys.exit(1)
        city, state = loc.split(",", 1)
        locations.append((city.strip(), state.strip()))
    if not locations:
        print("ERROR: Provide at least one location via --city/--state or --locations.")
        sys.exit(1)

    # Distribute --max across unique states so one state can't monopolise the budget.
    # City results are kept first; state fallback fills remaining slots per state.
    unique_states = list(dict.fromkeys(state for _, state in locations))
    state_max = args.max // len(unique_states)
    state_remainder = args.max % len(unique_states)
    state_limits: dict[str, int] = {
        s: state_max + (1 if i < state_remainder else 0)
        for i, s in enumerate(unique_states)
    }

    state_repeaters: dict[str, list[Repeater]] = {s: [] for s in unique_states}
    seen_callsigns: set[str] = set()
    state_searched: set[str] = set()

    # --- Pass 1: city searches ---
    for city, state in locations:
        print(f"\nSearching for repeaters in {city}, {state}...")
        found = radioid.search_repeaters(
            state=state,
            city=city,
            country=args.country,
            networks=api_networks,
        )
        added = 0
        for r in found:
            if r.callsign not in seen_callsigns:
                state_repeaters[state].append(r)
                seen_callsigns.add(r.callsign)
                added += 1
        print(f"  Added {added} new repeater(s) for {state}")

    # --- Pass 2: state fallbacks for states with < 3 results ---
    for city, state in locations:
        current_count = len(state_repeaters[state])
        if current_count < 3 and state not in state_searched:
            print(f"\n  Only {current_count} results for {state}, searching by state...")
            state_found = radioid.search_repeaters(
                state=state,
                country=args.country,
                networks=api_networks,
            )
            state_searched.add(state)
            added = 0
            for r in state_found:
                if r.callsign not in seen_callsigns:
                    state_repeaters[state].append(r)
                    seen_callsigns.add(r.callsign)
                    added += 1
            print(f"  Added {added} state-wide repeater(s) for {state}")

    # --- Assemble final list, applying per-state caps ---
    repeaters: list[Repeater] = []
    for state in unique_states:
        limit = state_limits[state]
        kept = state_repeaters[state][:limit]
        repeaters.extend(kept)
        if len(state_repeaters[state]) > limit:
            print(f"  {state}: kept {len(kept)} of {len(state_repeaters[state])} (cap {limit})")

    # Sort by city for predictable output; stable within a city by frequency
    repeaters = sorted(repeaters, key=lambda r: (r.city, r.rx_freq))

    if not repeaters:
        print("ERROR: No on-air repeaters found. Try adjusting --city, --state, or --networks.")
        sys.exit(1)

    # --- Step 2b: Cross-reference with BrandMeister API ---
    bm_index: dict = {}
    bm_talkgroups: dict[int, str] = {}
    bm_key = brandmeister._load_api_key()
    if bm_key:
        print("\nVerifying networks against BrandMeister API...")
        devices = brandmeister.get_all_devices(bm_key, force_refresh=args.refresh_bm)
        bm_talkgroups = brandmeister.get_all_talkgroups(bm_key, force_refresh=args.refresh_bm)
        if bm_talkgroups:
            print(f"  BM talkgroup catalog loaded ({len(bm_talkgroups)} talkgroups)")
        if devices:
            bm_index = brandmeister.build_repeater_index(devices)
            print(f"  BM repeater index loaded ({len(bm_index)} unique repeater callsigns)")
            for r in repeaters:
                bm_network_names = {"brandmeister", "bm"}
                claimed_bm = r.network.lower() in bm_network_names
                actually_bm = brandmeister.is_on_brandmeister(r.callsign, bm_index)
                if actually_bm and not claimed_bm:
                    print(f"  ✓  {r.callsign}: confirmed on BM — correcting network label "
                          f"(was '{r.network}')")
                    r.network = "BrandMeister"
                elif claimed_bm and not actually_bm:
                    print(f"  ⚠  {r.callsign}: RadioID says BrandMeister but not found in BM "
                          f"repeater registry (keeping as-is)")
        else:
            print("  Could not reach BrandMeister API — skipping verification.")

    print(f"\n  Found {len(repeaters)} repeater(s):")
    for r in repeaters:
        tg_count = len(r.talkgroups)
        tg_info = f"{tg_count} TGs from API" if tg_count else "using defaults"
        bm_verified = "✓BM" if brandmeister.is_on_brandmeister(r.callsign, bm_index) else "   "
        print(f"    {r.callsign:10s}  {r.city:20s}  {r.network:20s}  "
              f"{r.rx_freq:.5f}  CC{r.color_code}  {bm_verified}  [{tg_info}]")

    # --- Step 3: Build request ---
    primary_city, primary_state = locations[0] if locations else ("", "")
    req = CodeplugRequest(
        dmr_id=args.dmr_id,
        callsign=callsign,
        city=primary_city,
        state=primary_state,
        country=args.country,
        networks=args.networks,
        max_repeaters=args.max,
        tx_power=args.power,
        include_hotspot=args.hotspot,
        hotspot_freq=args.hs_freq,
        hotspot_talkgroup_ids=args.hs_tgs,
    )

    # --- Step 4: Build codeplug ---
    print("\nBuilding codeplug...")
    builder = CodeplugBuilder(req, bm_talkgroups=bm_talkgroups)
    codeplug = builder.build(repeaters)

    # --- Step 5: Validate ---
    warnings = codeplug.validate()
    for w in warnings:
        print(f"  WARNING: {w}")

    print(f"\n  Contacts:  {len(codeplug.contacts)}")
    print(f"  RX Groups: {len(codeplug.rx_groups)}")
    print(f"  Channels:  {len(codeplug.channels)}")
    print(f"  Zones:     {len(codeplug.zones)}")

    if codeplug.zones:
        print("\n  Zones:")
        for z in codeplug.zones:
            print(f"    {z.name:30s}  {len(z.channels):3d} channels")

    # --- Step 6: Write output ---
    if args.dry_run:
        print("\n[dry-run] Skipping file output.")
        return

    print(f"\nWriting CSV files to '{args.out}/'...")
    csv_export.write_to_directory(codeplug, args.out)
    print("\nDone. Import the files into the DM-32UV CPS in this order:")
    print("  1. talk_groups.csv        (Talk Groups — REQUIRED for TX Contact lookups)")
    print("  2. rx_group_lists.csv     (Digital RX Groups)")
    print("  3. channels.csv           (Channels)")
    print("  4. zones.csv              (Zones)")
    print("\nNote: digital_contacts.csv is NOT generated — it is only needed for")
    print("private-call contacts (ham operators). Talkgroup lookups use Talk Groups.csv.")


if __name__ == "__main__":
    main()
