#!/usr/bin/env python3.12
"""
CODEPLUGGER — Repeater Database Import Tool

Imports repeater data from multiple sources into data/repeaters.db:
  - Google Earth KML ZIP (RepeaterBook data for all 50 US states)
  - PDF repeater directories (Iowa, Minnesota, WPRC, Oregon, Rochester, etc.)

Usage:
    python3.12 import_data.py                         # import everything found
    python3.12 import_data.py --kml-zip FILE.zip      # specific KML ZIP
    python3.12 import_data.py --states IL IN          # KML: only these states
    python3.12 import_data.py --pdfs-only             # skip KML
    python3.12 import_data.py --stats                 # show DB stats only
"""

import argparse
import sys
import pathlib
import glob

# Ensure project root is on path
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from codeplug.repeater_db import get_connection, get_stats, list_states
from codeplug.kml_import import import_kml_zip
from codeplug.pdf_import import import_all_pdfs, import_pdf

PROJECT_ROOT = pathlib.Path(__file__).parent


def find_kml_zip() -> pathlib.Path | None:
    """Find any ZIP file in the project root that looks like the Google Drive download."""
    for z in PROJECT_ROOT.glob("drive-download*.zip"):
        return z
    for z in PROJECT_ROOT.glob("*.zip"):
        return z
    return None


def show_stats():
    conn = get_connection()
    s = get_stats(conn)
    states = list_states(conn)
    conn.close()
    print(f"\nRepeater Database Stats")
    print(f"  Total records: {s['total']:,}")
    print(f"  States/territories: {s['states']}")
    print(f"  Sources: {s['sources']}")
    print(f"  By mode:")
    for mode, cnt in s["by_mode"].items():
        print(f"    {mode:12s}  {cnt:,}")
    if states:
        print(f"\n  States in DB ({len(states)}):")
        for i in range(0, len(states), 6):
            print("    " + "  ".join(f"{s:<20}" for s in states[i:i+6]))


def main():
    parser = argparse.ArgumentParser(description="Import repeater data into local database")
    parser.add_argument("--kml-zip",   type=str, help="Path to Google Earth KML ZIP file")
    parser.add_argument("--states",    nargs="+", metavar="STATE",
                        help="Import only these states from KML (e.g. Illinois Indiana)")
    parser.add_argument("--pdf",       type=str, nargs="+", metavar="PDF",
                        help="Import specific PDF file(s)")
    parser.add_argument("--pdf-dir",   type=str, help="Import all PDFs in a directory")
    parser.add_argument("--pdfs-only", action="store_true", help="Skip KML import")
    parser.add_argument("--kml-only",  action="store_true", help="Skip PDF import")
    parser.add_argument("--stats",     action="store_true", help="Show DB stats and exit")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    total = 0

    # --- KML import ---
    if not args.pdfs_only:
        zip_path = pathlib.Path(args.kml_zip) if args.kml_zip else find_kml_zip()
        if zip_path and zip_path.exists():
            print(f"\nImporting KML from: {zip_path.name}")
            inserted = import_kml_zip(
                zip_path,
                states=args.states,
                verbose=True,
            )
            print(f"  → KML total inserted: {inserted:,}")
            total += inserted
        else:
            print("\nNo KML ZIP found — skipping KML import.")
            print("  Download from: https://drive.google.com/drive/folders/10Lvzkdtox8vG7iNkpQHSOIUfn8yUNV5b")
            print("  Then re-run this script.")

    # --- PDF import ---
    if not args.kml_only:
        pdf_paths: list[pathlib.Path] = []

        if args.pdf:
            pdf_paths = [pathlib.Path(p) for p in args.pdf]
        elif args.pdf_dir:
            pdf_paths = list(pathlib.Path(args.pdf_dir).glob("*.pdf"))
        else:
            # Auto-discover PDFs in project root
            pdf_paths = list(PROJECT_ROOT.glob("*.pdf"))

        if pdf_paths:
            print(f"\nImporting {len(pdf_paths)} PDF(s):")
            for pdf in sorted(pdf_paths):
                total += import_pdf(pdf, verbose=True)
        else:
            print("\nNo PDFs found — skipping PDF import.")

    print(f"\nDone. Total new records inserted this run: {total:,}")
    show_stats()


if __name__ == "__main__":
    main()
