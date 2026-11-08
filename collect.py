#!/usr/bin/env python3
"""Collect published vacancies for Bangladesh and write data/jobs.json.

Run:  python scraper/collect.py
Secrets (environment): APIFY_TOKEN, RELIEFWEB_APPNAME  (each source is skipped if its secret is missing)
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "jobs.json"
CFG = Path(__file__).with_name("sources.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityBoardBot/1.0)"}
TODAY = dt.date.today()

CATEGORIES = {
    "GIS & Remote Sensing": ["gis", "remote sensing", "geospatial", "arcgis", "qgis", "satellite", "mapping", "surveyor"],
    "Engineering": ["engineer", "civil", "mechanical", "electrical", "construction", "architect", "structural", "site"],
    "IT & Data": ["software", "developer", "data", "python", "sql", "web", "network", "machine learning", "ai", "analyst", "programmer"],
    "Research & Academia": ["research", "lecturer", "professor", "phd", "fellowship", "scholarship", "academic", "faculty"],
    "NGO & Development": ["ngo", "unicef", "undp", "humanitarian", "project officer", "development", "program", "monitoring", "evaluation"],
    "Business & Finance": ["accountant", "finance", "audit", "marketing", "sales", "bank", "hr", "manager", "executive", "officer"],
}
EXTRA_TAGS = ["flood", "hydrology", "climate", "autocad", "excel", "dashboard", "statistics", "r", "remote", "wash", "mel", "reporting", "drainage"]
PLACES = ["Dhaka", "Chattogram", "Sylhet", "Khulna", "Rajshahi", "Barishal", "Rangpur", "Mymensingh", "Gazipur", "Narayanganj",
          "Cumilla", "Cox's Bazar", "Bogura", "Savar", "Tangail", "Jashore", "Remote"]
JOB_WORDS = re.compile(r"\b(hiring|vacanc\w+|recruit\w*|apply|career|position|job|opening|internship|walk-in|circular|wanted)\b", re.I)
KEY = r"(?:deadline|last date|closing date|apply by|apply before|due date|expires?|application ends?)"
DATE = (r"(\d{1,2}(?:st|nd|rd|th)?[\s\-/]+[A-Za-z]{3,9}[\s,\-/]+\d{2,4}"
        r"|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
        r"|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2})")


def log(*a):
    print(*a, file=sys.stderr)


def clean(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()


def has_word(text, word):
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


def to_date(s):
    if not s:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(s))
    try:
        d = dparse.parse(s, dayfirst=not re.match(r"\s*\d{4}-", s), default=dt.datetime(TODAY.year, 1, 1)).date()
    except (ValueError, OverflowError):
        return None
    return d if TODAY.year - 1 <= d.year <= TODAY.year + 2 else None


def find_deadline(text):
    for m in re.finditer(KEY, text, re.I):
        d = re.search(DATE, text[m.end():m.end() + 70])
        if d and to_date(d.group(1)):
            return to_date(d.group(1))
    return None


def build(title, org, summary, apply_url, source, source_url, deadline=None, location=None,
          jtype=None, level=None, quals=None, salary=None, published=None):
    title, org, summary = clean(title)[:140], clean(org) or source, clean(summary)
    if not title or not (apply_url or source_url):
        return None
    text = f"{title}. {summary} {quals or ''}".lower()
    category = next((c for c, kws in CATEGORIES.items() if any(has_word(text, k) for k in kws)), "Other")
    tags = [k for k in dict.fromkeys(sum(CATEGORIES.values(), []) + EXTRA_TAGS) if has_word(text, k)][:8]
    loc = clean(location).replace("Chittagong", "Chattogram")[:60] if location else None
    if not loc:
        loc = next((p for p in PLACES if has_word(text.replace("chittagong", "chattogram"), p.lower())), "Bangladesh")
    if not jtype:
        jtype = next((v for k, v in [("intern", "Internship"), ("part-time", "Part-time"), ("part time", "Part-time"), ("fellowship", "Fellowship"),
                                      ("scholarship", "Scholarship"), ("contract", "Contract")] if k in text), "Full-time")
    if not level:
        level = "Entry" if re.search(r"intern|entry|fresher|junior|trainee", text) else ("Senior" if re.search(r"senior|head of|lead|director|chief", text) else None)
    deadline = deadline or find_deadline(f"{title}. {summary} {quals or ''}")
    url = apply_url or source_url
    return {
        "id": hashlib.sha1(f"{url}|{title}|{org}".lower().encode()).hexdigest()[:12],
        "title": title, "org": org, "category": category, "location": loc, "type": jtype, "level": level,
        "deadline": deadline.isoformat() if deadline else None,
        "summary": summary[:320] + ("…" if len(summary) > 320 else ""),
        "qualifications": clean(quals)[:500] or None, "salary": clean(salary) or None,
        "apply_url": url, "source_name": source, "source_url": source_url or url, "tags": tags,
        "created_at": (published or TODAY).isoformat(),
    }


# ---------------------------------------------------------------- source parsers
def pick(raw, keys):
    for k in keys:
        v = raw.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("text")
        if isinstance(v, list):
            v = ", ".join(str(x.get("name") if isinstance(x, dict) else x) for x in v)
        if v not in (None, "", []):
            return v
    return None


def from_raw(raw, source):
    """Tolerant mapper for structured items (Apify actors use different field names)."""
    title = pick(raw, ["title", "jobTitle", "job_title", "position", "name"])
    if not title:
        log(f"[{source}] item skipped, no title field. Keys: {sorted(raw)[:15]}")
        return None
    url = pick(raw, ["url", "jobUrl", "job_url", "link", "applyUrl"])
    return build(title, pick(raw, ["companyName", "company_name", "company", "organization", "employer"]),
                 pick(raw, ["summary", "shortDescription", "description", "jobDescription", "job_description"]),
                 pick(raw, ["applyUrl", "apply_url"]) or url, source, url,
                 deadline=to_date(pick(raw, ["deadline", "closingDate", "closing_date", "applicationDeadline", "expires", "validThrough"])),
                 location=pick(raw, ["location", "workplace", "place", "city", "address"]),
                 jtype=pick(raw, ["employmentType", "employment_type", "jobType", "job_type", "type"]),
                 level=pick(raw, ["level", "jobLevel", "experienceLevel"]),
                 quals=pick(raw, ["requirements", "educationalRequirements", "education", "qualifications"]),
                 salary=pick(raw, ["salary", "salaryRange", "salary_range"]),
                 published=to_date(pick(raw, ["postedDate", "publishedAt", "datePosted", "posted_date", "published"])))


def fetch_apify(src):
    token = os.getenv("APIFY_TOKEN")
    if not token:
        log(f"[{src['name']}] skipped: APIFY_TOKEN not set")
        return None
    out = []
    for run in src["runs"]:
        r = requests.post(f"https://api.apify.com/v2/acts/{src['actor']}/run-sync-get-dataset-items",
                          params={"token": token}, json=run, timeout=330)
        r.raise_for_status()
        out += [j for j in (from_raw(i, src["name"]) for i in r.json()) if j]
    return out


def fetch_reliefweb(src):
    app = os.getenv("RELIEFWEB_APPNAME")
    if not app:
        log(f"[{src['name']}] skipped: RELIEFWEB_APPNAME not set")
        return None
    body = {"filter": {"field": "country.iso3", "value": "BGD"}, "limit": 100, "preset": "latest", "sort": ["date.created:desc"],
            "fields": {"include": ["title", "url", "source.name", "date.closing", "date.created", "body", "how_to_apply",
                                   "city.name", "type.name", "experience.name"]}}
    r = requests.post("https://api.reliefweb.int/v2/jobs", params={"appname": app}, json=body, headers=HEADERS, timeout=60)
    r.raise_for_status()
    out = []
    for it in r.json().get("data", []):
        f = it.get("fields", {})
        src_name = (f.get("source") or [{}])[0].get("name")
        quals = BeautifulSoup(f.get("how_to_apply") or "", "html.parser").get_text(" ")
        j = build(f.get("title"), src_name, BeautifulSoup(f.get("body") or "", "html.parser").get_text(" "), f.get("url"),
                  "ReliefWeb", f.get("url"), deadline=to_date((f.get("date") or {}).get("closing")),
                  location=((f.get("city") or [{}])[0] or {}).get("name"), jtype=((f.get("type") or [{}])[0] or {}).get("name"),
                  quals=quals, published=to_date((f.get("date") or {}).get("created")))
        if j:
            out.append(j)
    return out


def parse_post(text, link, urls, src, published=None):
    """Turn an unstructured post (feed entry or social post) into a job, or None if it is not a vacancy."""
    text = text.strip()
    if not text or not JOB_WORDS.search(text):
        return None
    first = next((l for l in text.splitlines() if clean(l)), "")
    title = re.sub(r"^[^\w]+|[^\w)]+$", "", clean(first))
    m = re.search(r"(?:company|organi[sz]ation|employer)\s*[:\-]\s*([^\n|]{3,80}?)(?=\s*(?:\n|\||\.\s|$))", text, re.I)
    apply_url = next((u for u in urls if re.search(r"apply|career|job|form|recruit", u, re.I)), None) or (urls[0] if urls else link)
    return build(title, m.group(1) if m else None, clean(text), apply_url, src["name"], link, published=published)


def parse_rss(content, src):
    out = []
    for e in feedparser.parse(content).entries:
        body = BeautifulSoup(e.get("summary", "") or e.get("description", ""), "html.parser")
        pub = dt.date(*e.published_parsed[:3]) if e.get("published_parsed") else None
        urls = [a["href"] for a in body.find_all("a", href=True)]
        j = parse_post(f"{e.get('title', '')}\n{body.get_text(' ')}", e.get("link"), urls, src, pub)
        if j:
            j["title"] = clean(e.get("title"))[:140] or j["title"]
            out.append(j)
    return out


def parse_telegram(html, src):
    out = []
    for w in BeautifulSoup(html, "html.parser").select("div.tgme_widget_message_wrap"):
        t = w.select_one("div.tgme_widget_message_text")
        if not t:
            continue
        urls = [a["href"] for a in t.find_all("a", href=True) if a["href"].startswith("http")]
        for br in t.find_all("br"):
            br.replace_with("\n")
        link = (w.select_one("a.tgme_widget_message_date") or {}).get("href")
        tm = w.select_one("time[datetime]")
        pub = to_date(tm["datetime"][:10]) if tm else None
        j = parse_post(t.get_text(), link, urls, src, pub)
        if j:
            out.append(j)
    return out


def parse_html(html, src):
    out = []
    soup = BeautifulSoup(html, "html.parser")
    txt = lambda el, sel: clean(el.select_one(sel).get_text(" ")) if sel and el.select_one(sel) else ""
    for el in soup.select(src["item"]):
        a = el.select_one(src.get("link", "a"))
        href = urljoin(src["url"], a["href"]) if a and a.get("href") else src["url"]
        j = build(txt(el, src.get("title")), txt(el, src.get("org")), txt(el, src.get("summary")), href, src["name"], href,
                  deadline=to_date(txt(el, src.get("deadline"))))
        if j:
            out.append(j)
    return out


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=40)
    r.raise_for_status()
    return r.text


FETCHERS = {
    "apify": fetch_apify,
    "reliefweb": fetch_reliefweb,
    "rss": lambda s: parse_rss(get(s["url"]), s),
    "telegram": lambda s: parse_telegram(get(f"https://t.me/s/{s['channel']}"), s),
    "html": lambda s: parse_html(get(s["url"]), s),
}


# ---------------------------------------------------------------- merge and write
def still_valid(j, keep_days):
    if j.get("deadline"):
        return dt.date.fromisoformat(j["deadline"]) >= TODAY
    return (TODAY - dt.date.fromisoformat(j.get("created_at") or TODAY.isoformat())).days <= keep_days


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    keep = cfg.get("keep_days_without_deadline", 45)
    fresh, ok = {}, 0
    for src in cfg["sources"]:
        if not src.get("enabled"):
            continue
        try:
            items = FETCHERS[src["type"]](src)
        except Exception as e:  # one broken source must not stop the others
            log(f"[{src['name']}] failed: {e}")
            continue
        if items is None:
            continue
        ok += 1
        log(f"[{src['name']}] {len(items)} vacancies")
        for j in items:
            fresh[j["id"]] = j
    if not ok:
        log("No source succeeded; keeping the existing data/jobs.json")
        return 1
    old = {}
    if OUT.exists():
        data = json.loads(OUT.read_text(encoding="utf-8") or "[]")
        old = {j["id"]: j for j in (data["jobs"] if isinstance(data, dict) else data)}
    for i, j in fresh.items():
        if i in old:
            j["created_at"] = old[i].get("created_at", j["created_at"])
    merged = {**old, **fresh}
    jobs = sorted((j for j in merged.values() if still_valid(j, keep)), key=lambda j: (j["deadline"] or "9999", j["title"]))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "jobs": jobs},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Wrote {len(jobs)} vacancies to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
