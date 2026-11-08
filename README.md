# Opportunity Board Bangladesh

Job seekers add their CV or interests on the page. The page ranks vacancies that are already published on job portals and social media. It shows a summary, deadline, apply link and source.

```
index.html                    the page (GitHub Pages)
data/jobs.json                vacancies, rewritten by the collector
scraper/collect.py            collector
scraper/sources.json          which sources to read
.github/workflows/collect.yml runs the collector every 6 hours
```

## Setup

1. Push everything to a GitHub repository. Turn on **Settings → Pages → Deploy from branch → main / root**.
2. Turn on **Settings → Actions → General → Workflow permissions → Read and write**.
3. Add secrets in **Settings → Secrets and variables → Actions**:
   - `APIFY_TOKEN` for BDJobs. BDJobs has no public API, so the collector runs a ready-made Apify actor. Apify bills per result and has a monthly free credit. Open the actor in the Apify console, check its input fields, and edit `runs` in `scraper/sources.json`.
   - `RELIEFWEB_APPNAME` for NGO and UN jobs. Request an appname at reliefweb.int (it is required on every API call).
4. Open the **Actions** tab, choose **Collect vacancies**, and press **Run workflow**. When it finishes, `data/jobs.json` is filled and the site updates in a minute.

A source whose secret is missing is skipped, and one failing source does not stop the others. If every source fails, the old `jobs.json` is kept.

## Adding more sources (`scraper/sources.json`)

- `rss`: any site with an RSS or Atom feed of vacancies.
- `telegram`: a public channel name. Reads the public preview page `t.me/s/<channel>`.
- `html`: a career page that lists jobs in plain HTML, with CSS selectors.

Set `"enabled": true` after filling in the details.

## Limits

- Facebook and LinkedIn do not allow automated collection, so they are not included. Many pages and groups also post to Telegram or have a website with a feed, which you can add above.
- For posts without a clear structure (RSS and Telegram), organization, location, category and deadline are guessed from the text. A deadline is only set when the post says "deadline", "last date" or similar next to a date.
- Always keep the link to the original post. Check each site's terms before adding it.
- Expired vacancies are removed. Posts with no deadline are removed after 45 days.
