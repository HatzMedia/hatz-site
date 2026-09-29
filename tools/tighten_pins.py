#!/usr/bin/env python3
"""
Second try at approximate pins. For every mapped place with a numbered street address whose pin only landed
on the street, ask the map service for the house number itself (a structured search). If it answers with a
building or an interpolated house number on that street, the pin becomes exact.

    python tools/tighten_pins.py
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "HatzSiteBuilder/1.0 (Hatz@hatzmedia.com)"}


def load(name, default):
    p = DATA / name
    text = p.read_text(encoding="utf-8-sig").strip() if p.exists() else ""
    return json.loads(text) if text else default


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def structured(street, city, state):
    q = {"format": "jsonv2", "street": street, "city": city, "state": state, "country": "USA", "limit": 3, "addressdetails": 1}
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    places = load("places.json", [])
    decisions = load("decisions.json", [])
    fixed, tried = 0, 0
    for p in places:
        addr = p.get("address") or ""
        if p.get("precision") == "exact" or not re.match(r"^\d+\s", addr):
            continue
        parts = [x.strip() for x in addr.split(",")]
        street = parts[0]
        city = parts[1] if len(parts) > 1 else ""
        state = "KY" if re.search(r"\bKY\b", addr) else "OH"
        city = re.sub(r"\s+(OH|KY)\b.*$", "", city).strip()
        tried += 1
        try:
            hits = structured(street, city, state)
        except Exception:
            hits = []
        time.sleep(1.1)
        road = squash(re.sub(r"^\d+\s*", "", street))[:8]
        good = next((h for h in hits if h.get("addresstype") != "road" and road in squash(h.get("display_name", ""))
                     and (h.get("address", {}).get("house_number") or h.get("category") in ("amenity", "shop", "building", "tourism", "leisure"))), None)
        if good:
            p["lat"], p["lng"], p["precision"] = round(float(good["lat"]), 5), round(float(good["lon"]), 5), "exact"
            decisions.append({"action": "editPlace", "slug": p["slug"], "lat": p["lat"], "lng": p["lng"], "precision": "exact"})
            fixed += 1
            print("exact now: %-34s %s" % (p["name"][:34], good.get("display_name", "")[:70]))
        else:
            print("still approx: %s" % p["name"])
    (DATA / "places.json").write_text(json.dumps(places, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (DATA / "decisions.json").write_text(json.dumps(decisions, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Tightened %d of %d approximate pins." % (fixed, tried))


if __name__ == "__main__":
    main()
