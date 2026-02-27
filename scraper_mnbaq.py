"""
Scraper – Activités Familles MNBAQ
Collecte les événements familles sur https://www.mnbaq.org/programmation/familles
et produit un fichier evenements.json structuré.

Filtre automatique : mois courant + mois suivant (basé sur date d'exécution).
Les images CloudFront (signées/expirables) sont converties en URLs stables via wsrv.nl.

Usage : python scraper_mnbaq.py
"""

import json
import time
import re
import sys
from datetime import date
from urllib.parse import urljoin, quote
import requests
from bs4 import BeautifulSoup
from quartier import resoudre_quartier

# ─────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────

BASE_URL    = "https://www.mnbaq.org"
LIST_URL    = f"{BASE_URL}/programmation/familles"
OUTPUT_FILE = "evenements.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9",
}

THEME_MAP = {
    "atelier":    "arts",
    "collage":    "arts",
    "dessin":     "arts",
    "peinture":   "arts",
    "sculpture":  "arts",
    "cinema":     "cinéma",
    "cinéma":     "cinéma",
    "film":       "cinéma",
    "visite":     "visite guidée",
    "guidée":     "visite guidée",
    "musique":    "musique",
    "concert":    "musique",
    "mieux-être": "art et mieux-être",
    "événement":  "événement spécial",
    "spécial":    "événement spécial",
    "exposition": "exposition",
}

MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}

# ─────────────────────────────────────────────────────────────────
# FENÊTRE DE DATES
# ─────────────────────────────────────────────────────────────────

_today      = date.today()
_next_month = _today.month % 12 + 1
_next_year  = _today.year + (_today.month // 12)

DATE_MIN = date(_today.year, _today.month, 1)
DATE_MAX = date(
    _next_year,
    _next_month,
    [31, 28 + (_next_year % 4 == 0 and (_next_year % 100 != 0 or _next_year % 400 == 0)),
     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][_next_month - 1]
)

# ─────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────

def parse_date_fr(text):
    text = text.lower().strip()
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if m:
        month = MONTHS_FR.get(m.group(2))
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass
    return None


def event_in_window(dates_text):
    dt = dates_text.lower()
    m = re.search(r"(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})\s+au\s+(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})", dt)
    if m:
        start = parse_date_fr(m.group(1))
        end   = parse_date_fr(m.group(2))
        if start and end:
            return start <= DATE_MAX and end >= DATE_MIN
    d = parse_date_fr(dt)
    if d:
        return DATE_MIN <= d <= DATE_MAX
    return True


def detect_theme(titre, type_activite):
    combined = (titre + " " + type_activite).lower()
    for keyword, theme in THEME_MAP.items():
        if keyword in combined:
            return theme
    return "arts"


def detect_age(description, titre):
    text = (description + " " + titre).lower()
    m = re.search(r"(\d+)\s*(?:ans?|year)", text)
    if m:
        age = int(m.group(1))
        return "0-5 ans" if age <= 5 else f"{age} ans et +"
    if any(k in text for k in ["poussette", "bébé", "bambin"]):
        return "0-3 ans"
    return "Tous"


def normalize_price(raw):
    if not raw:
        return "Voir le site"
    raw = raw.strip()
    low = raw.lower()
    if "gratuit" in low and "inclus" in low:
        return "Gratuit / Inclus"
    if "gratuit" in low:
        return "Gratuit"
    if "inclus" in low:
        return "Inclus avec le billet d'entrée"
    return raw


def proxy_image(url):
    if not url:
        return url
    return f"https://wsrv.nl/?url={quote(url, safe='')}&w=600&output=webp"


def format_date(dates_text):
    if not dates_text:
        return ""
    m = re.search(
        r"(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})\s+au\s+(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})",
        dates_text, re.IGNORECASE
    )
    if m:
        return f"{m.group(1)} au {m.group(2)}"
    m = re.search(r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}", dates_text)
    if m:
        return m.group(0)
    return ""


def build_semaine(index):
    return str((index // 7) + 1)


# ─────────────────────────────────────────────────────────────────
# RÉSEAU
# ─────────────────────────────────────────────────────────────────

def fetch_page(url, retries=3):
    """Télécharge une page et retourne un BeautifulSoup, ou None."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            print(f"  ⚠️  Erreur ({attempt+1}/{retries}) : {e}")
            time.sleep(2 ** attempt)
    return None


# ─────────────────────────────────────────────────────────────────
# SCRAPING
# ─────────────────────────────────────────────────────────────────

def scrape_event_detail(url):
    soup = fetch_page(url)
    if not soup:
        return {}
    main = soup.find("main") or soup.find("div", {"id": "main"}) or soup.find("article") or soup.body
    if not main:
        return {}

    # Image
    image, autres_h2 = "", None
    for h2 in main.find_all("h2"):
        if "autres activit" in h2.get_text(strip=True).lower():
            autres_h2 = h2
            break
    for img in main.find_all("img"):
        if autres_h2 and autres_h2 in img.find_all_previous("h2"):
            break
        src = img.get("src", "")
        if src and "cloudfront" in src and "newsletter" not in src:
            image = src
            break

    # Description
    description = ""
    for h2 in main.find_all("h2"):
        if "à propos" in h2.get_text(strip=True).lower():
            parts = []
            for sib in h2.find_next_siblings():
                if sib.name == "h2":
                    break
                if sib.name == "p":
                    parts.append(sib.get_text(" ", strip=True))
            description = " ".join(parts)
            break
    if not description:
        for p in main.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 40:
                description = t
                break

    # Section Informations — search ALL heading levels (h1-h5).
    # The MNBAQ page uses <h3> for "Informations", not <h2>.
    # Must still exclude "Informations sur l'image" (appears as <h2> earlier).
    info_text = ""
    INFO_EXACT = re.compile(r"^informations?\s*$", re.IGNORECASE)
    HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5"]
    for tag in main.find_all(HEADING_TAGS):
        if INFO_EXACT.match(tag.get_text(strip=True)):
            parts = []
            for sib in tag.find_next_siblings():
                if sib.name in HEADING_TAGS:
                    break
                t = sib.get_text(" ", strip=True)
                if t:
                    parts.append(t)
            info_text = " \n".join(parts)
            break

    # Prix
    prix_raw = ""
    for line in info_text.splitlines():
        line = line.strip()
        if any(k in line.lower() for k in ["$", "gratuit", "inclus", "membre"]):
            prix_raw = line
            break

    # Dates — only from the Informations block (never fall back to full page).
    # Handles three formats:
    #   "15 février 2026 au 29 mars 2026"               → range
    #   "14 janvier 2026, 27 février 2026 et 10 avril 2026" → pick first & last
    #   "27 février 2026"                                → single date
    dates_text = ""
    DATE_RE = re.compile(
        r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}",
        re.IGNORECASE
    )
    DATE_RANGE_RE = re.compile(
        r"(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})"
        r"\s+au\s+"
        r"(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})",
        re.IGNORECASE
    )
    if info_text:
        # 1. Try explicit "X au Y" range
        m = DATE_RANGE_RE.search(info_text)
        if m:
            dates_text = f"{m.group(1)} au {m.group(2)}"
        else:
            # 2. Collect all individual dates in order
            all_dates = DATE_RE.findall(info_text)
            if len(all_dates) >= 2:
                # Multiple dates (e.g. "14 janvier 2026, 27 février 2026 et 10 avril 2026")
                # → represent as first au last
                dates_text = f"{all_dates[0]} au {all_dates[-1]}"
            elif len(all_dates) == 1:
                dates_text = all_dates[0]

    # Lieu — same exact heading match, all heading levels
    lieu = "MNBAQ"
    for tag in main.find_all(HEADING_TAGS):
        if INFO_EXACT.match(tag.get_text(strip=True)):
            for sib in tag.find_next_siblings():
                if sib.name in HEADING_TAGS:
                    break
                for link in (sib.find_all("a") if hasattr(sib, "find_all") else []):
                    href = link.get("href", "")
                    txt  = link.get_text(strip=True)
                    if ("pavillon" in href or "plan" in href) and txt:
                        if "pratiques" not in txt.lower():
                            lieu = "MNBAQ – " + txt
                            break
            break

    return {
        "description": description[:400],
        "image":       image,
        "lieu":        lieu,
        "prix_raw":    prix_raw,
        "dates_text":  dates_text,
    }


def parse_listing_page(soup):
    events, seen_urls = [], set()
    for link in soup.select("a[href*='/programmation/']"):
        text = link.get_text(strip=True)
        if not text.startswith("En savoir plus sur"):
            continue
        full_url = urljoin(BASE_URL, link.get("href", ""))
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Only keep events from known family-compatible URL paths
        # This blocks adult cinema, conférences, membres-only events etc.
        FAMILY_PATHS = [
            "/programmation/familles",
            "/programmation/ateliers-et-cours",
            "/programmation/evenements-speciaux",
            "/programmation/visites-guidees",
            "/programmation/musique-et-concerts",
            "/programmation/expositions",
            "/programmation/arts-et-mieux-etre",
        ]
        if not any(p in full_url for p in FAMILY_PATHS):
            continue

        card = (link.find_parent("li")
                or link.find_parent("article")
                or link.find_parent("div"))

        titre         = text.replace("En savoir plus sur", "").strip()
        type_tag      = card.find(["h2","h3","h4","span","p"]) if card else None
        type_activite = type_tag.get_text(strip=True) if type_tag else ""

        prix_card = ""
        if card:
            for t in card.find_all(string=True):
                s = t.strip()
                if any(k in s.lower() for k in ["$", "gratuit", "inclus", "membre"]):
                    prix_card = s
                    break

        image_card = ""
        if card:
            img = card.find("img", src=lambda s: s and "cloudfront" in s)
            if img:
                image_card = img["src"]

        events.append({
            "titre":         titre,
            "url":           full_url,
            "type_activite": type_activite,
            "prix_card":     prix_card,
            "image_card":    image_card,
        })
    return events


def get_total_pages(soup):
    max_page = 1
    for a in soup.select("a[href*='page=']"):
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    print("🔍 Démarrage du scraping MNBAQ – Activités Familles")
    print(f"   Source : {LIST_URL}\n")

    first_page = fetch_page(LIST_URL)
    if not first_page:
        print("❌ Impossible d'accéder à la page principale.")
        sys.exit(1)

    total_pages = get_total_pages(first_page)
    print(f"📄 {total_pages} page(s) détectée(s).")

    all_cards = list(parse_listing_page(first_page))
    for page_num in range(2, total_pages + 1):
        print(f"   → Page {page_num}/{total_pages}")
        soup = fetch_page(f"{LIST_URL}?page={page_num}")
        if soup:
            all_cards.extend(parse_listing_page(soup))
        time.sleep(0.8)

    seen, unique_cards = set(), []
    for c in all_cards:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique_cards.append(c)

    print(f"\n✅ {len(unique_cards)} événement(s) unique(s).")
    print(f"📅 Filtre : {DATE_MIN.strftime('%d %B %Y')} → {DATE_MAX.strftime('%d %B %Y')}\n")

    evenements, skipped = [], 0
    for i, card in enumerate(unique_cards):
        print(f"   [{i+1}/{len(unique_cards)}] {card['titre']}")
        detail     = scrape_event_detail(card["url"])
        time.sleep(0.6)

        if detail.get("skip"):
            skipped += 1
            continue

        dates_text = detail.get("dates_text", "")
        if dates_text and not event_in_window(dates_text):
            print("        ⏩ Hors fenêtre – ignoré.")
            skipped += 1
            continue

        prix = normalize_price(detail.get("prix_raw") or card.get("prix_card", ""))
        lieu = detail.get("lieu") or "MNBAQ"
        desc = detail.get("description", "") or \
               f"Activité au Musée national des beaux-arts du Québec : {card['titre']}."

        raw_image = card.get("image_card") or detail.get("image", "")
        image = proxy_image(raw_image) if raw_image else \
                "https://wsrv.nl/?url=https%3A%2F%2Fwww.mnbaq.org%2Fresources%2Fassets%2Fimages%2Fog-image.jpg&w=600&output=webp"

        evenements.append({
            "titre":       card["titre"],
            "lieu":        lieu,
            "quartier":    resoudre_quartier(lieu),
            "theme":       detect_theme(card["titre"], card.get("type_activite", "")),
            "age":         detect_age(desc, card["titre"]),
            "semaine":     build_semaine(len(evenements)),
            "date":        format_date(dates_text),
            "prix":        prix,
            "image":       image,
            "description": desc,
            "URL":         card["url"],
        })

    print(f"\n🎉 {len(evenements)} événement(s) MNBAQ ({skipped} hors fenêtre ignoré(s)).")
    return evenements


if __name__ == "__main__":
    import json as _json
    results = main()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        _json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 {len(results)} événements dans {OUTPUT_FILE}.")
