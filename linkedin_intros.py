import re
import json
import time
from urllib.parse import urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# -----------------------------
# Put your URLs here OR load from a file (see main()).
# -----------------------------
URLS = [
    "https://www.linkedin.com/posts/stephens-inc-_stephens-educationfinance-publicfinance-activity-7421574252451049472-LAmF?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_investmentbanking-activity-7420130811317972994-4D8M?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_ipaa-privatecapitalconference-energycapital-activity-7419404836124647426-X_n0?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_today-we-honor-the-extraordinary-life-and-activity-7419016578815520769-GSva?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_investmentbanking-activity-7417989211741491200-4u2d?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_stephens-energy-eoy-activity-7417581366311194624-joaq?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_stephens-served-as-exclusive-sell-side-advisor-activity-7416765969903087616-mib6?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_stephens-sf-eoy-recap-activity-7415420433598013440-n7s7?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_stephens-tl-2025-recap-activity-7414784138903379968-b7F4?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_investmentbanking-activity-7415407016086589440-Jk9n?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_investmentbanking-activity-7415042497535721473-ZZfJ?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_investmentbanking-activity-7414682237654192128-61Ug?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_investmentbanking-activity-7414376072416256001--od4?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_happynewyear-activity-7412477754031452160-rtjb?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/stephens-inc-_market-rotations-accelerated-in-november-activity-7411491065343582208-LzR-?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
    "https://www.linkedin.com/posts/atlassianwilliamsracing_some-stories-arent-just-captured-on-track-ugcPost-7409369002428497921-zm31?utm_source=share&utm_medium=member_desktop&rcm=ACoAAAAoXVkBM2cc-KSh7SQMPYKZN4JhUS8k5qw",
]

def strip_tracking(url: str) -> str:
    """Remove query params; keep stable canonical URL."""
    parts = urlparse(url)
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))

def slug_fallback_intro(url: str) -> str:
    """
    Convert LinkedIn post URL slugs into clean, human titles.
    """
    path = urlparse(url).path.lower()

    # Extract the slug after /posts/
    slug = path.split("/posts/")[-1]

    # Remove activity / ugc IDs
    slug = re.sub(r"-(activity|ugcpost)-\d+.*$", "", slug)

    # Remove org handle prefix
    slug = re.sub(r"^stephens-inc-+", "", slug)

    # Replace separators with spaces
    slug = slug.replace("_", " ").replace("-", " ")

    # Normalize whitespace
    slug = re.sub(r"\s+", " ", slug).strip()

    # Common phrase cleanups
    replacements = {
        "educationfinance": "Education Finance",
        "publicfinance": "Public Finance",
        "investmentbanking": "Investment Banking",
        "privatecapitalconference": "Private Capital Conference",
        "energycapital": "Energy Capital",
        "happynewyear": "Happy New Year",
        "market rotations": "Market Rotations",
        "eoy": "End of Year",
        "sf": "SF",
        "tl": "TL",
    }

    for k, v in replacements.items():
        slug = slug.replace(k, v.lower())

    # Title case words
    words = [w.capitalize() for w in slug.split(" ") if w]
    title = " ".join(words)
    title = title.replace("Public Finance", "& Public Finance")
    # Add brand prefix once
    return f"Stephens | {title}" if title else "Stephens | LinkedIn Post"

    """
    Convert URL path bits into a readable title.
    Example: /posts/stephens-inc-_stephens-educationfinance-publicfinance-activity-742... -> "Stephens Educationfinance Publicfinance"
    """
    path = urlparse(url).path
    # Take the last chunk after /posts/
    chunk = path.split("/posts/")[-1] if "/posts/" in path else path.strip("/").split("/")[-1]
    # Remove the trailing activity/ugc IDs portion
    chunk = re.sub(r"-(activity|ugcPost)-\d+.*$", "", chunk, flags=re.IGNORECASE)
    # Remove leading org handle and extra separators
    chunk = re.sub(r"^[-_]+", "", chunk)
    chunk = chunk.replace("_", " ")
    chunk = re.sub(r"\s+", " ", chunk).strip()

    # Title-case, but keep acronyms if any
    words = [w for w in chunk.split(" ") if w]
    pretty = " ".join([w.upper() if w.isupper() else w.capitalize() for w in words])

    # Slight cleanup for very short/empty cases
    return pretty if pretty else "LinkedIn Post"

def looks_like_login_wall(html_text: str) -> bool:
    """
    Heuristic: LinkedIn often shows 'Sign in' or 'Join LinkedIn' pages.
    """
    s = html_text.lower()
    needles = [
        "join linkedin",
        "sign in",
        "signin",
        "authwall",
        "login",
        "challenge",
        "security verification",
    ]
    return any(n in s for n in needles)

def extract_meta(soup: BeautifulSoup, key: str, attr: str = "property") -> str | None:
    tag = soup.find("meta", attrs={attr: key})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None

def fetch_intro(session: requests.Session, url: str, timeout: int = 20) -> dict:
    canonical = strip_tracking(url)

    headers = {
        # A normal-ish browser UA helps avoid some generic blocks
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = session.get(canonical, headers=headers, timeout=timeout, allow_redirects=True)
        status = r.status_code
        text = r.text or ""
    except Exception as e:
        return {
            "url": canonical,
            "ok": False,
            "status": None,
            "title": slug_fallback_intro(canonical),
            "intro": "",
            "source": "error",
            "error": str(e),
        }

    # Parse HTML
    soup = BeautifulSoup(text, "lxml")

    og_title = extract_meta(soup, "og:title") or extract_meta(soup, "twitter:title", attr="name")
    og_desc  = extract_meta(soup, "og:description") or extract_meta(soup, "twitter:description", attr="name")

    # If LinkedIn blocks, these may be generic ("LinkedIn") or missing
    blocked = looks_like_login_wall(text) or (og_title in (None, "", "LinkedIn") and og_desc in (None, ""))

    if not blocked and (og_title or og_desc):
        title = og_title or slug_fallback_intro(canonical)
        intro = og_desc or ""
        return {
            "url": canonical,
            "ok": True,
            "status": status,
            "title": title,
            "intro": intro,
            "source": "open_graph",
        }

    # Fallback: derive something readable from slug
    title = slug_fallback_intro(canonical)

    return {
        "url": canonical,
        "ok": True,
        "status": status,
        "title": title,
        "intro": "",
        "source": "slug_fallback",
        "note": "LinkedIn page likely blocked to scripts (login wall).",
    }

def load_urls_from_file(path: str) -> list[str]:
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch LinkedIn post intro/title (best effort) for demo RSS.")
    parser.add_argument("--file", help="Text file containing URLs (one per line). If omitted, uses URLS in script.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between requests.")
    parser.add_argument("--out", default="items.json", help="Output JSON filename.")
    args = parser.parse_args()

    urls = load_urls_from_file(args.file) if args.file else URLS

    session = requests.Session()

    results = []
    for i, u in enumerate(urls, start=1):
        data = fetch_intro(session, u)
        results.append(data)
        print(f"[{i}/{len(urls)}] {data['source']:12} {data.get('status')}  {data['title']}")
        time.sleep(max(0.0, args.sleep))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(results)} items to {args.out}")

if __name__ == "__main__":
    main()
