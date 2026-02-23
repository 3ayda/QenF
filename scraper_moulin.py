"""
scraper_moulin.py – Activités familiales
                    Moulin des Jésuites  (moulindesjesuites.org)

WordPress / The Events Calendar — tout est family-friendly par nature.

Usage : python scraper_moulin.py   → ajoute au fichier evenements.json
"""

import json, re, sys, time
from datetime import date
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from quartier import resoudre_quartier

# ── Constantes ────────────────────────────────────────────────────
BASE_URL    = "https://www.moulindesjesuites.org"
LIST_URL    = f"{BASE_URL}/activites/"
OUTPUT_FILE = "evenements.json"
LIEU_FIXE   = "Moulin des Jésuites, 7960 boul. Henri-Bourassa, Charlesbourg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9",
}

MONTHS_FR = {
    "janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,
}

_today   = date.today()
_nm      = _today.month % 12 + 1
_ny      = _today.year + (_today.month // 12)
DATE_MIN = date(_today.year, _today.month, 1)
DATE_MAX = date(_ny, _nm,
    [31,28+(_ny%4==0 and(_ny%100!=0 or _ny%400==0)),
     31,30,31,30,31,31,30,31,30,31][_nm-1])

# ── Helpers ───────────────────────────────────────────────────────
def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            print(f"  ⚠️  ({attempt+1}/{retries}) {e}")
            time.sleep(2 ** attempt)
    return None


def parse_date_fr(text):
    text = text.lower().strip()
    m = re.search(r"(\d{1,2})\s+([A-Za-z\u00C0-\u024F]+)\s+(\d{4})", text)
    if m:
        month = MONTHS_FR.get(m.group(2))
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass
    return None


def in_window(date_str):
    if not date_str:
        return True
    D = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"
    m = re.search(rf"({D})\s+au\s+({D})", date_str, re.I)
    if m:
        s, e = parse_date_fr(m.group(1)), parse_date_fr(m.group(2))
        if s and e:
            return s <= DATE_MAX and e >= DATE_MIN
    d = parse_date_fr(date_str)
    if d:
        return DATE_MIN <= d <= DATE_MAX
    return True


def normalize_price(raw):
    if not raw:
        return "Voir le site"
    low = raw.lower().strip()
    if "gratuit" in low:
        return "Gratuit"
    # Clean up "13,80$ / famille" style
    raw = raw.strip().rstrip(".")
    return raw


def detect_age_moulin(text):
    """Cherche 'Public cible: X-Y ans' dans le texte."""
    m = re.search(r"public\s+cible\s*[:\-]\s*([\d\s\-àa]+\s*ans?)", text, re.I)
    if m:
        ages = m.group(1).strip()
        nums = re.findall(r"\d+", ages)
        if nums:
            mn = int(nums[0])
            if mn <= 5:   return "0-5 ans"
            if mn <= 12:  return f"{mn} ans et +"
            return "Adolescents"
    if "famille" in text.lower():
        return "Familles"
    return "Tous"


def detect_theme_moulin(titre, categories):
    combined = (titre + " " + " ".join(categories)).lower()
    if "atelier" in combined:              return "arts"
    if "rallye" in combined:               return "événement spécial"
    if "circuit" in combined:              return "visite guidée"
    if "visite" in combined:               return "visite guidée"
    if "exposition" in combined:           return "exposition"
    if "spectacle" in combined:            return "événement spécial"
    if "conte" in combined:                return "arts"
    return "événement spécial"


# ── ISO date from Google Calendar link ───────────────────────────
def extract_iso_dates(soup):
    """
    The Events Calendar embeds ISO dates in Google Calendar links.
    Extract start/end dates from: dates=20260228T000000/20260308T235959
    """
    gcal = soup.find("a", href=re.compile(r"google\.com/calendar.*dates="))
    if not gcal:
        return None, None
    m = re.search(r"dates=(\d{8})", gcal["href"])
    if not m:
        return None, None
    raw = m.group(1)
    try:
        yr, mo, dy = int(raw[:4]), int(raw[4:6]), int(raw[6:8])
        start = date(yr, mo, dy)
    except ValueError:
        return None, None

    # End date
    m2 = re.search(r"dates=\d+[T/](\d{8})", gcal["href"])
    if m2:
        raw2 = m2.group(1)
        try:
            yr2, mo2, dy2 = int(raw2[:4]), int(raw2[4:6]), int(raw2[6:8])
            end = date(yr2, mo2, dy2)
        except ValueError:
            end = start
    else:
        end = start
    return start, end


def format_date_range(start, end):
    MONTH_NAMES = ["","janvier","février","mars","avril","mai","juin",
                   "juillet","août","septembre","octobre","novembre","décembre"]
    if not start:
        return ""
    if start == end:
        return f"{start.day} {MONTH_NAMES[start.month]} {start.year}"
    if start.month == end.month and start.year == end.year:
        return f"{start.day} au {end.day} {MONTH_NAMES[end.month]} {end.year}"
    return (f"{start.day} {MONTH_NAMES[start.month]} {start.year} "
            f"au {end.day} {MONTH_NAMES[end.month]} {end.year}")


# ── Parse listing ─────────────────────────────────────────────────
def parse_listing(soup):
    """
    The Events Calendar listing: each event in an article.tribe-event-calendar-list__event
    or similar wrapper. We look for event links /activite/{slug}/
    """
    events = []
    seen   = set()

    for a in soup.select("a[href*='/activite/']"):
        href = a.get("href", "")
        # Only detail pages: /activite/slug/ or /activite/slug/YYYY-MM-DD/
        if not re.search(r"/activite/[\w-]+", href):
            continue
        # Skip image-only links (no text)
        titre = a.get_text(strip=True)
        if not titre or len(titre) < 3:
            # Try parent heading
            parent = a.find_parent(["h2","h3","h4","article","div"])
            h = parent.find(["h2","h3","h4"]) if parent else None
            titre = h.get_text(strip=True) if h else ""
        if not titre:
            continue

        full_url = urljoin(BASE_URL, href)
        # Normalise URL (remove date suffix for dedup)
        canonical = re.sub(r"/\d{4}-\d{2}-\d{2}/$", "/", full_url)
        canonical = canonical.rstrip("/") + "/"
        if canonical in seen:
            continue
        seen.add(canonical)

        # Card container
        card = a.find_parent(["article", "li", "div"])

        # Image
        img   = card.find("img") if card else None
        image = img.get("src", "") if img else ""

        # Date text visible on listing (e.g. "28 février – 8 mars")
        date_vis = ""
        for tag in (card.find_all(["abbr","time","span","p"]) if card else []):
            t = tag.get_text(strip=True)
            if re.search(r"\d+\s+[A-Za-z\u00C0-\u024F]+", t):
                date_vis = t
                break

        # Price
        prix_raw = ""
        if card:
            for txt in card.find_all(string=True):
                s = txt.strip()
                if re.search(r"\$|gratuit", s, re.I) and len(s) < 80:
                    prix_raw = s
                    break

        # Short description
        desc_c = ""
        if card:
            for p in card.find_all("p"):
                t = p.get_text(" ", strip=True)
                if len(t) > 30:
                    desc_c = t[:300]
                    break

        # Category tags
        cats = []
        if card:
            for tag in card.select(".tribe-event-categories a, .cat-links a, [class*='categ'] a"):
                cats.append(tag.get_text(strip=True))

        events.append({
            "titre":    titre,
            "url":      full_url,
            "image":    image,
            "date_vis": date_vis,
            "prix_raw": prix_raw,
            "desc_courte": desc_c,
            "cats":     cats,
        })

    return events


# ── Scrape detail ─────────────────────────────────────────────────
def scrape_detail(url):
    soup = fetch(url)
    if not soup:
        return {}

    body = soup.find("main") or soup.body
    full_text = body.get_text(" ", strip=True) if body else ""

    # ISO dates from Google Calendar link (most reliable)
    start, end = extract_iso_dates(soup)

    # Fallback: parse visible date text
    if not start:
        D = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"
        DATE_RE = re.compile(rf"({D})(?:\s+au\s+({D}))?", re.I)
        dm = DATE_RE.search(full_text)
        if dm:
            start = parse_date_fr(dm.group(1))
            end   = parse_date_fr(dm.group(2)) if dm.group(2) else start

    # Description (first substantial paragraph)
    desc = ""
    if body:
        for p in body.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 60 and "$" not in t:
                desc = t[:400]
                break

    # Prix (from detail page, more complete)
    prix_raw = ""
    m = re.search(r"([\d,\.]+\s*\$[^\n]*|gratuit)", full_text, re.I)
    if m:
        prix_raw = m.group(0).strip()[:80]

    return {
        "start":    start,
        "end":      end,
        "description": desc,
        "prix_raw": prix_raw,
        "full_text": full_text,
    }


# ── Main ──────────────────────────────────────────────────────────
def main():
    print("🔍 Scraping – Moulin des Jésuites")
    print(f"   Source : {LIST_URL}\n")

    soup = fetch(LIST_URL)
    if not soup:
        print("❌ Impossible d'accéder à la page listing.")
        return []

    cards = parse_listing(soup)
    # Deduplicate by titre
    seen_titres, unique = set(), []
    for c in cards:
        if c["titre"] not in seen_titres:
            seen_titres.add(c["titre"])
            unique.append(c)
    cards = unique

    print(f"📋 {len(cards)} activités trouvées.")
    print(f"📅 Filtre : {DATE_MIN} → {DATE_MAX}\n")

    evenements = []
    skipped = 0

    for i, card in enumerate(cards):
        print(f"   [{i+1}/{len(cards)}] {card['titre']}")
        detail = scrape_detail(card["url"])
        time.sleep(0.5)

        start = detail.get("start")
        end   = detail.get("end") or start
        date_str = format_date_range(start, end)

        if start and not (start <= DATE_MAX and end >= DATE_MIN):
            print(f"        ⏩ Hors fenêtre ({date_str}) – ignoré.")
            skipped += 1
            continue

        full_text = detail.get("full_text", "")
        desc  = detail.get("description") or card.get("desc_courte", "")
        prix  = normalize_price(detail.get("prix_raw") or card.get("prix_raw", ""))

        evenements.append({
            "titre":       card["titre"],
            "lieu":        LIEU_FIXE,
            "quartier":    resoudre_quartier(LIEU_FIXE),
            "theme":       detect_theme_moulin(card["titre"], card.get("cats", [])),
            "age":         detect_age_moulin(full_text),
            "semaine":     "",
            "date":        date_str,
            "prix":        prix,
            "image":       card.get("image", ""),
            "description": desc,
            "URL":         card["url"],
        })

    print(f"\n✅ Moulin : {len(evenements)} événements retenus ({skipped} ignorés).")
    return evenements


if __name__ == "__main__":
    results = main()
    try:
        existing = json.load(open(OUTPUT_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing = [e for e in existing if "moulindesjesuites" not in e.get("URL","")]
    existing.extend(results)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"💾 {len(existing)} événements total dans {OUTPUT_FILE}.")
