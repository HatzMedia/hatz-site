#!/usr/bin/env python3
"""
Hatz site updater. Uses only the Python standard library.

What it does, every time it runs (a GitHub Action runs it once a day):
  1. Pulls Hatz's newest YouTube videos (YouTube API if YOUTUBE_API_KEY is set, otherwise the public feed).
  2. Adds any new video to data/videos.json.
  3. Tries to work out the place for each new video by matching place names in the title and description.
       - Exactly one known place matches -> the video is put on the map automatically ("auto").
       - Anything else -> the video waits in the review queue for Hatz to confirm.
  4. Applies Hatz's decisions from data/decisions.json (made on the /review/ page).
  5. Rebuilds: the "Latest from Hatz" block on the home page, data/data.js (used by the map),
     one page per place under /places/, sitemap.xml and robots.txt.

Run by hand:
    python tools/update.py                 normal run
    python tools/update.py --offline       no internet, just rebuild pages from the data files
    python tools/update.py --backfill      needs YOUTUBE_API_KEY, pulls the whole video archive
    python tools/update.py --notify        (used by the Action) opens or closes the "videos waiting" GitHub issue
"""
import datetime
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = "https://hatzmedia.com"
EMAIL = "Hatz@hatzmedia.com"
CHANNEL_ID = "UCEQJaPBu_YHqumyEpuUm4uA"
UPLOADS_PLAYLIST = "UU" + CHANNEL_ID[2:]
UA = {"User-Agent": "Mozilla/5.0 (compatible; HatzSiteUpdater/1.0; +https://hatzmedia.com)"}

CAT_LABELS = {
    "eats": "Restaurants & eats",
    "sweets": "Sweets & bakeries",
    "shopping": "Markets & shopping",
    "family": "Family outings",
    "events": "Events & seasonal",
}


# ---------------------------------------------------------------- small helpers
def load(name, default):
    p = DATA / name
    if not p.exists():
        return default
    text = p.read_text(encoding="utf-8-sig").strip()  # utf-8-sig: tolerate the invisible marker some editors add
    return json.loads(text) if text else default


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def fmt_date(iso):
    try:
        d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%b %-d, %Y") if os.name != "nt" else d.strftime("%b %d, %Y").replace(" 0", " ")
    except Exception:
        return ""


def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- YouTube
def parse_rss(xml_text):
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    out = []
    for e in ET.fromstring(xml_text).findall("a:entry", ns):
        vid = e.findtext("yt:videoId", default="", namespaces=ns)
        if not vid:
            continue
        out.append({
            "id": vid,
            "title": (e.findtext("a:title", default="", namespaces=ns) or "").strip(),
            "published": e.findtext("a:published", default="", namespaces=ns),
            "desc": (e.findtext("m:group/m:description", default="", namespaces=ns) or "").strip(),
        })
    return out


def fetch_rss():
    return parse_rss(http_get("https://www.youtube.com/feeds/videos.xml?channel_id=" + CHANNEL_ID))


def parse_api_items(payload):
    out = []
    for it in payload.get("items", []):
        sn, cd = it.get("snippet", {}), it.get("contentDetails", {})
        title = sn.get("title", "")
        if title in ("Private video", "Deleted video") or not cd.get("videoId"):
            continue
        out.append({
            "id": cd["videoId"],
            "title": title.strip(),
            "published": cd.get("videoPublishedAt") or sn.get("publishedAt", ""),
            "desc": (sn.get("description") or "").strip(),
        })
    return out


def fetch_api(key, everything=False):
    out, token = [], ""
    while True:
        q = {"part": "snippet,contentDetails", "maxResults": 50, "playlistId": UPLOADS_PLAYLIST, "key": key}
        if token:
            q["pageToken"] = token
        payload = json.loads(http_get("https://www.googleapis.com/youtube/v3/playlistItems?" + urllib.parse.urlencode(q)))
        out += parse_api_items(payload)
        token = payload.get("nextPageToken", "")
        if not token or not everything:
            return out


def fetch_videos(backfill):
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    errors = []
    if key:
        try:
            return fetch_api(key, everything=backfill)
        except Exception as e:  # fall through to the feed
            errors.append("YouTube API: %s" % e)
    if backfill and not key:
        sys.exit("--backfill needs a YOUTUBE_API_KEY (see README).")
    try:
        return fetch_rss()
    except Exception as e:
        errors.append("YouTube feed: %s" % e)
    print("WARNING: could not reach YouTube (%s). Rebuilding from saved data only." % "; ".join(errors))
    return []


# ---------------------------------------------------------------- place matching
def match_places(video, places):
    text = squash(video.get("title", "") + " " + video.get("desc", ""))
    hits = []
    for p in places:
        for alias in [p["name"]] + p.get("aliases", []):
            a = squash(alias)
            if len(a) >= 6 and a in text:
                hits.append(p["slug"])
                break
    return hits


def merge(videos, places, fetched):
    known = {v["id"]: v for v in videos}
    added = 0
    for f in fetched:
        if f["id"] in known:
            known[f["id"]]["title"] = f["title"] or known[f["id"]]["title"]
            continue
        hits = match_places(f, places)
        v = {"id": f["id"], "title": f["title"], "published": f["published"], "desc": f["desc"][:600],
             "place": None, "status": "pending", "by": None, "suggest": hits}
        if len(hits) == 1:
            v.update(place=hits[0], status="mapped", by="auto")
        videos.append(v)
        known[v["id"]] = v
        added += 1
    # re-check queued videos against any newly added places
    for v in videos:
        if v["status"] == "pending":
            v["suggest"] = match_places(v, places)
    return added


def apply_decisions(videos, places, decisions):
    vids = {v["id"]: v for v in videos}
    by_slug = {p["slug"]: p for p in places}
    for d in decisions:
        act = d.get("action")
        if act == "editPlace" and d.get("slug") in by_slug:
            p = by_slug[d["slug"]]
            for k in ("lat", "lng", "address", "area", "cat", "precision", "trip", "name"):
                if k in d:
                    p[k] = d[k]
            continue
        v = vids.get(d.get("video"))
        if not v:
            continue
        if act == "assign":
            slug = d.get("place")
            if d.get("newPlace"):
                np = d["newPlace"]
                slug = np.get("slug") or slugify(np["name"])
                if slug not in by_slug:
                    p = {"slug": slug, "name": np["name"], "area": np.get("area", ""), "address": np.get("address", ""),
                         "cat": np.get("cat", "eats"), "trip": bool(np.get("trip", False)),
                         "lat": np.get("lat"), "lng": np.get("lng"),
                         "precision": np.get("precision", "exact"), "aliases": np.get("aliases", [])}
                    places.append(p)
                    by_slug[slug] = p
            if slug in by_slug:
                v.update(place=slug, status="mapped", by="hatz")
        elif act == "skip":
            v.update(place=None, status="skip", by="hatz")
        elif act == "pending":
            v.update(place=None, status="pending", by=None)


# ---------------------------------------------------------------- HTML pieces
PLAY = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="m8 4 13 8-13 8z"/></svg>'
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%230b0c11'/%3E"
           "%3Cpath d='M8 7h5v7h6V7h5v18h-5v-7h-6v7H8z' fill='%2300aeff'/%3E%3Cpath d='M8 27h16v2H8z' fill='%23ff39d5'/%3E%3C/svg%3E")
COLLAB = "mailto:%s?subject=Collaboration%%20with%%20Hatz%%20Media%%20Works" % EMAIL
SUGGEST = ("mailto:%s?subject=A%%20local%%20spot%%20for%%20Hatz%%20to%%20check%%20out&body=Hi%%20Hatz%%2C%%0A%%0AHere%%E2%%80%%99s%%20a%%20place%%20you%%20should%%20check%%20out%%3A%%0ABusiness%%20name%%3A%%0ALocation%%3A%%0AWhat%%20makes%%20it%%20worth%%20a%%20visit%%3A%%0AWebsite%%20or%%20social%%20link%%3A%%0A" % EMAIL)


def header(rp):
    return ('<a class="skip-link" href="#main">Skip to content</a><header class="header"><a class="wordmark" href="%(rp)s" aria-label="Hatz home">'
            '<img src="%(rp)sassets/hatz-brand.webp" alt="" width="56" height="56"><span><strong>HATZ</strong><small>CINCINNATI &amp; BEYOND</small></span></a>'
            '<nav aria-label="Main navigation"><a href="%(rp)s#watch">Watch</a><a href="%(rp)sexplore/">Explore the map</a><a href="%(rp)s#about">Meet Hatz</a><a href="%(rp)s#follow">Join the crew</a></nav>'
            '<a class="button button-small" href="%(c)s">Let’s collab <span aria-hidden="true">↗</span></a></header>') % {"rp": rp, "c": COLLAB}


def footer(rp):
    return ('<footer><div class="footer-top"><a class="wordmark" href="%(rp)s" aria-label="Hatz home"><img src="%(rp)sassets/hatz-brand.webp" alt="" width="56" height="56">'
            '<span><strong>HATZ</strong><small>CINCINNATI &amp; BEYOND</small></span></a><a class="footer-email" href="mailto:%(e)s">%(e)s</a></div>'
            '<div class="footer-bottom"><p>© 2026 Hatz Media Works LLC</p><div><a href="%(rp)s#watch">Watch</a><a href="%(rp)sexplore/">Explore the map</a>'
            '<a href="%(c)s">Collaborations</a><a href="%(rp)sprivacy/">Privacy &amp; disclosures</a>'
            '<a href="https://linktr.ee/HatzReviews" target="_blank" rel="noopener noreferrer">All Hatz links <span aria-hidden="true">↗</span></a></div></div></footer>') % {"rp": rp, "e": EMAIL, "c": COLLAB}


def thumb(v):
    return "https://i.ytimg.com/vi/%s/hqdefault.jpg" % v["id"]


def yt_url(v):
    return "https://www.youtube.com/watch?v=" + v["id"]


def directions(p):
    if p.get("lat") is not None and p.get("precision") == "exact":
        dest = "%s,%s" % (p["lat"], p["lng"])
    else:
        dest = ", ".join(x for x in [p["name"], p.get("address") or p.get("area")] if x)
    return "https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote(dest)


def video_card(v, label, sub="", href=None, rp="", place_name=None):
    href = href or yt_url(v)
    external = href.startswith("http")
    tgt = ' target="_blank" rel="noopener noreferrer"' if external else ""
    return ('<article class="video-card"><a href="%s"%s><div class="card-image"><img src="%s" width="480" height="360" alt="" loading="lazy">'
            '<span class="card-category">%s</span></div><div class="card-text"><p class="card-location">%s</p><h3>%s</h3></div></a></article>') % (
        esc(href), tgt, thumb(v), esc(label), esc(sub), esc(v["title"]))


def render_latest(videos, places):
    by = {p["slug"]: p for p in places}
    recent = sorted(videos, key=lambda v: v["published"], reverse=True)[:6]
    cards = []
    for v in recent:
        p = by.get(v["place"]) if v["status"] == "mapped" else None
        label = ("On the map · " + p["name"]) if p else "Watch on YouTube ↗"
        cards.append(video_card(v, label, fmt_date(v["published"])))
    return ('<!--LATEST_START--><section class="latest section" id="watch" aria-labelledby="latest-title"><div class="section-heading"><div>'
            '<p class="eyebrow">THE ADVENTURE KEEPS GOING</p><h2 id="latest-title">Latest from Hatz.</h2></div>'
            '<p>Food stops, family adventures, and whatever we get into next.</p></div>'
            '<p class="feed-note">Updated automatically from YouTube. Visit the channel for everything.</p>'
            '<div class="video-grid latest-grid">%s</div><div class="watch-more"><p>Catch up with the crew.</p>'
            '<a class="text-link" href="https://www.tiktok.com/@hatzreviews" target="_blank" rel="noopener noreferrer">Follow Hatz on TikTok ↗</a></div></section><!--LATEST_END-->'
            ) % "".join(cards)


def render_place_page(p, vids, all_places, all_vids):
    rp = "../../"
    vids = sorted(vids, key=lambda v: v["published"], reverse=True)
    latest = vids[0]
    n = len(vids)
    cat = CAT_LABELS.get(p.get("cat"), "Local stop")
    desc = "Hatz stopped by %s%s. Watch %s and get directions." % (
        p["name"], (" in " + p["area"]) if p.get("area") else "", "the video" if n == 1 else "all %d videos" % n)
    more = ""
    if n > 1:
        more = ('<section class="related section" aria-labelledby="more-title"><p class="eyebrow">MORE FROM THIS PLACE</p><h2 id="more-title">Every visit.</h2><div class="video-grid">%s</div></section>'
                % "".join(video_card(v, "Watch on YouTube ↗", fmt_date(v["published"])) for v in vids))
    others = [q for q in all_places if q["slug"] != p["slug"] and any(v["place"] == q["slug"] and v["status"] == "mapped" for v in all_vids)][:3]
    keep = ""
    if others:
        cards = []
        for q in others:
            qv = sorted([v for v in all_vids if v["place"] == q["slug"] and v["status"] == "mapped"], key=lambda v: v["published"], reverse=True)[0]
            cards.append(video_card(qv, CAT_LABELS.get(q.get("cat"), "Local stop"), q.get("area", ""), href="../%s/" % q["slug"]))
        keep = ('<section class="related section" aria-labelledby="related-title"><p class="eyebrow">KEEP EXPLORING</p><h2 id="related-title">One more before you go?</h2><div class="video-grid">%s</div></section>'
                % "".join(cards))
    approx = ""
    if p.get("precision") != "exact":
        approx = '<li>The map pin is approximate. It shows the area, not the exact door.</li>'
    where = esc(p.get("address") or p.get("area") or "")
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "VideoObject", "name": latest["title"], "description": desc,
        "thumbnailUrl": [thumb(latest)], "uploadDate": latest["published"],
        "embedUrl": "https://www.youtube-nocookie.com/embed/" + latest["id"]}, ensure_ascii=False)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="theme-color" content="#0b0c11"><meta name="referrer" content="strict-origin-when-cross-origin">'
            '<title>%(name)s | Watch with Hatz</title><meta name="description" content="%(desc)s">'
            '<link rel="canonical" href="%(site)s/places/%(slug)s/"><meta property="og:title" content="%(name)s | Watch with Hatz">'
            '<meta property="og:description" content="%(desc)s"><meta property="og:type" content="website"><meta property="og:image" content="%(thumb)s">'
            '<link rel="icon" type="image/svg+xml" href="%(fav)s"><link rel="stylesheet" href="%(rp)sstyles.css">'
            '<script>try{if(localStorage.getItem("hatz-admin"))document.documentElement.classList.add("hatz-admin")}catch(e){}</script></head><body>%(header)s'
            '<main id="main" class="watch-page"><section class="watch-intro"><a class="back-link" href="%(rp)sexplore/">← Back to the map</a>'
            '<p class="eyebrow">%(cat)s%(areaSep)s</p><h1>%(name)s</h1><p class="story-meta">%(count)s <span aria-hidden="true">·</span> Latest visit %(date)s</p>'
            '<p class="watch-description">%(desc)s</p></section>'
            '<div class="watch-layout"><div><div class="video-frame"><iframe src="https://www.youtube-nocookie.com/embed/%(vid)s?rel=0" title="%(name)s — Hatz video" width="960" height="540" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen loading="lazy"></iframe></div>'
            '<p class="player-help">%(title)s · <a href="%(yt)s" target="_blank" rel="noopener noreferrer">Watch directly on YouTube <span aria-hidden="true">↗</span></a></p></div>'
            '<aside class="visit-notes"><p class="eyebrow">THE STOP</p><h2>Plan your visit.</h2><ul><li><strong>%(name)s</strong>%(where)s</li>%(approx)s</ul>'
            '<p class="visit-note">Check with the business for current hours, menus, and availability.</p>'
            '<p><a class="button button-small" href="%(dir)s" target="_blank" rel="noopener noreferrer">Get directions <span aria-hidden="true">↗</span></a></p>'
            '<p><a class="text-link" href="%(suggest)s">Suggest the next stop <span aria-hidden="true">↗</span></a></p>'
            '<p class="fix-link"><a href="%(rp)sreview/#fix-%(slug)s">Something off? Send this place to review</a></p></aside></div>'
            '%(more)s%(keep)s<div class="small-collab"><p>Own a local business like this one?</p><a class="text-link" href="%(collab)s">Let’s start a conversation <span aria-hidden="true">↗</span></a></div></main>'
            '<script type="application/ld+json">%(ld)s</script>%(footer)s</body></html>') % {
        "name": esc(p["name"]), "desc": esc(desc), "site": SITE, "slug": esc(p["slug"]), "thumb": thumb(latest), "fav": FAVICON, "rp": rp,
        "header": header(rp), "cat": esc(cat), "areaSep": (" / " + esc(p["area"])) if p.get("area") else "",
        "count": "%d video%s" % (n, "" if n == 1 else "s"), "date": esc(fmt_date(latest["published"])), "vid": latest["id"],
        "title": esc(latest["title"]), "yt": yt_url(latest), "where": (" · " + where) if where else "", "approx": approx,
        "dir": esc(directions(p)), "suggest": SUGGEST, "more": more, "keep": keep, "collab": COLLAB,
        "ld": ld.replace("</", "<\\/"), "footer": footer(rp)}


def replace_block(text, start, end, block):
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    return pattern.sub(lambda m: block, text, count=1) if pattern.search(text) else text


# ---------------------------------------------------------------- build
def build(videos, places):
    mapped = [v for v in videos if v["status"] == "mapped" and v["place"]]
    with_videos = {v["place"] for v in mapped}
    public_places = [p for p in places if p["slug"] in with_videos]

    # data.js for the map and the review page
    out_places = []
    for p in places:
        q = dict(p)
        q["videos"] = [v["id"] for v in sorted(mapped, key=lambda v: v["published"], reverse=True) if v["place"] == p["slug"]]
        out_places.append(q)
    payload = {
        "suggestions": load("suggestions.json", {"places": [], "skip": [], "existing": {}}),
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "places": out_places,
        "videos": [{"id": v["id"], "title": v["title"], "published": v["published"], "place": v["place"], "status": v["status"],
                    "by": v.get("by"), "suggest": v.get("suggest", [])} for v in sorted(videos, key=lambda v: v["published"], reverse=True)],
    }
    (DATA / "data.js").write_text("window.HATZ_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")

    # place pages
    pdir = ROOT / "places"
    pdir.mkdir(exist_ok=True)
    keep_dirs = set()
    for p in public_places:
        d = pdir / p["slug"]
        d.mkdir(exist_ok=True)
        pv = [v for v in mapped if v["place"] == p["slug"]]
        (d / "index.html").write_text(render_place_page(p, pv, public_places, mapped), encoding="utf-8")
        keep_dirs.add(p["slug"])
    for d in pdir.iterdir():  # remove pages for places that no longer have a video
        if d.is_dir() and d.name not in keep_dirs:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()

    # home page blocks
    idx = ROOT / "index.html"
    if idx.exists():
        t = idx.read_text(encoding="utf-8")
        t = replace_block(t, "<!--LATEST_START-->", "<!--LATEST_END-->", render_latest(videos, places))
        stats = "<!--STATS_START-->%d videos across %d places<!--STATS_END-->" % (len(mapped), len(public_places))
        t = replace_block(t, "<!--STATS_START-->", "<!--STATS_END-->", stats)
        idx.write_text(t, encoding="utf-8")

    # sitemap + robots
    today = datetime.date.today().isoformat()
    urls = ["", "explore/", "privacy/"] + ["places/%s/" % p["slug"] for p in public_places]
    sm = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
          "".join("  <url><loc>%s/%s</loc><lastmod>%s</lastmod></url>\n" % (SITE, u, today) for u in urls) + "</urlset>\n")
    (ROOT / "sitemap.xml").write_text(sm, encoding="utf-8")
    (ROOT / "robots.txt").write_text("User-agent: *\nAllow: /\nDisallow: /review/\nSitemap: %s/sitemap.xml\n" % SITE, encoding="utf-8")

    return mapped, public_places


# ---------------------------------------------------------------- notify (GitHub issue)
def notify(videos):
    pending = [v for v in videos if v["status"] == "pending"]
    title = "Videos waiting for a location"
    found = subprocess.run(["gh", "issue", "list", "--state", "open", "--search", title + " in:title", "--json", "number,title"],
                           capture_output=True, text=True)
    existing = [i for i in json.loads(found.stdout or "[]") if i["title"] == title]
    if not pending:
        for i in existing:
            subprocess.run(["gh", "issue", "close", str(i["number"]), "--comment", "All caught up."])
        return
    lines = ["%d video%s need a location before %s on the map." % (len(pending), "" if len(pending) == 1 else "s", "they show up" if len(pending) != 1 else "it shows up"), ""]
    for v in pending[:20]:
        sug = (" (looks like: %s)" % ", ".join(v["suggest"])) if v.get("suggest") else ""
        lines.append("- [%s](https://www.youtube.com/watch?v=%s) — %s%s" % (v["title"].replace("]", ")").replace("[", "("), v["id"], fmt_date(v["published"]), sug))
    lines += ["", "Open the review page on your site (`/review/`), pick the place for each video, and follow the two steps at the bottom of the page."]
    body = "\n".join(lines)
    if existing:
        subprocess.run(["gh", "issue", "edit", str(existing[0]["number"]), "--body", body])
    else:
        subprocess.run(["gh", "issue", "create", "--title", title, "--body", body])


# ---------------------------------------------------------------- main
def main():
    args = set(sys.argv[1:])
    places = load("places.json", [])
    videos = load("videos.json", [])
    decisions = load("decisions.json", [])

    if "--notify" in args:
        notify(videos)
        return

    added = 0
    if "--offline" not in args:
        added = merge(videos, places, fetch_videos("--backfill" in args))
    apply_decisions(videos, places, decisions)
    save("places.json", places)
    save("videos.json", sorted(videos, key=lambda v: v["published"], reverse=True))
    mapped, public_places = build(videos, places)
    pending = sum(1 for v in videos if v["status"] == "pending")
    print("New videos: %d | on the map: %d videos at %d places | waiting for review: %d" % (added, len(mapped), len(public_places), pending))


if __name__ == "__main__":
    main()
