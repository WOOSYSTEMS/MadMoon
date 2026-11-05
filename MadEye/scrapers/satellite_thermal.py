"""
MadEye Sniper Mode — Scraper 12: NASA FIRMS Satellite Thermal Monitor
Monitors fire/explosion hotspots in 5 oil-critical regions.
Detects anomaly clusters and high-brightness events.
"""

import json as json_mod
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from .base_scraper import (
    fetch, make_result, safe_run, DATA_DIR
)

FIRMS_KEY = "cf56ebe9e0641c7716f98d13e0f44778"

# 5 oil-critical monitoring regions (bounding boxes: W,S,E,N)
REGIONS = {
    "persian_gulf": {
        "name": "Persian Gulf",
        "bbox": "47,23,57,31",
        "baseline_avg": 15,  # updated dynamically
    },
    "yemen": {
        "name": "Yemen / Red Sea",
        "bbox": "40,11,55,19",
        "baseline_avg": 20,
    },
    "hormuz": {
        "name": "Strait of Hormuz",
        "bbox": "54,24,58,28",
        "baseline_avg": 5,
    },
    "gulf_of_mexico": {
        "name": "Gulf of Mexico",
        "bbox": "-98,18,-80,31",
        "baseline_avg": 30,
    },
    "libya": {
        "name": "Libya",
        "bbox": "9,19,25,34",
        "baseline_avg": 25,
    },
}

BASELINE_FILE = os.path.join(DATA_DIR, "firms_baselines.json")


def load_baselines() -> Dict:
    if os.path.exists(BASELINE_FILE):
        try:
            with open(BASELINE_FILE, "r") as f:
                return json_mod.load(f)
        except:
            pass
    return {}


def save_baselines(baselines: Dict):
    try:
        with open(BASELINE_FILE, "w") as f:
            json_mod.dump(baselines, f, indent=2)
    except:
        pass


def fetch_firms_region(region_key: str, region: Dict) -> Dict:
    """Fetch FIRMS data for a region. Returns analysis dict."""
    bbox = region["bbox"]
    # FIRMS VIIRS active fire data, last 24 hours
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_KEY}/VIIRS_SNPP_NRT/{bbox}/1"

    result = {
        "region": region["name"],
        "fire_count": 0,
        "high_brightness_count": 0,
        "cluster_detected": False,
        "anomaly": False,
        "signals": [],
    }

    raw = fetch(url, ttl_seconds=300)
    if not raw:
        result["signals"].append(f"{region['name']}: FIRMS API unreachable")
        return result

    # Parse CSV: latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,...
    lines = raw.strip().split('\n')
    if len(lines) < 2:
        return result

    header = lines[0].lower().split(',')
    try:
        bright_idx = header.index('bright_ti4') if 'bright_ti4' in header else header.index('brightness')
    except ValueError:
        bright_idx = 2  # fallback

    try:
        lat_idx = header.index('latitude')
        lon_idx = header.index('longitude')
    except ValueError:
        lat_idx = 0
        lon_idx = 1

    fires = []
    for line in lines[1:]:
        parts = line.split(',')
        if len(parts) <= max(bright_idx, lat_idx, lon_idx):
            continue
        try:
            brightness = float(parts[bright_idx])
            lat = float(parts[lat_idx])
            lon = float(parts[lon_idx])
            fires.append({"brightness": brightness, "lat": lat, "lon": lon})
        except:
            continue

    result["fire_count"] = len(fires)

    # High brightness events (>350K = large fire/explosion)
    high_bright = [f for f in fires if f["brightness"] > 350]
    result["high_brightness_count"] = len(high_bright)

    if high_bright:
        result["signals"].append(
            f"{region['name']}: {len(high_bright)} HIGH BRIGHTNESS events (>350K) — possible explosion/large fire"
        )

    # Cluster detection: 6+ fires within small area
    # Simple grid: count fires in 0.5-degree cells
    grid = {}
    for f in fires:
        cell = (round(f["lat"] * 2) / 2, round(f["lon"] * 2) / 2)
        grid[cell] = grid.get(cell, 0) + 1

    max_cluster = max(grid.values()) if grid else 0
    if max_cluster >= 6:
        result["cluster_detected"] = True
        result["signals"].append(
            f"{region['name']}: CLUSTER of {max_cluster} fires detected — possible major event"
        )

    # Anomaly: compare to baseline
    baseline = region.get("baseline_avg", 20)
    if len(fires) > baseline * 2:
        result["anomaly"] = True
        result["signals"].append(
            f"{region['name']}: {len(fires)} fires vs {baseline} baseline (2x+ anomaly)"
        )

    return result


def scrape() -> Dict:
    all_signals = []
    total_score_points = 0
    baselines = load_baselines()

    region_results = {}
    for key, region in REGIONS.items():
        # Use saved baseline if available
        if key in baselines:
            region["baseline_avg"] = baselines[key]

        rr = fetch_firms_region(key, region)
        region_results[key] = rr
        all_signals.extend(rr["signals"])

        # Update rolling baseline (exponential moving average)
        if rr["fire_count"] > 0:
            old = baselines.get(key, region["baseline_avg"])
            baselines[key] = round(old * 0.9 + rr["fire_count"] * 0.1, 1)

        # Scoring
        if rr["high_brightness_count"] > 0:
            total_score_points += min(4, rr["high_brightness_count"])
        if rr["cluster_detected"]:
            total_score_points += 3
        if rr["anomaly"]:
            total_score_points += 2

    save_baselines(baselines)

    if total_score_points >= 12:
        score = 10
    elif total_score_points >= 9:
        score = 8
    elif total_score_points >= 6:
        score = 6
    elif total_score_points >= 4:
        score = 4
    elif total_score_points >= 2:
        score = 2
    else:
        score = 0

    # Confidence: higher if we got data from most regions
    regions_with_data = sum(1 for r in region_results.values() if r["fire_count"] > 0)
    confidence = min(1.0, 0.3 + regions_with_data * 0.14)

    result = make_result(score, confidence, all_signals[:20], "satellite_thermal")
    result["region_results"] = {
        k: {"fire_count": v["fire_count"], "high_brightness": v["high_brightness_count"],
             "cluster": v["cluster_detected"], "anomaly": v["anomaly"]}
        for k, v in region_results.items()
    }
    result["total_fires"] = sum(r["fire_count"] for r in region_results.values())
    return result


def run() -> Dict:
    return safe_run("satellite_thermal", scrape)


if __name__ == "__main__":
    print(json_mod.dumps(run(), indent=2))
