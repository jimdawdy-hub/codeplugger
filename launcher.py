#!/usr/bin/env python3
"""
CODEPLUGGER launcher.

Starts the web server on localhost:8000, waits for it to be ready,
then opens the default browser. Used as the PyInstaller entry point
and can also be run directly from source.

Usage:
    python launcher.py          # default port 8000
    python launcher.py 8001     # custom port
"""

import sys
import time
import threading
import webbrowser
import urllib.request
import urllib.error


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Poll until the server responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    # Import here so PyInstaller hidden-import collection picks them up
    import uvicorn
    from web.app import app

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    print(f"Starting CODEPLUGGER on http://localhost:{port} ...")
    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    if wait_for_server(port):
        webbrowser.open(f"http://localhost:{port}")
    else:
        print(f"Server did not start in time — open http://localhost:{port} manually.")

    try:
        t.join()
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
