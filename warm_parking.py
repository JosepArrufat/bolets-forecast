#!/usr/bin/env python3
"""Precompute nearby parking for every station in mushrooms.json.

Why: public Overpass instances can take 30-40 s per live query. The web app
should answer instantly, so we warm `parking_cache.json` once and let the app
serve the cached rows. New stations fall back to a live query at runtime.

Usage:
    python3 warm_parking.py --bulk parking-cat.json
    python3 warm_parking.py                 # query each station live (slow)
"""
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MUSHROOMS = os.path.join(BASE_DIR, "mushrooms.json")
OUT = os.path.join(BASE_DIR, "parking_cache.json")
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = "BoletsForecast/1.0 (mushroom forecast; warm cache)"


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def parkings_from_overpass(data):
    rows = []
    for el in data.get("elements", []):
        center = el.get("center") or {}
        lat = el.get("lat", center.get("lat"))
        lon = el.get("lon", center.get("lon"))
        if lat is None or lon is None:
            continue
        tags = el.get("tags") or {}
        rows.append({
            "name": tags.get("name") or "Aparcament",
            "lat": lat,
            "lon": lon,
            "capacity": tags.get("capacity"),
        })
    return rows


def query_station(lat, lon, radius_m=2500):
    query = (
        f'[out:json][timeout:60];'
        f'(node["amenity"="parking"](around:{radius_m},{lat},{lon});'
        f'way["amenity"="parking"](around:{radius_m},{lat},{lon}););'
        f'out center 12;'
    )
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for endpoint in ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint, data=body,
                headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                return parkings_from_overpass(json.loads(r.read()))
        except Exception as e:
            last = e
    raise last


def nearest(rows, lat, lon, limit=5):
    out = []
    for p in rows:
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if d <= 3000:
            out.append({**p, "distance_m": round(d)})
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk", help="JSON file from one large Overpass bbox query")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    with open(MUSHROOMS) as f:
        stations = json.load(f)["target_stations"]

    existing = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            existing = json.load(f)

    if args.bulk:
        with open(args.bulk) as f:
            bulk = json.load(f)
        rows = parkings_from_overpass(bulk)
        print(f"Loaded {len(rows)} parking places from {args.bulk}")
        for comarca, stns in stations.items():
            for stn in stns:
                key = f"{stn['lat']:.4f},{stn['lon']:.4f}"
                existing[key] = nearest(rows, stn["lat"], stn["lon"])
                print(f"  {stn['name']}: {len(existing[key])} parking")
    else:
        def work(comarca, stn):
            rows = query_station(stn["lat"], stn["lon"])
            return f"{stn['lat']:.4f},{stn['lon']:.4f}", nearest(rows, stn["lat"], stn["lon"]), stn["name"]

        jobs = [(c, s) for c, ss in stations.items() for s in ss]
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(work, c, s): (c, s) for c, s in jobs}
            for fut in as_completed(futs):
                key, rows, name = fut.result()
                existing[key] = rows
                print(f"  {name}: {len(rows)} parking")

    with open(OUT, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUT} ({len(existing)} stations)")


if __name__ == "__main__":
    main()
