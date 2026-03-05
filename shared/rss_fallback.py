from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET


@dataclass
class RssItem:
    id: str
    title: str
    link: str
    published: str
    summary: str
    image_url: Optional[str] = None


def _first_text(elem: ET.Element | None, path: str) -> str:
    if elem is None:
        return ""
    found = elem.find(path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _extract_image_url(item: ET.Element) -> Optional[str]:
    # RSS 2.0 common patterns: <enclosure url="..."> or media:content
    enc = item.find("enclosure")
    if enc is not None:
        url = enc.attrib.get("url")
        if url:
            return url.strip()

    # media namespace (best-effort)
    for tag in ("{http://search.yahoo.com/mrss/}content", "{http://search.yahoo.com/mrss/}thumbnail"):
        m = item.find(tag)
        if m is not None:
            url = m.attrib.get("url")
            if url:
                return url.strip()

    # Some feeds embed img tags in description; do not HTML-parse here (keep simple)
    return None


def fetch_rss(feed_url: str, timeout_seconds: int = 20) -> list[RssItem]:
    """Fetch and parse an RSS/Atom feed into a normalized list.

    Notes:
      - Uses stdlib only (no requests dependency).
      - Best-effort parsing across RSS 2.0 variants.
    """
    if not feed_url:
        return []

    req = Request(
        feed_url,
        headers={
            "User-Agent": "EchoMediaAI/1.0 (+https://echomedia.ai)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
        method="GET",
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = resp.read()
    except (HTTPError, URLError) as e:
        logging.warning("RSS fetch failed: %s", str(e))
        return []
    except Exception as e:
        logging.warning("RSS fetch failed: %s", str(e))
        return []

    try:
        root = ET.fromstring(data)
    except Exception as e:
        logging.warning("RSS parse failed: %s", str(e))
        return []

    items: list[RssItem] = []

    # RSS 2.0: <rss><channel><item>...
    for item in root.findall(".//item"):
        title = _first_text(item, "title")
        link = _first_text(item, "link")
        guid = _first_text(item, "guid") or link
        pub = _first_text(item, "pubDate")
        desc = _first_text(item, "description")
        img = _extract_image_url(item)

        if not guid and not link and not title:
            continue

        items.append(RssItem(
            id=guid or link or title,
            title=title,
            link=link,
            published=pub,
            summary=desc,
            image_url=img,
        ))

    # Atom: <feed><entry>...
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns):
            title = _first_text(entry, "{http://www.w3.org/2005/Atom}title")
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = (link_el.attrib.get("href") or "").strip() if link_el is not None else ""
            guid = _first_text(entry, "{http://www.w3.org/2005/Atom}id") or link
            pub = _first_text(entry, "{http://www.w3.org/2005/Atom}updated") or _first_text(entry, "{http://www.w3.org/2005/Atom}published")
            summary = _first_text(entry, "{http://www.w3.org/2005/Atom}summary")
            if not guid and not link and not title:
                continue
            items.append(RssItem(
                id=guid or link or title,
                title=title,
                link=link,
                published=pub,
                summary=summary,
                image_url=None,
            ))

    return items


def normalize_rss_items(items: list[RssItem], author_urn: str) -> list[dict[str, Any]]:
    """Normalize RSS items to the same shape as LinkedIn REST items expected by the front-end."""
    out: list[dict[str, Any]] = []
    for it in items:
        out.append({
            "urn": it.id,
            "author": author_urn,
            "createdAt": it.published,
            "lastModifiedAt": it.published,
            "text": it.title or it.summary or "",
            "link": it.link,
            "imageUrl": it.image_url,
            "raw": {
                "title": it.title,
                "summary": it.summary,
                "published": it.published,
                "link": it.link,
                "imageUrl": it.image_url,
            },
        })
    return out
