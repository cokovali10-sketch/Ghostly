#!/usr/bin/env python3
"""
Ghostly Analytics - Double-click launcher.

This script provides a simple double-click entry point for starting
Ghostly Analytics. It opens a browser window and starts the server
with sensible defaults.

Just double-click this file to launch Ghostly!
"""

import os
import signal
import sys
import webbrowser
import time
from pathlib import Path

BANNER = r"""
   _____ _               _                    _
  / ____| |             | |                  | |
 | |  __| |__   ___  ___| | __ _ _   _  __ _| |
 | | |_ | '_ \ / _ \/ __| |/ _` | | | |/ _` | |
 | |__| | | | |  __/ (__| | (_| | |_| | (_| | |
  \_____|_| |_|\___|\___|_|\__,_|\__, |\__, |_|
                                   __/ | __/ |
                                  |___/ |___/
"""


def is_frozen() -> bool:
    """Check if running as a PyInstaller frozen executable."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_db_path() -> str:
    """Determine database path based on execution context."""
    if is_frozen():
        db_dir = Path(os.path.dirname(sys.executable))
    else:
        db_dir = Path(__file__).parent
    return str(db_dir / "ghostly.db")


def open_browser(host: str, port: int, delay: float = 2.0) -> None:
    """Open the browser after a short delay."""
    def _open():
        time.sleep(delay)
        webbrowser.open(f"http://{host}:{port}")
    
    import threading
    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main() -> None:
    """Launch Ghostly Analytics."""
    host = os.getenv("GHOSTLY_HOST", "127.0.0.1")
    port = int(os.getenv("GHOSTLY_PORT", "8080"))
    db_path = os.getenv("GHOSTLY_DB", get_db_path())

    print(BANNER)
    print("  Starting Ghostly Analytics...")
    print(f"  Dashboard: http://{host}:{port}")
    print(f"  Database:  {db_path}")
    print()

    open_browser(host, port)

    try:
        from ghostly.__main__ import main as ghostly_main
        sys.argv = [
            "ghostly",
            "--port", str(port),
            "--host", host,
            "--db", db_path,
            "--no-browser",
        ]
        ghostly_main()
    except KeyboardInterrupt:
        print("\n  Ghostly stopped. Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n  Error starting Ghostly: {e}")
        print("  Make sure dependencies are installed:")
        print("    pip install -e .")
        print("  Or for standalone use:")
        print("    pip install aiohttp aiosqlite")
        input("\n  Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: (print("\n  Ghostly stopped!"), sys.exit(0)))
    main()
