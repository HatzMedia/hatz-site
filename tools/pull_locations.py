#!/usr/bin/env python3
"""
Pulls the location tag YouTube stores with each video (the pin the uploader set), plus the full description.
Needs YOUTUBE_API_KEY. Writes data/yt_details.json; nothing else changes until tools/apply_locations.py runs.

    $env:YOUTUBE_API_KEY="..."; python tools/pull_locations.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main():
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        sys.exit("Set YOUTUBE_API_KEY first (see README).")
    videos = json.loads((DATA / "videos.json").read_text(encoding="utf-8-sig"))
    ids = [v["id"] for v in videos]
    out, tagged = {}, 0
    for i in range(0, len(ids), 50):
        q = {"part": "snippet,recordingDetails", "id": ",".join(ids[i:i + 50]), "key": key}
        url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "HatzSite/1.0"}), timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
        for it in payload.get("items", []):
            sn, rd = it.get("snippet", {}), it.get("recordingDetails", {})
            loc = rd.get("location") or {}
            rec = {"desc": sn.get("description", ""), "tags": sn.get("tags", []),
                   "locationDescription": rd.get("locationDescription", "")}
            if loc.get("latitude") is not None:
                rec["lat"], rec["lng"] = round(loc["latitude"], 5), round(loc["longitude"], 5)
                tagged += 1
            out[it["id"]] = rec
        print("fetched %d of %d" % (min(i + 50, len(ids)), len(ids)))
    (DATA / "yt_details.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Done. %d of %d videos carry a location tag. Saved data/yt_details.json." % (tagged, len(out)))


if __name__ == "__main__":
    main()
