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
    if any(k in combined for k in ["atelier", "bricolage", "création", "art"]):
        return "arts"
    if any(k in combined for k in ["spectacle", "cirque", "magie", "humour"]):
        return "événement spécial"
    if any(k in combined for k in ["cinéma", "cinema", "film"]):
        return "cinéma"
    if any(k in combined for k in ["concert", "musique", "chanson"]):
        return "musique"
    if any(k in combined for k in ["visite", "guidée", "découverte"]):
        return "visite guidée"
    if any(k in combined for k in ["expo", "exposition", "musée"]):
        return "exposition"
    if any(k in combined for k in ["sport", "hockey", "ski", "course", "natation",
                                    "soccer", "basket", "patin"]):
        return "sport"
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
    if not raw:
        return "Voir le site"
    low = raw.lower().strip()
    if "gratuit" in low:
        return "Gratuit"
    if "inclus" in low:
        return "Inclus avec le billet d'entrée"
    # Keep a short price string, drop trailing junk
    cleaned = re.sub(r"\s{2,}", " ", raw).strip()
    return cleaned[:80] if cleaned else "Voir le site"


def best_image(soup_el) -> str:
    """Extract the best image URL from a card or detail element."""
    for attr in ("src", "data-src", "data-lazy-src", "data-srcset"):
        for img in soup_el.find_all("img"):
            val = img.get(attr, "")
            if val and val.startswith("http") and not any(
                x in val for x in ["placeholder", "blank", "pixel", "logo", "loading"]
            ):
                # data-srcset may have "url 1x, url2 2x" — take first
                val = val.split(",")[0].split(" ")[0]
                return val
    # Also try style="background-image: url(…)"
    for el in soup_el.find_all(style=True):
        m = re.search(r"background(?:-image)?\s*:\s*url\(['\"]?(https?[^'\")\s]+)", el["style"])
        if m:
            return m.group(1)
    return ""


# ── Listing page parser ───────────────────────────────────────────

def parse_listing(soup: BeautifulSoup) -> list:
    """
    Extract event stubs from a listing page.
    Gestev's calendar uses cards with links to /evenement/{slug}/.
    We probe several selector strategies in order of specificity.
    """
    events = []
    seen   = set()

    # ── Strategy 1: any <a> pointing to /evenement/ detail pages ──
    candidates = soup.select(
        "a[href*='/evenement/'], "
        "a[href*='/event/'], "
        "a[href*='/spectacle/'], "
        "a[href*='/activite/']"
    )

    # ── Strategy 2: fallback — all cards with an <img> + <h2>/<h3> ──
    if not candidates:
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href or href == "#" or href.startswith("javascript"):
                continue
            if a.find(["h2", "h3", "h4"]) and a.find("img"):
                candidates.append(a)

    for a in candidates:
        href = a.get("href", "")
        if not href:
            continue
        full_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/") + "/"
        if full_url in seen or full_url == BASE_URL + "/":
            continue
        seen.add(full_url)

        # Title — h2 > h3 > h4 > alt text > link text
        titre = ""
        for tag in ("h2", "h3", "h4", "p"):
            el = a.find(tag)
            if el:
                t = el.get_text(strip=True)
                if t and len(t) > 2:
                    titre = t
                    break
        if not titre:
            titre = a.get_text(strip=True)[:80]
        if not titre or len(titre) < 3:
            continue

        # Image
        image = best_image(a)

        # All visible text in card
        card_text = a.get_text(" ", strip=True)

        # Date
        date_str = extract_date_str(card_text)

        # Lieu / Venue — look for text that isn't the title or date
        lieu_raw = ""
        for span in a.find_all(["span", "p", "div"]):
            t = span.get_text(strip=True)
            if (t and t != titre and not re.search(r"\d{4}", t)
                    and 3 < len(t) < 80 and t.lower() not in ("famille",)):
                lieu_raw = t
                break

        # Price — look for $ or "gratuit"
        prix_raw = ""
        for string in a.stripped_strings:
            if re.search(r"\$|gratuit|inclus", string, re.I):
                prix_raw = string.strip()
                break

        # Category span — often a badge/tag inside the card
        categorie = ""
        for el in a.find_all(["span", "div", "p"]):
            cls = " ".join(el.get("class", []))
            t   = el.get_text(strip=True)
            if ("categ" in cls.lower() or "tag" in cls.lower() or "badge" in cls.lower()
                    or "type" in cls.lower()):
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
    """Fetch event detail page for richer data: description, price, image, lieu."""
    soup = fetch(url)
    if not soup:
        return {}

    body = soup.find("main") or soup.find("article") or soup.body
    if not body:
        return {}

    full_text = body.get_text(" ", strip=True)

    # Description — first substantial paragraph
    desc = ""
    for p in body.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 60 and not re.search(r"cookie|politique|©", t, re.I):
            desc = t[:400]
            break

    # Better image from detail page
    image = best_image(body)

    # Venue — look for address or venue name patterns
    lieu = ""
    for pattern in [
        r"((?:Centre|Salle|Colisée|Amphithéâtre|Aréna|Place|Agora|Pavillon)[^,\n]{3,60})",
        r"((?:\d{1,4}\s+[A-Za-z\u00C0-\u024F]+(?:\s+[A-Za-z\u00C0-\u024F]+){1,4})[,\s]+Québec)",
    ]:
        m = re.search(pattern, full_text, re.I)
        if m:
            lieu = m.group(1).strip()
            break

    # Price
    prix_raw = ""
    # Look for structured price blocks first
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

    # Date — in case listing page missed it
    date_str = extract_date_str(full_text)

    return {
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

    # Show all <a> tags that look like event links
    print("── All <a> tags with /evenement/, /event/, /spectacle/ ──")
    for a in soup.select("a[href*='/evenement/'], a[href*='/event/'], a[href*='/spectacle/']"):
        print(f"  href={a.get('href', '')[:80]}  text={a.get_text(strip=True)[:40]}")

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

    print("\n── Page raw text (first 1500 chars) ──")
    print(soup.get_text(" ", strip=True)[:1500])


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
