# hatz-site — notes for Claude

The public website for Hatz Media Works LLC (HMW), served at https://hatzmedia.com by GitHub Pages from the `main` branch, repo root. "Hatz" is Zac Hatley's on-camera name; the company is HMW. See `README.md` for the owner-facing setup guide.

## How the site works

- Plain static HTML/CSS/JS. No build tool, no package manager, no framework.
- `tools/update.py` (Python 3, standard library only) pulls YouTube videos, matches them to places and rebuilds the generated files. A GitHub Action (`.github/workflows/update.yml`) runs it daily, and again whenever `data/decisions.json` is pushed. It commits as `hatz-bot` with the message "Update videos and map".
- `data/places.json` and `data/decisions.json` are the hand-editable source of truth. `data/videos.json` is maintained by the updater.

## Generated files: don't hand-edit

These are overwritten on every run, so change the template code in `tools/update.py` (or the source data) instead:

- `places/*/index.html` (one page per place)
- `data/data.js`, `sitemap.xml`, `robots.txt`
- The blocks between `<!--LATEST_START-->`/`<!--LATEST_END-->`, `<!--TOP5_START-->`/`<!--TOP5_END-->` and `<!--STATS_START-->`/`<!--STATS_END-->` in `index.html` (and the stats block in `work-with-hatz/index.html`)

Everything else in `index.html` and the other pages is hand-written and safe to edit.

## Check your work

```
python3 tools/update.py --offline
git status
```

`--offline` rebuilds every generated file from the data files with no internet access or API key. On a clean tree the only expected change is the timestamp in `data/data.js`. Anything else that changes is the result of your edit; review it before committing. Open the HTML in a browser (Playwright/Chromium is available in cloud sessions) to check layout at phone width.

Don't run the updater without `--offline` unless asked. `--backfill` needs `YOUTUBE_API_KEY`, and `--notify` opens or edits GitHub issues.

## Working rules

- The bot commits to `main` every day. Pull before starting, and expect merge conflicts in generated files. Resolve those by re-running `--offline`, never by hand-merging.
- `styles.css` is an old copy kept only for old links. The live design is `hatz.css`.
- Never commit secrets. The YouTube key lives only in the repo's Actions secrets.
- Public copy is in Hatz's voice: plain, warm, local, no hype. Never invent prices, quotes, ratings or visit details. Collaborations go through an email link only, with no public prices.
- Paid/gifted-video disclosure and `/privacy/` wording are flagged in the README for professional review. Don't change their meaning without saying so.
- Nothing is live until it's merged to `main`. Don't push to `main` or merge without Zac's explicit OK.
