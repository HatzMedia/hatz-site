# Hatz site, version 2

This is your current hatzmedia.com design plus three new things:

1. **The map** at `/explore/`, with a page for every place.
2. **Automatic video updates.** Once a day the site checks YouTube, adds new videos to "Latest from Hatz", and puts a video on the map by itself when its title or description names a place it already knows.
3. **A review page** at `/review/`. Anything the site can't place shows up there. You pick the place, and it goes on the map.

Collaborations stay the way you like them: an email link, no public prices.

## Before you upload

The `assets` folder already holds your logo (`hatz-brand.webp`), the hero photo (`hatz-in-the-community.jpg`) and the profile photo (`hatz-profile.jpg`). To swap one, replace the file and keep the same name.

## How it's hosted

GitHub does two jobs, both free: it serves the site's files (GitHub Pages), and once a day it checks YouTube and rebuilds the map. Northwest holds the domain, hatzmedia.com, and points it at GitHub. Northwest's own hosting (the WordPress install) isn't used.

## One-time setup (about 20 minutes)

1. Make a free account at github.com and create a **new public repository** called `hatz-site`. (Public is required for free hosting; everything in it is already on the public website anyway. Your API key is never in the repository.)
2. Click **Add file, then Upload files**, drag in everything from this folder (including the hidden `.github` folder), and press **Commit changes**.
3. In the repository go to **Settings, then Pages**. Under "Build and deployment" choose **Deploy from a branch**, pick `main` and `/ (root)`, and save. After a minute your site is at `https://YOUR-NAME.github.io/hatz-site/`. Open it and check it over.
4. In **Settings, then Secrets and variables, then Actions**, press **New repository secret**, name it `YOUTUBE_API_KEY`, and paste the key you already made.
5. Go to **Actions**, open "Update Hatz videos and map", and press **Run workflow**. Watch it turn green. That's the daily job proving itself.
6. Go live on your own address, last, because it replaces the current site:
   - In **Settings, then Pages**, type `hatzmedia.com` under **Custom domain** and save.
   - At Northwest, open **Domains, hatzmedia.com, DNS Settings** and make exactly these changes:
     - **A Records:** delete the two `@` rows whose values are `162.159.143.30` and `172.66.3.26` (those are ChatGPT's). Add four `@` rows with values `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`. Leave the `*` and `mail` rows alone.
     - **CNAME Records:** edit the `www` row and change its value from `custom-domains.chatgpt.site.` to `YOUR-NAME.github.io.` Leave `psrp` alone.
     - **Leave everything else alone:** MX, the `@` TXT (SPF), `_dmarc`, `postal-…_domainkey`, and NS are your email and domain plumbing.
     - **Optional tidy-up, a week later:** the `_cf-custom-hostname`, `_openai-site-verification` and `_acme-challenge` TXT rows belonged to the ChatGPT site and can be deleted.
   - The records use a 1-minute TTL, so the switch takes effect within minutes.
   - Back in GitHub Pages, tick **Enforce HTTPS** once the check next to the domain turns green (up to a day).

## If Northwest ever gives you FTP access

The daily job can also copy the finished site to Northwest by FTP. Add secrets named `FTP_HOST`, `FTP_USER` and `FTP_PASSWORD` (and `FTP_DIR` if the folder isn't `public_html/`) and it starts doing so automatically. The `.htaccess` file here makes our home page win over WordPress's if WordPress is still installed there.

## Getting the full video archive (optional, recommended)

YouTube's public feed only shows the newest 15 videos. To bring in your whole archive:

1. Go to console.cloud.google.com, create a project, turn on **YouTube Data API v3**, and create an **API key**. It is free.
2. In your repository go to **Settings, then Secrets and variables, then Actions, then New repository secret**. Name it `YOUTUBE_API_KEY` and paste the key.
3. Go to **Actions**, press **Run workflow**, tick **Import the whole video archive**, and run it. Videos that name a known place go on the map. The rest wait on the review page.

## Sorting the archive (one time)

The review page has a **Quick confirm** section built from your whole archive. Each card is one place with all its videos, a pin already looked up, and a **Confirm** button. Tap **Check it** next to the pin if you want to be sure, then **Confirm**. Below that, **Probably not place videos** lists gaming, Elf on the Shelf, Red Bull and family clips; untick any that should stay, then **Skip the checked videos**. What's left is a short list to sort by hand.

## Fixing a place from the map

On the map, every place card has a small **Fix** link, and every place page has **Something off? Send this place to review** near the directions button. Tapping it puts that place at the top of the review page, where you can correct the name or address, find a new pin, pull a video off the place, or take the place down.

## Your day-to-day

- **Nothing to do** when a new video names a known place. It just appears.
- When a video can't be placed, GitHub emails you an issue called **Videos waiting for a location**. Open `/review/` on your site, choose the place (or add a new one), press **Put on the map**, then follow the two save steps at the bottom of the page.
- **Not a place video** (family clips, gaming) takes it out of the queue. It still shows in "Latest from Hatz."

## Files

| File or folder | What it is |
|---|---|
| `index.html`, `styles.css` | Home page and design |
| `explore/` | The map |
| `places/` | One page per place. Built automatically, do not edit |
| `review/` | Your review page |
| `data/places.json` | The places, with their pins. You can edit this by hand |
| `data/videos.json` | Every video and where it's placed |
| `data/decisions.json` | The choices you save from the review page |
| `tools/update.py` | The updater |
| `tools/build_suggestions.py`, `data/suggestions.json` | The one-time archive sort behind Quick confirm. Safe to delete once the queue is empty |
| `tools/apply_hits.py` | Puts every suggested place that already has a pin on the map without a tap |
| `tools/pull_locations.py`, `tools/apply_locations.py` | Pull the location tag YouTube stores with each video (needs the API key), then use it to snap pins and place queued videos |
| `tools/tighten_pins.py` | Second try at turning approximate pins into exact ones from the street address |
| `tools/reconcile_tags.py`, `data/location_report.json` | Settles cases where a video's YouTube tag disagrees with its place's pin |
| `.github/workflows/update.yml` | The daily schedule |

## Things to confirm with a professional

- Wording on `/privacy/`, and disclosure of paid or gifted videos.
- A written agreement template for collaborations, so pricing can vary by client without public rates.
