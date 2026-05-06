#!/usr/bin/env python3
"""Quick test to verify render_png works with background enabled."""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Suppress DEBUG logging
os.environ["PYTHONWARNINGS"] = "ignore"
import logging
logging.getLogger("boto").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)

# Setup path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.web_render import render_png, RenderParams

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

print(f"[TEST] Starting render with background={params.background}")

try:
    png_bytes, metadata, headers = render_png(settings_path=settings_path, params=params)
    print(f"[OK] Render succeeded!")
    print(f"  PNG size: {len(png_bytes)} bytes")
    print(f"  Data source: {headers.get('X-Data-Source', 'unknown')}")
    print(f"  Background applied: {headers.get('X-Background-Applied', 'unknown')}")
    print(f"  Background reason: {headers.get('X-Background-Reason', 'unknown')}")
    print(f"  Imshow executed: {headers.get('X-Debug-BG-Imshow-Executed', 'unknown')}")
    if headers.get('X-Background-Detail'):
        print(f"  Background detail: {headers.get('X-Background-Detail')}")
except Exception as e:
    print(f"[FAIL] Render failed!")
    print(f"  Error: {type(e).__name__}: {e}")
    sys.exit(1)
