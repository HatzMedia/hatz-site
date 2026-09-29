#!/usr/bin/env python3
"""
Uses the YouTube location tags pulled by tools/pull_locations.py (data/yt_details.json). Each tagged video
carries a pin and, usually, the place name Hatz typed when he tagged it. That name is trusted over anything
a map service would guess.

  1. A suggested place that had no pin gets one from any of its tagged videos.
  2. A mapped place with an approximate pin is snapped to a video's tag when the tag is within 400 m.
  3. A mapped video whose tag sits more than 3 km from its place is listed for Hatz to check (not changed).
  4. A queued video with a tag: assigned to an existing place within 150 m, otherwise proposed as a new place
     named from the tag, so tools/apply_hits.py can put it on the map.
  5. Full descriptions replace the shortened ones, so name matching sees everything.

Safety: videos on the "probably not a place" list are never placed from their tag, and a tag that lands on a
house with no place name is left alone. A family clip filmed at home must not become a pin.

    python tools/apply_locations.py
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "HatzSiteBuilder/1.0 (Hatz@hatzmedia.com)"}
POI_TYPES = {"amenity", "shop", "tourism", "leisure", "craft", "office", "historic", "attraction"}
HOUSE_TYPES = {"house", "residential", "apartments", "detached", "semidetached_house", "terrace"}
CINCY = (39.09, -84.27)


def load(name, default):
    p = DATA / name
    text = p.read_text(encoding="utf-8-sig").strip() if p.exists() else ""
    return json.loads(text) if text else default


def save(name, obj, indent=1):
    (DATA / name).write_text(json.dumps(obj, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def dist_m(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def reverse(lat, lng):
    q = {"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 18, "namedetails": 1}
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def guess_cat(name, category):
    n = name.lower()
    if re.search(r"bakery|dessert|ice cream|creamy|sweet|candy|donut|doughnut|cookie|scoop", n):
        return "sweets"
    if re.search(r"fest|festival|fair|market(?!place)|christmas|halloween", n):
        return "events"
    if re.search(r"zoo|park|aquarium|resort|waterpark|museum|terminal|island|point\b", n):
        return "family"
    if re.search(r"mall|store|shop|market|towne centre|town center", n):
        return "shopping"
    return {"tourism": "family", "leisure": "family", "shop": "shopping"}.get(category, "eats")


def main():
    details = load("yt_details.json", {})
    if not details:
        raise SystemExit("data/yt_details.json is missing. Run tools/pull_locations.py first.")
    videos = load("videos.json", [])
    places = load("places.json", [])
    decisions = load("decisions.json", [])
    sugg = load("suggestions.json", {"places": [], "skip": [], "existing": {}})
    by_slug = {p["slug"]: p for p in places}
    for d in decisions:
        if d.get("newPlace"):
            by_slug.setdefault(d["newPlace"]["slug"], d["newPlace"])
    skip_set = set(sugg.get("skip", []))
    decided = {d["video"] for d in decisions if d.get("video")}

    def tag_of(vid):
        d = details.get(vid) or {}
        return (d["lat"], d["lng"]) if d.get("lat") is not None else None

    def label_of(vid):
        s = (details.get(vid) or {}).get("locationDescription", "").strip()
        return "" if re.match(r"^\d+\s", s) else s  # a bare street address is not a place name

    # 5. full descriptions
    longer = 0
    for v in videos:
        d = details.get(v["id"])
        if d and len(d.get("desc", "")) > len(v.get("desc", "")):
            v["desc"] = d["desc"]
            longer += 1

    # 1. pin the suggestions that had none
    pinned_sugg = 0
    for p in sugg["places"]:
        if p.get("found"):
            continue
        tags = [tag_of(v) for v in p["videos"] if tag_of(v)]
        if tags:
            p.update(found=True, lat=tags[0][0], lng=tags[0][1], precision="exact", weak=False, source="youtube-tag",
                     display="from the video's YouTube location tag")
            pinned_sugg += 1
    suggested = {v for p in sugg["places"] for v in p["videos"] if p.get("found")}

    # 2 + 3. mapped videos
    snapped, mismatches, edited = 0, [], set()
    for v in videos:
        tag = tag_of(v["id"])
        if not tag or v["status"] != "mapped" or v["place"] not in by_slug:
            continue
        p = by_slug[v["place"]]
        if p.get("lat") is None:
            continue
        dm = dist_m(tag, (p["lat"], p["lng"]))
        if dm > 3000:
            mismatches.append({"video": v["id"], "title": v["title"], "place": p["name"], "tagged_as": label_of(v["id"]), "km": round(dm / 1000, 1)})
        elif p.get("precision") != "exact" and dm <= 400 and p["slug"] not in edited:
            decisions.append({"action": "editPlace", "slug": p["slug"], "lat": tag[0], "lng": tag[1], "precision": "exact"})
            p["lat"], p["lng"], p["precision"] = tag[0], tag[1], "exact"
            edited.add(p["slug"])
            snapped += 1

    # 4. queued videos with a tag
    assigned, proposed_places, proposed_videos, left_alone = 0, 0, 0, []
    groups = []  # {"name", "tag", "videos"}
    for v in videos:
        tag = tag_of(v["id"])
        if not tag or v["status"] != "pending" or v["id"] in decided or v["id"] in skip_set or v["id"] in suggested:
            continue
        near = sorted((p for p in by_slug.values() if p.get("lat") is not None), key=lambda p: dist_m(tag, (p["lat"], p["lng"])))
        if near and dist_m(tag, (near[0]["lat"], near[0]["lng"])) <= 150:
            decisions.append({"video": v["id"], "action": "assign", "place": near[0]["slug"]})
            decided.add(v["id"])
            assigned += 1
            continue
        label = label_of(v["id"])
        for g in groups:
            if (label and g["name"] == label) or (not label and dist_m(tag, g["tag"]) <= 150):
                g["videos"].append(v)
                break
        else:
            groups.append({"name": label, "tag": tag, "videos": [v]})

    for g in groups:
        try:
            r = reverse(*g["tag"])
        except Exception:
            r = {}
        time.sleep(1.1)
        cat, atype = r.get("category", ""), r.get("addresstype", "")
        map_name = (r.get("namedetails") or {}).get("name") or ""
        name = g["name"] or (map_name if (cat in POI_TYPES or atype in POI_TYPES) and atype not in HOUSE_TYPES else "")
        if not name:
            left_alone += [v["title"] for v in g["videos"]]
            continue
        addr = r.get("address", {})
        town = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("township") or ""
        state = {"Ohio": "OH", "Kentucky": "KY", "Indiana": "IN", "Michigan": "MI", "West Virginia": "WV", "Pennsylvania": "PA"}.get(addr.get("state", ""), "OH")
        street = " ".join(x for x in [addr.get("house_number", ""), addr.get("road", "")] if x)
        key = "yt-" + slugify(name)
        if any(p["key"] == key for p in sugg["places"]) or slugify(name) in by_slug:
            for v in g["videos"]:
                decisions.append({"video": v["id"], "action": "assign", "place": slugify(name)})
                assigned += 1
            continue
        sugg["places"].append({
            "key": key, "name": name, "area": (town + ", " + state) if town else state,
            "address": ", ".join(x for x in [street, town, state] if x), "cat": guess_cat(name, cat),
            "trip": dist_m(g["tag"], CINCY) > 90000, "videos": [v["id"] for v in g["videos"]],
            "found": True, "lat": g["tag"][0], "lng": g["tag"][1], "precision": "exact",
            "display": "from the video's YouTube location tag" + ((" · " + r.get("display_name", "")[:60]) if r.get("display_name") else ""),
            "weak": not g["name"], "source": "youtube-tag"})
        proposed_places += 1
        proposed_videos += len(g["videos"])

    save("videos.json", videos)
    save("decisions.json", decisions)
    save("suggestions.json", sugg, indent=2)
    save("location_report.json", {"mismatches": mismatches, "left_alone": left_alone})
    print("Full descriptions updated: %d" % longer)
    print("Suggested places that got a pin from a tag: %d" % pinned_sugg)
    print("Approximate pins snapped to a video tag: %d" % snapped)
    print("Queued videos assigned to an existing place: %d" % assigned)
    print("New places proposed from tags: %d (covering %d videos)" % (proposed_places, proposed_videos))
    print("Tagged videos left alone (no place name, not a business): %d" % len(left_alone))
    print("Mapped videos whose tag disagrees with the pin by 3 km or more: %d" % len(mismatches))
    for m in mismatches[:20]:
        print("  %5.1f km  %-45s  mapped to %s, tagged %s" % (m["km"], m["title"][:45], m["place"], m["tagged_as"] or "(no name)"))
    print("Next: python tools/apply_hits.py, then python tools/update.py --offline")


if __name__ == "__main__":
    main()
