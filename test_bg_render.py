#!/usr/bin/env python3
"""Quick test to verify render_png works with background enabled."""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import logging

# Setup path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.web_render import render_png, RenderParams

logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")

# Test parameters: 3-hour rolling window, background enabled
now_utc = datetime.now(timezone.utc)
tz_local = datetime.now().astimezone().tzinfo or timezone.utc

# Default: last 3 hours
end_local = now_utc.astimezone(tz_local)
start_local = (end_local - timedelta(hours=3))

params = RenderParams(
    taker_name="Test Tomador",
    lat0=-15.5,  # Brasília
    lon0=-47.9,
    mode=1,
    start_local=start_local,
    end_local=end_local,
    dynamic_start=False,
    dynamic_end=False,
    initial_load_hours=3,
    background=True,  # Enable IR overlay
    thumb=False,
)

settings_path = project_root / "config" / "settings.yaml"

print(f"Starting render test with background={params.background}")
print(f"Time range: {start_local} to {end_local}")
print(f"Settings path: {settings_path}")

try:
    png_bytes, metadata, headers = render_png(settings_path=settings_path, params=params)
    print(f"\n✓ Render succeeded!")
    print(f"  PNG size: {len(png_bytes)} bytes")
    print(f"  Flashes: {metadata.flashes_count}")
    print(f"  Events: {metadata.events_count}")
    print(f"  Data source: {headers.get('X-Data-Source', 'unknown')}")
    print(f"  Background applied: {headers.get('X-Background-Applied', 'unknown')}")
    print(f"  Background reason: {headers.get('X-Background-Reason', 'unknown')}")
    if headers.get('X-Background-Detail'):
        print(f"  Background detail: {headers.get('X-Background-Detail')}")
    print(f"  Debug: imshow executed? {headers.get('X-Debug-BG-Imshow-Executed', 'unknown')}")
    print(f"\nKey render headers:")
    for k in sorted(headers.keys()):
        if k.startswith('X-Background-') or k.startswith('X-Debug-'):
            print(f"  {k}: {headers[k]}")
except Exception as e:
    print(f"\n✗ Render failed!")
    print(f"  Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
