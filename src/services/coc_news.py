"""Scrapes the official Clash of Clans blog for game-update / balance-change
posts. There's no RSS or JSON feed (checked), so this parses the live HTML —
verified against the real markup during implementation, not guessed."""

import requests
from bs4 import BeautifulSoup

BLOG_ARCHIVE_URL = "https://supercell.com/en/games/clashofclans/blog/"
BASE_URL = "https://supercell.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# /blog/release-notes/<slug>/ posts are reliably substantive game-content
# updates. /blog/news/<slug>/ is a mixed bag — real standalone balance posts
# (e.g. "July Balance Update") share that same path with pure marketing/event
# posts (crossovers, medal events), and the page has no separate category
# field to tell them apart (the on-page "category" text is just the static
# label "Blog – Clash of Clans" for every post). So /news/ posts are only
# included if their title looks like a content update. This is a best-effort
# heuristic, not a guarantee — release-notes posts are never filtered.
NEWS_TITLE_KEYWORDS = ("update", "balance", "sneak peek", "changes", "patch")


def _get(url, timeout=15):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    # The server doesn't send a charset in Content-Type, so requests falls
    # back to ISO-8859-1 and mangles special characters (en-dashes, curly
    # quotes) into mojibake. The real encoding is UTF-8.
    resp.encoding = "utf-8"
    return resp.text


def _is_relevant(href, title):
    if "/blog/release-notes/" in href:
        return True
    if "/blog/news/" in href:
        title_lower = title.lower()
        return any(kw in title_lower for kw in NEWS_TITLE_KEYWORDS)
    return False


def fetch_recent_posts(limit=10):
    """Returns the most recent relevant blog posts, newest first, as
    [{"title", "url", "date"}, ...]."""
    html = _get(BLOG_ARCHIVE_URL)
    soup = BeautifulSoup(html, "html.parser")

    posts = []
    for link in soup.find_all("a", href=True, class_=lambda c: c and "titleLink" in c):
        href = link["href"]
        title = link.get_text(" ", strip=True)
        if not title or not _is_relevant(href, title):
            continue

        # DOM shape: <div><div class="...metaRow..">category, date</div>
        #                  <div class="...title..."><a>title</a></div></div>
        card = link.parent.parent if link.parent else None
        date_text = None
        if card:
            date_el = card.find("p", attrs={"data-test-id": "publish-date-text"})
            if date_el:
                date_text = date_el.get_text(strip=True)

        posts.append({
            "title": title,
            "url": href if href.startswith("http") else BASE_URL + href,
            "date": date_text,
        })

        if len(posts) >= limit:
            break

    return posts


def fetch_post_changes(url):
    """Fetches one post and breaks it into sections:
    {"title", "url", "sections": [{"heading": str|None, "lines": [str, ...]}]}.

    Posts vary in shape — some are a flat list of balance changes, others
    (like a monthly "Update" post) have multiple headed sections (new pet
    levels, QoL changes, bug fixes) plus the occasional table. This walks the
    body in document order and groups text under whichever heading it falls
    under. If the site's markup doesn't match what we expect at all, it falls
    back to raw paragraph text so a layout change degrades instead of raising.
    """
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.find(class_=lambda c: c and "articleTitle" in c) or soup.find("title")
    title = title_el.get_text(" ", strip=True) if title_el else url
    # The <title> tag fallback includes a " - Clash of Clans" site suffix — trim it.
    title = title.split(" – Clash of Clans")[0].split(" - Clash of Clans")[0].strip()

    body = soup.find("div", class_=lambda c: c and "richText" in c and "content" in c)
    sections = []

    if body:
        current = None
        for el in body.find_all(["h2", "h3", "h4", "p", "li", "table"]):
            # <li> elements wrap their own <p>, and table cells contain <p>
            # too — skip those so we don't emit the same text twice.
            if el.name == "p" and (el.find_parent("li") or el.find_parent("table")):
                continue

            if el.name in ("h2", "h3", "h4"):
                current = {"heading": el.get_text(" ", strip=True), "lines": []}
                sections.append(current)
                continue

            text = "[table omitted — see full post]" if el.name == "table" \
                else el.get_text(" ", strip=True)
            if not text:
                continue

            if current is None:
                current = {"heading": None, "lines": []}
                sections.append(current)
            current["lines"].append(text)

    if not sections:
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        paras = [p for p in paras if p][:15]
        if paras:
            sections = [{"heading": None, "lines": paras}]

    return {"title": title, "url": url, "sections": sections}
