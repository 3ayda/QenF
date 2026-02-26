"""
scraper_gestev.py – Activités Famille
                    Gestev  (gestev.com)

Source : https://www.gestev.com/calendrier-evenements/
         ?page=0&categories[0]=famille

Gestev is a Québecor event management platform. Their calendar page
uses query-param pagination (page=0, page=1, …) with the famille
category filter. All events from this filtered listing are
family-appropriate — no secondary public filter needed.

Usage : python scraper_gestev.py   → adds to evenements.json
        Called by scraper.py orchestrator → returns list
"""

import json
import re
import sys
import time
from datetime import date
from urllib.parse import urljoin, urlencode, quote

import requests
from bs4 import BeautifulSoup
from quartier import resoudre_quartier

# ── Constants ─────────────────────────────────────────────────────

BASE_URL    = "https://www.gestev.com"
LIST_URL    = (
    f"{BASE_URL}/calendrier-evenements/"
    "?page=0&salle=&categories%5B0%5D=famille"
    "&categoriesm=&regions=&date=&dateEnd="
)
OUTPUT_FILE = "evenements.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE_URL,
}

# ── Date window: current month + next month ───────────────────────

_today   = date.today()
_nm      = _today.month % 12 + 1
_ny      = _today.year + (_today.month // 12)
DATE_MIN = date(_today.year, _today.month, 1)
DATE_MAX = date(
    _ny, _nm,
    [31, 28 + (_ny % 4 == 0 and (_ny % 100 != 0 or _ny % 400 == 0)),
     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][_nm - 1]
)

MONTHS_FR = {
    "janvier":1, "février":2, "mars":3, "avril":4,
    "mai":5,     "juin":6,    "juillet":7, "août":8,
    "septembre":9, "octobre":10, "novembre":11, "décembre":12,
}

# Regex: matches "28 février 2026" or "28 février" (no year)
DATE_RE = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+(?:\s+\d{4})?"
DATE_RE_FULL = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"

# ── Helpers ───────────────────────────────────────────────────────

def fetch(url, retries=3, delay=1.2):
    """Download a page and return BeautifulSoup, or None."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.HTTPError as e:
            print(f"  ⚠️  HTTP {e.response.status_code} ({attempt+1}/{retries}) {url}")
            if e.response.status_code in (403, 404, 410):
                return None       # don't retry on hard errors
            time.sleep(2 ** attempt)
        except requests.RequestException as e:
            print(f"  ⚠️  ({attempt+1}/{retries}) {e}")
            time.sleep(2 ** attempt)
    return None


def page_url(page_num: int) -> str:
    """Build URL for page N (0-indexed)."""
    return (
        f"{BASE_URL}/calendrier-evenements/"
        f"?page={page_num}&salle=&categories%5B0%5D=famille"
        "&categoriesm=&regions=&date=&dateEnd="
    )


def parse_date_fr(text: str):
    """Parse '28 février 2026' → date object, or None."""
    if not text:
        return None
    m = re.search(DATE_RE_FULL, text.lower())
    if not m:
        return None
    m2 = re.match(r"(\d{1,2})\s+([A-Za-z\u00C0-\u024F]+)\s+(\d{4})", m.group(0).lower())
    if not m2:
        return None
    month = MONTHS_FR.get(m2.group(2))
    if not month:
        return None
    try:
        return date(int(m2.group(3)), month, int(m2.group(1)))
    except ValueError:
        return None


def extract_date_str(raw: str) -> str:
    """
    Normalize Gestev date strings. Handles:
      "Samedi 28 février 2026"
      "28 février 2026 au 8 mars 2026"
      "Du 28 février au 8 mars 2026"
      "28 février au 8 mars 2026"    ← year only on end date
      "Jusqu'au 30 juin 2026"
      "28 février 2026"
    Returns a normalized string like "28 février 2026 au 8 mars 2026".
    """
    if not raw:
        return ""
    raw = raw.strip()

    DY  = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"
    DNY = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+"

    # "X au Y" with year on both
    m = re.search(rf"({DY})\s+au\s+({DY})", raw, re.I)
    if m:
        return f"{m.group(1)} au {m.group(2)}"

    # "Du X mois au Y mois YYYY" — year only at end
    m2 = re.search(rf"(?:du\s+)?({DNY})\s+au\s+({DY})", raw, re.I)
    if m2:
        year = re.search(r"\d{4}", m2.group(2)).group(0)
        return f"{m2.group(1)} {year} au {m2.group(2)}"

    # "Jusqu'au X YYYY"
    m3 = re.search(rf"jusqu['\u2019]au\s+({DY})", raw, re.I)
    if m3:
        return f"Jusqu'au {m3.group(1)}"

    # Single full date (may be preceded by day name like "Samedi")
    m4 = re.search(DY, raw, re.I)
    if m4:
        return m4.group(0)

    return ""


def in_window(date_str: str) -> bool:
    """Return True if date_str overlaps the DATE_MIN–DATE_MAX window."""
    if not date_str:
        return True   # no date = permanent, keep

    DY = DATE_RE_FULL

    # Range
    m = re.search(rf"({DY})\s+au\s+({DY})", date_str, re.I)
    if m:
        s = parse_date_fr(m.group(1))
        e = parse_date_fr(m.group(2))
        if s and e:
            return s <= DATE_MAX and e >= DATE_MIN

    # Jusqu'au
    m2 = re.search(rf"jusqu['\u2019]au\s+({DY})", date_str, re.I)
    if m2:
        e = parse_date_fr(m2.group(1))
        if e:
            return e >= DATE_MIN

    # Single date
    d = parse_date_fr(date_str)
    if d:
        return DATE_MIN <= d <= DATE_MAX

    return True


def detect_theme(categorie: str, titre: str) -> str:
    combined = (categorie + " " + titre).lower()
    # Sport must be checked before art (patin, patinoire contain no "art" but karting does)
    if any(k in combined for k in ["sport", "hockey", "ski", "course", "natation",
                                    "soccer", "basket", "patin", "karting", "vélo",
                                    "olympique", "tournoi", "compétition"]):
        return "sport"
    # Spectacle: ice shows, theatre, circus, magic, Disney-type productions
    if any(k in combined for k in ["spectacle", "cirque", "magie", "humour", "théâtre",
                                    "theater", "theatre", "comédie", "comedie",
                                    "disney", "glace", "sur glace", "holiday on ice",
                                    "show", "revue", "cabaret", "marionnette",
                                    "illusion", "prestidigit", "clown"]):
        return "spectacle"
    # Arts & Ateliers — use word-boundary-like check: "art" as whole word or "atelier"
    if re.search(r"\barts?\b|\batelier", combined):
        return "arts"
    if any(k in combined for k in ["bricolage", "création", "creatif", "créatif",
                                    "dessin", "peinture", "sculpture", "poterie"]):
        return "arts"
    if any(k in combined for k in ["cinéma", "cinema", "film"]):
        return "cinéma"
    if any(k in combined for k in ["concert", "musique", "chanson", "orchestre"]):
        return "musique"
    if any(k in combined for k in ["visite", "guidée", "découverte", "patrimoine"]):
        return "visite guidée"
    if any(k in combined for k in ["expo", "exposition", "musée"]):
        return "exposition"
    return "événement spécial"


def detect_age(description: str, titre: str) -> str:
    text = (description + " " + titre).lower()
    m = re.search(r"(\d+)\s*(?:ans?|year)", text)
    if m:
        age = int(m.group(1))
        if age <= 5:  return "0-5 ans"
        if age <= 12: return f"{age} ans et +"
        return "Adolescents"
    if any(k in text for k in ["bébé", "bambin", "poussette", "tout-petit"]):
        return "0-5 ans"
    return "Tous"


def normalize_price(raw: str) -> str:
    """
    Normalize a raw price string to a clean display value.
    - Extracts all dollar amounts, returns "À partir de X $" with the lowest.
    - Handles "gratuit" → "Gratuit"
    - Handles "inclus" → "Inclus avec le billet"
    - Falls back to "Voir le site"
    """
    if not raw:
        return "Voir le site"
    low = raw.lower().strip()
    if "gratuit" in low:
        return "Gratuit"
    if "inclus" in low:
        return "Inclus avec le billet"

    # Find all numeric amounts: "29.50 $", "29,50$", "$29.50", "29 $", "29.50"
    amounts = []
    # Pattern covers: optional $ prefix, digits, optional decimal, optional $ suffix
    for m in re.finditer(
        r"\$?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*\$?",
        raw
    ):
        val_str = m.group(1).replace(",", ".")
        try:
            val = float(val_str)
            if 1 <= val <= 999:   # sanity range: ignore years (2026) and tiny noise
                amounts.append(val)
        except ValueError:
            pass

    if amounts:
        lowest = min(amounts)
        # Format: no decimals if .00, otherwise 2 decimal places
        if lowest == int(lowest):
            formatted = f"{int(lowest)} $"
        else:
            formatted = f"{lowest:.2f} $".replace(".", ",")
        return f"À partir de {formatted}"

    # No amount found — return a cleaned short string or fallback
    cleaned = re.sub(r"\s{2,}", " ", raw).strip()
    # Don't return bare numbers (years, codes) as price strings
    if re.fullmatch(r"[\d\s]+", cleaned):
        return "Voir le site"
    return cleaned[:60] if len(cleaned) > 2 else "Voir le site"


def best_image(soup_el, page_url: str = "") -> str:
    """
    Extract the best image URL from a soup element or full page.
    Handles all modern patterns:
      - <img src / data-src / data-lazy-src / data-original / data-bg>
      - <img srcset / data-srcset> (takes highest-res candidate)
      - <source srcset> inside <picture>
      - style="background-image: url(...)" on any element
      - data-bg / data-background attributes
      - og:image / twitter:image meta tags (when soup_el is the full page)
    Relative URLs are made absolute using BASE_URL.
    """
    SKIP = re.compile(
        r"placeholder|blank|pixel|logo|loading|spinner|avatar|icon|favicon"
        r"|1x1|transparent|spacer|data:image/gif",
        re.I
    )

    def clean(val: str) -> str:
        """Normalise a raw attribute value → absolute URL, or ''."""
        if not val:
            return ""
        # srcset: "url1 1x, url2 2x" or "url1 300w, url2 600w" → take last (largest)
        if " " in val.strip() and ("," in val or val.strip().split()[-1][-1] in "wx"):
            candidates = [p.strip().split()[0] for p in val.split(",") if p.strip()]
            val = candidates[-1] if candidates else val.split()[0]
        val = val.strip()
        if not val or val.startswith("data:"):
            return ""
        # Make absolute
        if val.startswith("//"):
            val = "https:" + val
        elif val.startswith("/"):
            val = BASE_URL.rstrip("/") + val
        if not val.startswith("http"):
            return ""
        if SKIP.search(val):
            return ""
        return val

    # 1. og:image / twitter:image meta — highest quality, only on full pages
    for meta in soup_el.find_all("meta"):
        prop = meta.get("property", "") + meta.get("name", "")
        if "og:image" in prop or "twitter:image" in prop:
            v = clean(meta.get("content", ""))
            if v:
                return v

    # 2. <picture> → <source srcset> (highest res)
    for source in soup_el.find_all("source"):
        v = clean(source.get("srcset", ""))
        if v:
            return v

    # 3. <img> — try attributes in priority order
    IMG_ATTRS = (
        "data-src", "data-lazy-src", "data-original",
        "data-srcset", "srcset", "src",
        "data-bg", "data-background",
    )
    for img in soup_el.find_all("img"):
        for attr in IMG_ATTRS:
            v = clean(img.get(attr, ""))
            if v:
                return v

    # 4. style="background-image: url(...)" on any element
    for el in soup_el.find_all(style=True):
        m = re.search(
            r"background(?:-image)?\s*:\s*url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)",
            el["style"], re.I
        )
        if m:
            v = clean(m.group(1))
            if v:
                return v

    # 5. data-bg / data-background on non-img elements (common in WordPress themes)
    for el in soup_el.find_all(attrs={"data-bg": True}):
        v = clean(el["data-bg"])
        if v:
            return v
    for el in soup_el.find_all(attrs={"data-background": True}):
        v = clean(el["data-background"])
        if v:
            return v

    return ""


# ── Listing page parser ───────────────────────────────────────────

def parse_listing(soup: BeautifulSoup) -> list:
    """
    Extract event stubs from a Gestev listing page.

    Gestev page structure (confirmed from live example):
      <div class="card / event-card / …">
        <a href="/calendrier-evenements/{slug}/">   ← internal detail link
          <img …>
          <h3>EVENT TITLE</h3>
          <span>Venue name</span>
          <span>28 février 2026</span>
        </a>
        <a href="https://www.ticketmaster.ca/…">Billets</a>  ← CTA, IGNORE
      </div>

    Strategy:
      1. Find all <a> whose href contains '/calendrier-evenements/' and a
         slug (i.e. more than just the base listing path).
      2. For each such anchor, walk UP to its card container (parent/grandparent)
         so we can also read sibling text (venue, date) outside the <a>.
      3. Skip any <a> whose text is a CTA word ("billets", "acheter", etc.)
         or whose href points to an external domain.
    """
    events = []
    seen   = set()

    CTA_WORDS = {"billets", "acheter", "buy", "tickets", "réserver",
                 "commander", "voir", "more", "details"}

    def is_detail_href(href: str) -> bool:
        """True if href is an internal Gestev event detail URL."""
        if not href:
            return False
        # Must contain /calendrier-evenements/ AND a slug (not just the listing root)
        if "/calendrier-evenements/" not in href:
            return False
        # Must be internal (no external domain after the path segment)
        clean = href.split("?")[0].rstrip("/")
        slug  = clean.split("/calendrier-evenements/")[-1].strip("/")
        return len(slug) > 0   # has an actual slug, not just the listing page

    def card_container(a_tag):
        """Walk up from <a> to find the nearest block that looks like a card."""
        el = a_tag.parent
        for _ in range(4):   # at most 4 levels up
            if el is None or el.name in ("body", "main", "section", "html"):
                return a_tag  # give up, use the <a> itself
            cls = " ".join(el.get("class", [])).lower()
            if any(k in cls for k in ("card", "event", "item", "article", "post")):
                return el
            el = el.parent
        return a_tag.parent or a_tag

    # ── Strategy 1: <a href*='/calendrier-evenements/{slug}'> ────────
    detail_links = [
        a for a in soup.find_all("a", href=True)
        if is_detail_href(a.get("href", ""))
    ]

    # ── Strategy 2: fallback — any <a> containing img + heading ──────
    if not detail_links:
        print("   ⚠️  Strategy 1 found 0 links — falling back to img+heading scan")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href or href == "#" or href.startswith("javascript"):
                continue
            # Skip external CTA links
            if href.startswith("http") and BASE_URL not in href:
                continue
            if a.find(["h2", "h3", "h4"]) and a.find("img"):
                link_text = a.get_text(strip=True).lower()
                if link_text not in CTA_WORDS:
                    detail_links.append(a)

    for a in detail_links:
        href = a.get("href", "")
        if not href:
            continue

        # Skip CTAs: short all-lowercase text matching known button words
        link_text = a.get_text(strip=True)
        if link_text.lower().strip() in CTA_WORDS or len(link_text) < 3:
            continue

        # Skip external URLs (ticketmaster, etc.)
        full_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/") + "/"
        if BASE_URL not in full_url:
            continue
        if full_url in seen or full_url == BASE_URL + "/":
            continue
        seen.add(full_url)

        # Use the card container so we can read ALL text (including outside <a>)
        container = card_container(a)

        # ── Title: h1>h2>h3>h4 inside container; skip CTA <a> text ──
        titre = ""
        for tag in ("h1", "h2", "h3", "h4"):
            el = container.find(tag)
            if el:
                t = el.get_text(strip=True)
                if t and len(t) > 2:
                    titre = t
                    break
        if not titre:
            # Try alt text of the main image
            img = container.find("img")
            if img:
                titre = img.get("alt", "").strip()
        if not titre or len(titre) < 3:
            continue

        # ── Image ──────────────────────────────────────────────────
        image = best_image(container)

        # ── All visible text in the card ───────────────────────────
        card_text = container.get_text(" ", strip=True)

        # ── Date ───────────────────────────────────────────────────
        date_str = extract_date_str(card_text)

        # ── Venue — first short text chunk that isn't title or date ─
        lieu_raw = ""
        for el in container.find_all(["span", "p", "div", "li"]):
            t = el.get_text(strip=True)
            if (t and t != titre
                    and t.lower() not in CTA_WORDS
                    and not re.search(r"\d{4}", t)
                    and 3 < len(t) < 80):
                lieu_raw = t
                break

        # ── Price ──────────────────────────────────────────────────
        prix_raw = ""
        for string in container.stripped_strings:
            if re.search(r"\$|gratuit|inclus", string, re.I):
                prix_raw = string.strip()
                break

        # ── Category badge ─────────────────────────────────────────
        categorie = ""
        for el in container.find_all(["span", "div"]):
            cls = " ".join(el.get("class", []))
            t   = el.get_text(strip=True)
            if any(k in cls.lower() for k in ("categ", "tag", "badge", "type", "label")):
                if t and len(t) < 40:
                    categorie = t
                    break

        events.append({
            "titre":     titre,
            "url":       full_url,
            "image":     image,
            "date_str":  date_str,
            "lieu_raw":  lieu_raw,
            "prix_raw":  prix_raw,
            "categorie": categorie,
        })

    return events


def has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Return True if there appears to be a next page."""
    # Gestev uses ?page=N — look for a link with page=(current+1)
    next_page_num = current_page + 1
    # Check for explicit next links
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if f"page={next_page_num}" in href:
            return True
    # Check for "next" / "suivant" pagination buttons
    for a in soup.find_all("a"):
        txt = a.get_text(strip=True).lower()
        if txt in ("suivant", "next", "›", "»", ">"):
            return True
    # Check for a disabled/active page indicator beyond current
    for el in soup.find_all(string=re.compile(rf"\b{next_page_num}\b")):
        parent = el.parent
        if parent and parent.name == "a":
            return True
    return False


# ── Detail page scraper ────────────────────────────────────────────

def scrape_detail(url: str) -> dict:
    """Fetch event detail page for richer data: title, description, price, image, lieu."""
    soup = fetch(url)
    if not soup:
        return {}

    body = soup.find("main") or soup.find("article") or soup.body
    if not body:
        return {}

    full_text = body.get_text(" ", strip=True)

    # ── Title — from <h1> on the detail page (most reliable) ─────────
    titre = ""
    h1 = body.find("h1")
    if h1:
        titre = h1.get_text(strip=True)
    # Fallback: og:title meta
    if not titre:
        og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
        if og:
            titre = og.get("content", "").strip()

    # ── Image — full-page pass (og:image first, then body) ───────────
    # Pass the full soup so og:image meta in <head> is found
    image = best_image(soup)
    if not image:
        image = best_image(body)

    # ── Description — multi-strategy ─────────────────────────────────
    desc = ""
    JUNK = re.compile(
        r"cookie|politique de confidentialité|©|javascript|droits réservés"
        r"|all rights reserved|newsletter|abonnez|inscrivez|partager|share"
        r"|facebook|twitter|instagram|linkedin|youtube",
        re.I
    )

    # Strategy A: og:description meta (cleanest, editor-written)
    og_desc = (soup.find("meta", property="og:description")
               or soup.find("meta", attrs={"name": "description"}))
    if og_desc:
        v = og_desc.get("content", "").strip()
        if len(v) > 30 and not JUNK.search(v):
            desc = v[:500]

    # Strategy B: explicit description container by class/id/itemprop
    if not desc:
        for selector in [
            "[class*='description']", "[class*='intro']", "[class*='summary']",
            "[class*='content']",     "[class*='texte']",  "[class*='text']",
            "[class*='body']",        "[class*='excerpt']","[class*='about']",
            "[itemprop='description']",
        ]:
            try:
                el = body.select_one(selector)
            except Exception:
                el = None
            if el:
                t = el.get_text(" ", strip=True)
                if len(t) > 50 and not JUNK.search(t):
                    desc = t[:500]
                    break

    # Strategy C: schema.org JSON-LD block
    if not desc:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json as _json
                data = _json.loads(script.string or "")
                # data can be a list or dict
                items = data if isinstance(data, list) else [data]
                for item in items:
                    v = item.get("description", "")
                    if isinstance(v, str) and len(v) > 30:
                        desc = v[:500]
                        break
            except Exception:
                pass
            if desc:
                break

    # Strategy D: walk all <p> tags — first one > 60 chars that isn't junk
    if not desc:
        for p in body.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 60 and not JUNK.search(t):
                desc = t[:500]
                break

    # Strategy E: walk <div> / <section> text blocks (when no <p> available)
    if not desc:
        for el in body.find_all(["div", "section"]):
            # Skip deeply nested wrappers — only look at "leaf-ish" blocks
            children_tags = [c.name for c in el.children if hasattr(c, "name") and c.name]
            if "div" in children_tags or "section" in children_tags:
                continue
            t = el.get_text(" ", strip=True)
            if len(t) > 80 and not JUNK.search(t):
                desc = t[:500]
                break

    # Clean up description: collapse whitespace, strip HTML artefacts
    if desc:
        desc = re.sub(r"\s{2,}", " ", desc).strip()

    # ── Venue ─────────────────────────────────────────────────────────
    lieu = ""
    venue_patterns = [
        r"(Centre\s+Vidéotron|Centre\s+Videotron)",
        r"((?:Centre|Salle|Colisée|Amphithéâtre|Aréna|Théâtre|Place|Agora|Pavillon|Auditorium)"
        r"[^,\n\.\<]{3,60})",
        r"(\d{1,4}\s+[A-Za-z\u00C0-\u024F][^,\n]{5,50},\s*Québec)",
    ]
    for pattern in venue_patterns:
        m = re.search(pattern, full_text, re.I)
        if m:
            lieu = m.group(1).strip()
            break
    if not lieu:
        # schema.org / microdata location
        for el in body.find_all(True, attrs={"itemprop": "location"}):
            t = el.get_text(strip=True)
            if t:
                lieu = t[:80]
                break
    if not lieu:
        # CSS class heuristic
        for el in body.find_all(
            attrs={"class": re.compile(r"venue|location|place|salle", re.I)}
        ):
            t = el.get_text(strip=True)
            if t and len(t) < 80:
                lieu = t
                break
    # schema.org JSON-LD location
    if not lieu:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json as _json
                data = _json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    loc = item.get("location", {})
                    if isinstance(loc, dict):
                        name = loc.get("name", "")
                        addr = loc.get("address", "")
                        if isinstance(addr, dict):
                            addr = addr.get("streetAddress", "")
                        lieu = (name or addr or "").strip()[:80]
                    if lieu:
                        break
            except Exception:
                pass
            if lieu:
                break

    # ── Price ─────────────────────────────────────────────────────────
    prix_raw = ""
    for kw_pattern in [
        r"(?:prix|tarif|coût|admission|billet)[^\n:]*:?\s*([^\n]{3,60})",
        r"(gratuit\b[^\n]{0,40})",
        r"(\d+[\s,\.]\d*\s*\$[^\n]{0,40})",
        r"(\$\s*\d+[^\n]{0,40})",
    ]:
        m = re.search(kw_pattern, full_text, re.I)
        if m:
            prix_raw = m.group(1).strip()
            break

    # ── Date ──────────────────────────────────────────────────────────
    date_str = extract_date_str(full_text)

    return {
        "titre":       titre,
        "description": desc,
        "image":       image,
        "lieu":        lieu,
        "prix_raw":    prix_raw,
        "date_str":    date_str,
    }


# ── Main ──────────────────────────────────────────────────────────

def main() -> list:
    print("🔍 Scraping – Gestev (Famille)")
    print(f"   Source : {LIST_URL}\n")
    print(f"   Fenêtre : {DATE_MIN} → {DATE_MAX}\n")

    # ── 1. Collect all listing pages ─────────────────────────────
    all_cards: list = []
    page = 0
    max_empty_pages = 2   # stop after N consecutive empty pages (safety)
    empty_streak    = 0

    while True:
        url = page_url(page)
        print(f"   → Page {page} : {url}")
        soup = fetch(url)
        if not soup:
            print(f"   ⚠️  Page {page} inaccessible – arrêt.")
            break

        cards = parse_listing(soup)
        if cards:
            print(f"      {len(cards)} carte(s) trouvée(s)")
            all_cards.extend(cards)
            empty_streak = 0
        else:
            empty_streak += 1
            print(f"      Aucune carte (streak={empty_streak})")
            if empty_streak >= max_empty_pages:
                break

        if not has_next_page(soup, page):
            break

        page += 1
        time.sleep(1.0)   # be polite

    # ── 2. Deduplicate ───────────────────────────────────────────
    seen, unique = set(), []
    for c in all_cards:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)

    print(f"\n📋 {len(unique)} événement(s) unique(s) trouvé(s).")

    if not unique:
        print("⚠️  Aucun événement – vérifiez les sélecteurs HTML.")
        print("   Conseil : lancez python -c \"import scraper_gestev; scraper_gestev._debug()\"")
        return []

    # ── 3. Enrich with detail pages + filter by date window ──────
    evenements: list = []
    skipped = 0

    CTA_TITLES = {"billets", "acheter", "buy", "tickets", "réserver",
                  "commander", "voir plus", "more", "details"}

    for i, card in enumerate(unique):
        titre = card["titre"]
        print(f"   [{i+1}/{len(unique)}] {titre}")

        # Quick date filter before fetching detail
        if card["date_str"] and not in_window(card["date_str"]):
            print(f"        ⏩ Hors fenêtre ({card['date_str']}) – ignoré.")
            skipped += 1
            continue

        detail    = scrape_detail(card["url"])
        time.sleep(0.8)

        # Prefer the detail-page <h1> title — it's authoritative
        # Override listing title if it looks like a CTA or is very short
        detail_titre = detail.get("titre", "").strip()
        if detail_titre and (
            titre.lower().strip() in CTA_TITLES
            or len(titre) < 5
            or not any(c.isalpha() for c in titre)
        ):
            titre = detail_titre
            print(f"        ℹ️  Titre corrigé → {titre}")

        # Skip if we still have no real title
        if not titre or titre.lower().strip() in CTA_TITLES or len(titre) < 3:
            print(f"        ⏩ Titre invalide – ignoré.")
            skipped += 1
            continue

        # Merge data — detail wins over listing stub
        date_str  = card["date_str"] or detail.get("date_str", "")
        prix_raw  = card["prix_raw"] or detail.get("prix_raw", "")
        image     = card["image"]    or detail.get("image", "")
        desc      = detail.get("description", "")

        # Post-detail date filter
        if date_str and not in_window(date_str):
            print(f"        ⏩ Hors fenêtre ({date_str}) – ignoré.")
            skipped += 1
            continue

        # Lieu: prefer detail page, then listing stub, then fallback
        lieu_detail = detail.get("lieu", "")
        lieu_card   = card.get("lieu_raw", "")
        if lieu_detail:
            lieu = lieu_detail
        elif lieu_card:
            lieu = f"Gestev – {lieu_card}"
        else:
            lieu = "Gestev – Québec"

        evenements.append({
            "titre":       titre,
            "lieu":        lieu,
            "quartier":    resoudre_quartier(lieu),
            "theme":       detect_theme(card.get("categorie", ""), titre),
            "age":         detect_age(desc, titre),
            "semaine":     "",
            "date":        date_str,
            "prix":        normalize_price(prix_raw),
            "image":       image,
            "description": desc,
            "URL":         card["url"],
        })

    print(f"\n✅ Gestev : {len(evenements)} événement(s) retenu(s) ({skipped} ignoré(s)).")
    return evenements


# ── Debug helper ─────────────────────────────────────────────────

def _debug():
    """
    Diagnostic tool: prints the raw HTML structure of the listing page
    to help adjust selectors if the site changes.
    Run with: python -c "import scraper_gestev; scraper_gestev._debug()"
    """
    print(f"Fetching {LIST_URL} …\n")
    soup = fetch(LIST_URL)
    if not soup:
        print("❌ Could not fetch page.")
        return

    # Show all <a> tags pointing to /calendrier-evenements/{slug}/
    print("── <a href*='/calendrier-evenements/'> links (strategy 1) ──")
    found = 0
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/calendrier-evenements/" in href:
            slug = href.split("/calendrier-evenements/")[-1].strip("/")
            if slug:   # has a real slug
                found += 1
                print(f"  [{found}] href={href[:80]}  text={a.get_text(strip=True)[:40]!r}")
    if not found:
        print("  (none found — check if URL pattern changed)")

    print("\n── All <a> on page (first 20, with text) ──")
    for i, a in enumerate(soup.find_all("a", href=True)[:20]):
        print(f"  href={a.get('href','')[:70]}  text={a.get_text(strip=True)[:40]!r}")

    print("\n── First 3 cards (any <a> with img+heading) ──")
    count = 0
    for a in soup.find_all("a", href=True):
        if a.find(["h2","h3","h4"]) and a.find("img") and count < 3:
            print(f"\n  CARD href={a.get('href','')[:60]}")
            for el in a.find_all(["h2","h3","h4","p","span","div","img"], limit=10):
                txt = el.get_text(strip=True)[:60]
                src = el.get("src","")[:60] if el.name=="img" else ""
                print(f"    <{el.name}> class={el.get('class',[])} text={txt!r} src={src!r}")
            count += 1

    print("\n── Page raw text (first 2000 chars) ──")
    print(soup.get_text(" ", strip=True)[:2000])


def _debug_detail(url: str = "https://www.gestev.com/calendrier-evenements/disney-sur-glace/"):
    """
    Diagnostic tool: print exactly what scrape_detail extracts from a given URL.
    Run with: python -c "import scraper_gestev; scraper_gestev._debug_detail()"
    """
    print(f"Fetching detail: {url}\n")
    result = scrape_detail(url)
    for k, v in result.items():
        print(f"  {k:15}: {str(v)[:200]!r}")

    # Also dump raw <head> meta and first img tags for diagnosis
    soup = fetch(url)
    if not soup:
        return
    print("\n── <meta> tags ──")
    for m in soup.find_all("meta")[:15]:
        print(f"  {dict(m.attrs)}")
    print("\n── first 10 <img> tags ──")
    for img in soup.find_all("img")[:10]:
        print(f"  {dict(img.attrs)}")
    print("\n── JSON-LD scripts ──")
    for script in soup.find_all("script", type="application/ld+json"):
        print(f"  {(script.string or '')[:300]}")


# ── Standalone run ───────────────────────────────────────────────

if __name__ == "__main__":
    results = main()
    try:
        existing = json.load(open(OUTPUT_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    # Remove stale Gestev entries before re-adding
    existing = [e for e in existing if "gestev.com" not in e.get("URL", "")]
    existing.extend(results)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"💾 {len(existing)} événements total dans {OUTPUT_FILE}.")
