#!/usr/bin/env python3
"""
One-time helper: puts every suggested place that already has a pin ("a positive hit") on the map,
without waiting for a tap on the review page. Hatz then uses the Fix links to correct any that are wrong.

Reads data/suggestions.json, skips anything Hatz already decided, and appends the rest to
data/decisions.json in the same shape the review page produces. Run tools/update.py afterwards.

    python tools/apply_hits.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(name, default):
    p = DATA / name
    text = p.read_text(encoding="utf-8-sig").strip() if p.exists() else ""
    return json.loads(text) if text else default


def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def main():
    sugg = load("suggestions.json", {"places": [], "skip": [], "existing": {}})
    decisions = load("decisions.json", [])
    videos = {v["id"]: v for v in load("videos.json", [])}
    known_slugs = {p["slug"] for p in load("places.json", [])}
    known_slugs |= {d["newPlace"]["slug"] for d in decisions if d.get("newPlace")}
    decided = {d["video"] for d in decisions if d.get("video")}

    added_places, added_videos, left = 0, 0, []
    for p in sugg["places"]:
        vids = [v for v in p["videos"] if v in videos and videos[v]["status"] == "pending" and v not in decided]
        if not vids:
            continue
        if not p.get("found"):
            left.append(p["name"])
            continue
        slug = slugify(p["name"])
        new_place = {"slug": slug, "name": p["name"], "area": p.get("area", ""), "address": p.get("address", ""),
                     "cat": p.get("cat", "eats"), "trip": bool(p.get("trip")), "lat": p["lat"], "lng": p["lng"],
                     "precision": p.get("precision", "area"), "aliases": [p["name"]]}
        for i, v in enumerate(vids):
            if i == 0 and slug not in known_slugs:
                decisions.append({"video": v, "action": "assign", "newPlace": new_place})
                known_slugs.add(slug)
                added_places += 1
            else:
                decisions.append({"video": v, "action": "assign", "place": slug})
            added_videos += 1
            decided.add(v)

    for v, slug in sugg.get("existing", {}).items():
        if v in videos and videos[v]["status"] == "pending" and v not in decided:
            decisions.append({"video": v, "action": "assign", "place": slug})
            added_videos += 1
            decided.add(v)

    # A queued video whose title or description names exactly one place we now know is a positive hit too.
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from update import match_places
    places = load("places.json", []) + [d["newPlace"] for d in decisions if d.get("newPlace")]
    by_name = 0
    for v in videos.values():
        if v["status"] != "pending" or v["id"] in decided:
            continue
        hits = match_places(v, places)
        if len(hits) == 1:
            decisions.append({"video": v["id"], "action": "assign", "place": hits[0]})
            decided.add(v["id"])
            by_name += 1
    print("Matched %d more queued videos by place name." % by_name)

    (DATA / "decisions.json").write_text(json.dumps(decisions, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Added %d places and %d videos to decisions.json." % (added_places, added_videos))
    print("Still need a pin from Hatz (%d): %s" % (len(left), ", ".join(left)))


if __name__ == "__main__":
    main()
