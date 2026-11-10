#!/usr/bin/env python3
"""Curator OS V2 source snapshot updater. All automatically discovered news is unverified."""
import datetime as dt
import html
import json
import pathlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
UA = "Mozilla/5.0 (compatible; CuratorOS/2.0; +https://yingchenghuang.github.io/curator-os/)"

def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/rss+xml,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(4_000_000)

def write(name, payload):
    (DATA / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

class OpenGraphImage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.url = ""
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta" or self.url:
            return
        props = dict(attrs)
        if (props.get("property") or props.get("name")) in ("og:image", "twitter:image"):
            self.url = html.unescape(props.get("content", ""))

def load_latest():
    rows = json.loads((ROOT / "daily-curator-prompts.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Daily prompts must be a JSON array")
    earliest = (TODAY - dt.timedelta(days=60)).isoformat()
    valid, ids = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not earliest <= str(row.get("date", "")) <= TODAY.isoformat():
            continue
        if not row.get("id") or not row.get("title") or len(row.get("questions") or []) != 10:
            continue
        if row["id"] in ids:
            continue
        ids.add(row["id"])
        valid.append(row)
    valid.sort(key=lambda row: (row["date"], row["id"]))
    if valid:
        write("daily-latest.json", valid)
    counts = Counter(row["date"] for row in valid)
    complete = [day for day, count in counts.items() if count == 5]
    if not complete:
        print("No complete five-topic day found")
        return []
    latest = max(complete)
    print("Latest complete day:", latest)
    return [row for row in valid if row["date"] == latest]

def update_media(rows):
    old = {}
    path = DATA / "daily-media.json"
    if path.exists():
        try:
            old = {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8")).get("items", [])}
        except (ValueError, KeyError, TypeError):
            pass
    items = []
    for row in rows:
        refs = (row.get("caseStudy") or {}).get("references") or []
        if not refs:
            continue
        source = refs[0].get("url", "")
        if not source.startswith("https://"):
            continue
        try:
            parser = OpenGraphImage()
            parser.feed(fetch(source).decode("utf-8", "replace")[:300_000])
            image = urllib.parse.urljoin(source, parser.url) if parser.url else ""
            if not image.startswith("https://"):
                raise ValueError("No official HTTPS preview image")
            items.append({
                "id": row["id"],
                "image": image,
                "case": (row.get("caseStudy") or {}).get("title") or row["title"],
                "source": source,
                "checkedAt": TODAY.isoformat(),
                "rights": "Official-source image preview; reuse rights not established"
            })
        except Exception as error:
            print("Image preview unavailable:", row["id"], str(error)[:120])
            if row["id"] in old:
                items.append(old[row["id"]])
    if items:
        write("daily-media.json", {"generatedAt": TODAY.isoformat(), "items": items})
    print("Daily preview images:", len(items))

def update_news():
    query = '("art exhibition" OR "biennale" OR "public art") (site:labiennale.org OR site:serpentinegalleries.org OR site:tate.org.uk OR site:nga.gov OR site:documenta.de)'
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": query, "hl": "en", "gl": "US", "ceid": "US:en"
    })
    try:
        root = ET.fromstring(fetch(url))
        items, seen = [], set()
        for entry in root.findall(".//channel/item"):
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            if not title or not link.startswith("https://") or title in seen:
                continue
            seen.add(title)
            pub = (entry.findtext("pubDate") or "").strip()
            try:
                day = parsedate_to_datetime(pub).date().isoformat()
            except (ValueError, TypeError):
                day = TODAY.isoformat()
            if (TODAY - dt.date.fromisoformat(day)).days > 35:
                continue
            publisher = entry.find("source")
            items.append({
                "date": day,
                "title": title,
                "url": link,
                "source": (publisher.text or "News") if publisher is not None else "News",
                "summary": "國際策展新聞線索，展期與內容仍須回查原機構公告。",
                "status": "待查證"
            })
            if len(items) >= 12:
                break
        write("auto-signals.json", {
            "generatedAt": TODAY.isoformat(),
            "items": items,
            "status": "待查證"
        })
        print("Unverified international news leads:", len(items))
    except Exception as error:
        print("News RSS unavailable; retaining previous snapshot:", str(error)[:120])

if __name__ == "__main__":
    latest_rows = load_latest()
    if latest_rows:
        update_media(latest_rows)
    update_news()
