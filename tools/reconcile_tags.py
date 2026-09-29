#!/usr/bin/env python3
"""
Settles the disagreements in data/location_report.json between a place's pin and a video's YouTube tag.
Hatz's tag names the spot where the video was filmed, so:

  a. Tag names the same place, and no other tag backs the current pin  ->  move the pin to the tag.
  b. Tag names the same place, but other tags back the current pin      ->  it's a second branch: new place.
  c. Tag names a different place we already know                        ->  move the video there,
     unless the video title names the current place, in which case keep it and use the tag as an approximate pin.
  d. Tag is a chain (a gas station, Skyline, Kroger...)                  ->  keep if the title names the place, else back to the queue.
  e. Tag names a place we don't know                                    ->  new place from the tag, move the video.

    python tools/reconcile_tags.py
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "tools"))
from apply_locations import dist_m, reverse, guess_cat, slugify, load, save  # noqa: E402

CHAINS = {"shell", "skylinechili", "skyline", "kroger", "krogermarketplace", "uniteddairyfarmers", "udf", "tacobell", "whitecastle",
          "texasroadhouse", "pizzahut", "mcdonalds", "sunoco", "sprinkles", "walmart", "target", "speedway", "bp", "marathon"}
STOP = {"the", "restaurant", "inc", "cincinnati", "oh", "ohio", "ky", "sandusky", "and", "co", "llc", "kitchen", "grill"}
STATES = {"Ohio": "OH", "Kentucky": "KY", "Indiana": "IN", "Michigan": "MI", "West Virginia": "WV", "Pennsylvania": "PA"}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean_label(s):
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)          # drop "(Hyde Park)"
    s = re.sub(r"\s+-\s+[A-Z][\w .]*,\s*[A-Z]{2}$", "", s)  # drop " - Sandusky, OH"
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP}


def same(a, b):
    qa, qb = squash(clean_label(a)), squash(b)
    if not qa or not qb:
        return False
    if qa in qb or qb in qa:
        return True
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.6


def is_chain(label):
    return squash(clean_label(label)) in CHAINS


def main():
    report = load("location_report.json", {"mismatches": []})
    videos = load("videos.json", [])
    vmap = {v["id"]: v for v in videos}
    places = load("places.json", [])
    decisions = load("decisions.json", [])
    details = load("yt_details.json", {})
    by_slug = {p["slug"]: p for p in places}
    for d in decisions:
        if d.get("newPlace"):
            by_slug.setdefault(d["newPlace"]["slug"], d["newPlace"])

    def tag_of(vid):
        d = details.get(vid) or {}
        return (d["lat"], d["lng"]) if d.get("lat") is not None else None

    def backing(slug, exclude):
        p = by_slug[slug]
        return sum(1 for v in videos if v["status"] == "mapped" and v["place"] == slug and v["id"] != exclude
                   and tag_of(v["id"]) and dist_m(tag_of(v["id"]), (p["lat"], p["lng"])) <= 400)

    def town_of(tag):
        try:
            r = reverse(*tag)
        except Exception:
            r = {}
        time.sleep(1.1)
        a = r.get("address", {})
        town = a.get("city") or a.get("town") or a.get("village") or a.get("township") or ""
        st = STATES.get(a.get("state", ""), "OH")
        street = " ".join(x for x in [a.get("house_number", ""), a.get("road", "")] if x)
        return town, st, street, r.get("category", "")

    log = []
    for m in report["mismatches"]:
        v = vmap.get(m["video"])
        if not v or v["status"] != "mapped":
            continue
        slug, tag, label = v["place"], tag_of(v["id"]), (m.get("tagged_as") or "").strip()
        p = by_slug.get(slug)
        if not p or not tag:
            continue
        title_names_place = same(p["name"], v["title"]) or squash(p["name"])[:10] in squash(v["title"])
        if not label:
            log.append("kept   %-40s (tag has no name)" % p["name"])
            continue
        if is_chain(label):
            if title_names_place:
                log.append("kept   %-40s tag is a chain (%s); title names the place" % (p["name"], label))
            else:
                decisions.append({"video": v["id"], "action": "pending"})
                v["status"], v["place"] = "pending", None
                log.append("queue  %-40s tag is a chain (%s) and title doesn't name the place" % (v["title"][:40], label))
            continue
        if same(label, p["name"]):
            if backing(slug, v["id"]) == 0:
                town, st, street, _ = town_of(tag)
                d = {"action": "editPlace", "slug": slug, "lat": tag[0], "lng": tag[1], "precision": "exact"}
                if town:
                    d["area"] = "%s, %s" % (town, st)
                    d["address"] = ", ".join(x for x in [street, town, st] if x)
                cl = clean_label(label)
                if squash(p["name"]) in squash(cl) and len(tokens(cl) - tokens(p["name"])) >= 2 and len(cl) <= 40:
                    d["name"] = cl
                decisions.append(d)
                p.update({k: d[k] for k in d if k not in ("action", "slug")})
                log.append("moved  %-40s pin -> tag (%s km)%s" % (p["name"], m["km"], (" now " + d["area"]) if town else ""))
            else:
                town, st, street, cat = town_of(tag)
                name = "%s (%s)" % (re.sub(r"\s+Eastgate$", "", p["name"]), town or "second location")
                nslug = slugify(name)
                if nslug not in by_slug:
                    np = {"slug": nslug, "name": name, "area": ("%s, %s" % (town, st)) if town else "", "address": ", ".join(x for x in [street, town, st] if x),
                          "cat": p.get("cat", "eats"), "trip": p.get("trip", False), "lat": tag[0], "lng": tag[1], "precision": "exact", "aliases": [name]}
                    decisions.append({"video": v["id"], "action": "assign", "newPlace": np})
                    by_slug[nslug] = np
                else:
                    decisions.append({"video": v["id"], "action": "assign", "place": nslug})
                v["place"] = nslug
                log.append("branch %-40s -> new place '%s' for this video" % (p["name"], name))
            continue
        other = next((q for q in by_slug.values() if q["slug"] != slug and same(label, q["name"])), None)
        if other:
            if title_names_place:
                decisions.append({"action": "editPlace", "slug": slug, "lat": tag[0], "lng": tag[1], "precision": "area"})
                p.update(lat=tag[0], lng=tag[1], precision="area")
                log.append("kept   %-40s title names it; pin set near tag (approximate)" % p["name"])
            else:
                decisions.append({"video": v["id"], "action": "assign", "place": other["slug"]})
                v["place"] = other["slug"]
                log.append("moved  %-40s video -> %s" % (v["title"][:40], other["name"]))
            continue
        if title_names_place and backing(slug, v["id"]) > 0:
            log.append("kept   %-40s title names it; tag says %s (check on review page)" % (p["name"], label))
            continue
        town, st, street, cat = town_of(tag)
        name = clean_label(label)
        nslug = slugify(name)
        if nslug not in by_slug:
            np = {"slug": nslug, "name": name, "area": ("%s, %s" % (town, st)) if town else "", "address": ", ".join(x for x in [street, town, st] if x),
                  "cat": guess_cat(name, cat), "trip": dist_m(tag, (39.09, -84.27)) > 90000, "lat": tag[0], "lng": tag[1], "precision": "exact", "aliases": [name]}
            decisions.append({"video": v["id"], "action": "assign", "newPlace": np})
            by_slug[nslug] = np
        else:
            decisions.append({"video": v["id"], "action": "assign", "place": nslug})
        v["place"] = nslug
        log.append("new    %-40s -> '%s' (was %s)" % (v["title"][:40], name, p["name"]))

    # tidy: a state code guessed as OH for a tag that is really elsewhere
    for d in decisions:
        np = d.get("newPlace")
        if np and np.get("area", "").endswith(", OH") and np.get("address"):
            pass
    save("decisions.json", decisions)
    for line in log:
        print(line)
    print("Settled %d of %d disagreements. Run tools/update.py --offline next." % (len(log), len(report["mismatches"])))


if __name__ == "__main__":
    main()
