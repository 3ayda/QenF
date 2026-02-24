"""
scraper_mcq.py – Activités Famille
                 Musée de la civilisation  (mcq.org)

WordPress site, filter f=11 = Famille public.
All events on this filtered listing are family-appropriate.

Usage : python scraper_mcq.py   → ajoute au fichier evenements.json
"""

import json, re, sys, time
from datetime import date
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from quartier import resoudre_quartier

# ── Constantes ────────────────────────────────────────────────────
BASE_URL    = "https://mcq.org"
LIST_URL    = f"{BASE_URL}/decouvrir/activites/?f=11&s"
OUTPUT_FILE = "evenements.json"
LIEU_FIXE   = "Musée de la civilisation, 85 rue Dalhousie, Vieux-Québec"

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


def extract_date_str(raw):
    """
    Handles:
      "28 février 2026 au 8 mars 2026"
      "Jusqu'au 30 juin 2026"
      "Du 28 février au 8 mars 2026"
    Returns normalised string or "".
    """
    if not raw:
        return ""
    DY  = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"
    DNY = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+"
    # Range with year on both sides
    m = re.search(rf"({DY})\s+au\s+({DY})", raw, re.I)
    if m:
        return f"{m.group(1)} au {m.group(2)}"
    # "Du X mois au Y mois YYYY"
    m2 = re.search(rf"(?:du\s+)?({DNY})\s+au\s+({DY})", raw, re.I)
    if m2:
        year = re.search(r"\d{4}", m2.group(2)).group(0)
        return f"{m2.group(1)} {year} au {m2.group(2)}"
    # "Jusqu'au X mois YYYY" → single end date
    m3 = re.search(rf"jusqu['\u2019]au\s+({DY})", raw, re.I)
    if m3:
        return f"Jusqu'au {m3.group(1)}"
    # Single date
    m4 = re.search(DY, raw, re.I)
    if m4:
        return m4.group(0)
    return ""


def in_window(date_str):
    """True if date_str overlaps DATE_MIN–DATE_MAX."""
    if not date_str:
        return True  # no date = permanent/ongoing → keep
    DY = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"
    # Range
    m = re.search(rf"({DY})\s+au\s+({DY})", date_str, re.I)
    if m:
        s = parse_date_fr(m.group(1))
        e = parse_date_fr(m.group(2))
        if s and e:
            return s <= DATE_MAX and e >= DATE_MIN
    # "Jusqu'au X" — end date only, assume it started already
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


def detect_theme(type_tag, titre):
    combined = (type_tag + " " + titre).lower()
    if "atelier" in combined:                        return "arts"
    if "spectacle" in combined:                      return "événement spécial"
    if "cinéma" in combined or "cinema" in combined: return "cinéma"
    if "visite" in combined:                         return "visite guidée"
    if "exposition" in combined:                     return "exposition"
    if "animation" in combined:                      return "événement spécial"
    if "jeu" in combined or "quiz" in combined:      return "événement spécial"
    if "conte" in combined:                          return "arts"
    return "événement spécial"


def detect_age(description, titre):
    text = (description + " " + titre).lower()
    m = re.search(r"(\d+)\s*(?:ans?|year)", text)
    if m:
        age = int(m.group(1))
        if age <= 5:  return "0-5 ans"
        if age <= 12: return f"{age} ans et +"
        return "Adolescents"
    if any(k in text for k in ["poussette", "bébé", "bambin", "tout-petit"]):
        return "0-5 ans"
    return "Tous"


def normalize_price(raw):
    if not raw:
        return "Inclus avec le billet d'entrée"
    low = raw.lower().strip()
    if "gratuit" in low:
        return "Gratuit"
    if "inclus" in low:
        return "Inclus avec le billet d'entrée"
    return raw.strip()


# ── Listing parser ────────────────────────────────────────────────
def parse_listing(soup):
    events = []
    seen   = set()

    # Each event card is an <a> linking to /decouvrir/activites/{slug}/
    for a in soup.select("a[href*='/decouvrir/activites/']"):
        href = a.get("href", "")
        # Skip pagination, filter links, and the main listing link
        if not re.search(r"/decouvrir/activites/[\w-]+/?$", href):
            continue
        full_url = urljoin(BASE_URL, href).rstrip("/") + "/"
        if full_url in seen:
            continue
        seen.add(full_url)

        # Image — use the real src (not data: placeholder)
        image = ""
        for img in a.find_all("img"):
            src = img.get("src", "")
            if src.startswith("http") and "wp-content/uploads" in src:
                image = src
                break

        # Title — h2 inside the card
        h2 = a.find("h2")
        titre = h2.get_text(strip=True) if h2 else a.get_text(strip=True)
        if not titre or len(titre) < 3:
            continue

        # All text nodes in card
        card_text = a.get_text(" ", strip=True)

        # Date — appears as "28 février 2026 au 8 mars 2026" or "Jusqu'au 30 juin 2026"
        date_str = extract_date_str(card_text)

        # Type tag ("Activité autonome", "Atelier éducatif", "Spectacle"…)
        # It's a small text node before or after the h2
        type_tag = ""
        for txt in a.stripped_strings:
            t = txt.strip()
            if t == titre:
                continue
            if re.search(r"\d", t):  # skip date strings
                continue
            if len(t) > 3 and len(t) < 50:
                type_tag = t
                break

        events.append({
            "titre":    titre,
            "url":      full_url,
            "image":    image,
            "date_str": date_str,
            "type_tag": type_tag,
        })

    return events


# ── Detail page ───────────────────────────────────────────────────
def scrape_detail(url):
    soup = fetch(url)
    if not soup:
        return {}

    body = soup.find("main") or soup.body
    if not body:
        return {}

    full_text = body.get_text(" ", strip=True)

    # Description — first substantial paragraph
    desc = ""
    for p in body.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 80:
            desc = t[:400]
            break

    # Price — look for tarif/prix info
    prix_raw = ""
    for kw in ["inclus", "gratuit", "payant", r"\d+\s*\$"]:
        m = re.search(rf"({kw}[^\n]{{0,60}})", full_text, re.I)
        if m:
            prix_raw = m.group(1).strip()
            break

    return {
        "description": desc,
        "prix_raw":    prix_raw,
    }


# ── Main ──────────────────────────────────────────────────────────
def main():
    print("🔍 Scraping – Musée de la civilisation (Famille)")
    print(f"   Source : {LIST_URL}\n")

    # Paginated listing — collect all pages
    all_cards = []
    page = 1
    while True:
        if page == 1:
            url = LIST_URL
        else:
            url = f"{BASE_URL}/decouvrir/activites/page/{page}/?f=11"
        print(f"   → Page {page}")
        soup = fetch(url)
        if not soup:
            break
        cards = parse_listing(soup)
        if not cards:
            break
        all_cards.extend(cards)
        # Check if there's a next page
        next_link = soup.select_one("a.next, a[rel='next'], .pagination a:last-child")
        if not next_link:
            # Check for numeric pagination
            has_next = soup.find("a", string=str(page + 1))
            if not has_next:
                break
        page += 1
        time.sleep(0.5)

    # Deduplicate
    seen, unique = set(), []
    for c in all_cards:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)

    print(f"\n📋 {len(unique)} activités trouvées.")
    print(f"📅 Filtre : {DATE_MIN} → {DATE_MAX}\n")

    evenements = []
    skipped = 0

    for i, card in enumerate(unique):
        print(f"   [{i+1}/{len(unique)}] {card['titre']}")

        if not in_window(card["date_str"]):
            print(f"        ⏩ Hors fenêtre ({card['date_str']}) – ignoré.")
            skipped += 1
            continue

        detail = scrape_detail(card["url"])
        time.sleep(0.5)

        desc  = detail.get("description", "")
        prix  = normalize_price(detail.get("prix_raw", ""))

        evenements.append({
            "titre":       card["titre"],
            "lieu":        LIEU_FIXE,
            "quartier":    resoudre_quartier(LIEU_FIXE),
            "theme":       detect_theme(card.get("type_tag", ""), card["titre"]),
            "age":         detect_age(desc, card["titre"]),
            "semaine":     "",
            "date":        card["date_str"],
            "prix":        prix,
            "image":       card.get("image", ""),
            "description": desc,
            "URL":         card["url"],
        })

    print(f"\n✅ MCQ : {len(evenements)} événements retenus ({skipped} ignorés).")
    return evenements


if __name__ == "__main__":
    results = main()
    try:
        existing = json.load(open(OUTPUT_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []
    existing = [e for e in existing if "mcq.org" not in e.get("URL", "")]
    existing.extend(results)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"💾 {len(existing)} événements total dans {OUTPUT_FILE}.")
