"""
Scraper – Activités Familles MNBAQ
Collecte les événements familles sur https://www.mnbaq.org/programmation/familles
et produit un fichier evenements.json structuré.

Filtre automatique : mois courant + mois suivant (basé sur date d'exécution).

Usage : python scraper_mnbaq.py
"""

import json
import time
import re
import sys
from datetime import date, datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.mnbaq.org"
LIST_URL = f"{BASE_URL}/programmation/familles"
OUTPUT_FILE = "evenements.json"

# ─────────────────────────────────────────────
# Fenêtre de dates : mois courant + mois suivant
# ─────────────────────────────────────────────
_today = date.today()
_next_month = _today.month % 12 + 1
_next_year  = _today.year + (_today.month // 12)

DATE_MIN = date(_today.year, _today.month, 1)
DATE_MAX = date(
    _next_year,
    _next_month,
    [31,28+(_next_year%4==0 and (_next_year%100!=0 or _next_year%400==0)),
     31,30,31,30,31,31,30,31,30,31][_next_month - 1]
)

MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}

def parse_date_fr(text: str):
    """Parse 'DD mois YYYY' ou 'DD mois' (année courante/suivante)."""
    text = text.lower().strip()
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if m:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = MONTHS_FR.get(month_str)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})\s+(\w+)", text)
    if m:
        day, month_str = int(m.group(1)), m.group(2)
        month = MONTHS_FR.get(month_str)
        if month:
            for year in (_today.year, _today.year + 1):
                try:
                    return date(year, month, day)
                except ValueError:
                    pass
    return None


def event_in_window(dates_text: str) -> bool:
    """
    Retourne True si l'événement a au moins une date dans la fenêtre
    DATE_MIN..DATE_MAX. Gère les plages 'DD mois YYYY au DD mois YYYY'
    et les dates isolées. Si aucune date n'est parsée, garde l'événement.
    """
    dt = dates_text.lower()
    m = re.search(
        r"(\d{1,2}\s+\w+\s+\d{4})\s+au\s+(\d{1,2}\s+\w+\s+\d{4})", dt
    )
    if m:
        start = parse_date_fr(m.group(1))
        end   = parse_date_fr(m.group(2))
        if start and end:
            return start <= DATE_MAX and end >= DATE_MIN
    d = parse_date_fr(dt)
    if d:
        return DATE_MIN <= d <= DATE_MAX
    return True   # date non parsée → on garde par prudence


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9",
}

# ─────────────────────────────────────────────
# Mapping mots-clés → thème normalisé
# ─────────────────────────────────────────────
THEME_MAP = {
    "atelier":   "arts",
    "collage":   "arts",
    "dessin":    "arts",
    "peinture":  "arts",
    "sculpture": "arts",
    "cinéma":    "cinéma",
    "film":      "cinéma",
    "visite":    "visite guidée",
    "guidée":    "visite guidée",
    "musique":   "musique",
    "concert":   "musique",
    "conférence":"conférence",
    "mieux-être":"art et mieux-être",
    "événement": "événement spécial",
    "spécial":   "événement spécial",
    "exposition": "exposition",
}

def detect_theme(titre: str, type_activite: str) -> str:
    combined = (titre + " " + type_activite).lower()
    for keyword, theme in THEME_MAP.items():
        if keyword in combined:
            return theme
    return "arts"  # défaut


def detect_age(description: str, titre: str) -> str:
    text = (description + " " + titre).lower()
    m = re.search(r"(\d+)\s*(?:ans?|year)", text)
    if m:
        age = int(m.group(1))
        if age <= 5:
            return "0-5 ans"
        elif age <= 12:
            return f"{age} ans et +"
        else:
            return f"{age} ans et +"
    if "poussette" in text or "bébé" in text or "bambin" in text:
        return "0-3 ans"
    if "famille" in text or "enfant" in text:
        return "Tous"
    return "Tous"


def normalize_price(raw: str) -> str:
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


def fetch_page(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            print(f"  ⚠️  Erreur ({attempt+1}/{retries}) : {e}")
            time.sleep(2 ** attempt)
    return None


def scrape_event_detail(url: str) -> dict:
    """Récupère les infos détaillées d'un événement."""
    soup = fetch_page(url)
    if not soup:
        return {}

    main = soup.find("main")
    if not main:
        return {}

    # ── Image ──
    # Premier <img> cloudfront dans le main, avant la section "Autres activités"
    image = ""
    autres_h2 = None
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

    # ── Description ──
    # Paragraphes sous le <h2> "À propos", sans inclure le titre lui-même
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
    # Fallback : premier <p> suffisamment long
    if not description:
        for p in main.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 40:
                description = t
                break

    # ── Section Informations (dates, prix, lieu) ──
    info_text = ""
    for h2 in main.find_all("h2"):
        if "information" in h2.get_text(strip=True).lower():
            parts = []
            for sib in h2.find_next_siblings():
                if sib.name == "h2":
                    break
                t = sib.get_text(" ", strip=True)
                if t:
                    parts.append(t)
            info_text = " \n".join(parts)
            break

    # ── Prix ──
    prix_raw = ""
    for line in info_text.splitlines():
        line = line.strip()
        if any(k in line.lower() for k in ["$", "gratuit", "inclus", "membre"]):
            prix_raw = line
            break

    # ── Dates ──
    dates_text = ""
    m = re.search(r"\d{1,2}\s+\w+\s+\d{4}[^\n]*(?:\s+au\s+\d{1,2}\s+\w+\s+\d{4})?", info_text)
    if m:
        dates_text = m.group(0).strip()

    # ── Lieu ──
    # Liens vers le plan du pavillon dans la section Informations
    lieu = "MNBAQ"
    lieu_names = []
    for h2 in main.find_all("h2"):
        if "information" in h2.get_text(strip=True).lower():
            for a in h2.find_next_siblings():
                if a.name == "h2":
                    break
                for link in (a.find_all("a") if hasattr(a, "find_all") else []):
                    href = link.get("href", "")
                    txt = link.get_text(strip=True)
                    if ("pavillon" in href or "plan" in href) and txt:
                        if "pratiques" not in txt.lower():
                            lieu_names.append(txt)
            break
    if lieu_names:
        lieu = "MNBAQ – " + lieu_names[0]

    return {
        "description": description[:400],
        "image": image,
        "lieu": lieu,
        "prix_raw": prix_raw,
        "dates_text": dates_text,
    }


def parse_listing_page(soup: BeautifulSoup) -> list:
    """Extrait les cartes d'événements d'une page de listing."""
    events = []

    # Chaque événement est dans un article ou une li avec un lien "En savoir plus"
    links = soup.select("a[href*='/programmation/']")
    seen_urls = set()

    for link in links:
        href = link.get("href", "")
        text = link.get_text(strip=True)

        # Filtre : liens "En savoir plus sur ..."
        if not text.startswith("En savoir plus sur"):
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Remonte pour trouver le bloc parent de la carte
        card = link.find_parent("li") or link.find_parent("article") or link.find_parent("div")

        titre = text.replace("En savoir plus sur", "").strip()

        # Type d'activité (Atelier, Visite guidée, etc.)
        type_tag = card.find(["h2", "h3", "h4", "span", "p"]) if card else None
        type_activite = type_tag.get_text(strip=True) if type_tag else ""

        # Prix depuis la carte
        prix_card = ""
        if card:
            for t in card.find_all(string=True):
                s = t.strip()
                if any(k in s.lower() for k in ["$", "gratuit", "inclus", "membre"]):
                    prix_card = s
                    break

        events.append({
            "titre": titre,
            "url": full_url,
            "type_activite": type_activite,
            "prix_card": prix_card,
        })

    return events


def get_total_pages(soup: BeautifulSoup) -> int:
    # Cherche la dernière page dans la pagination
    pagination = soup.select("a[href*='page=']")
    max_page = 1
    for a in pagination:
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def build_semaine(index: int) -> str:
    """Attribue un numéro de semaine fictif basé sur l'ordre de scraping (1-based)."""
    return str((index // 7) + 1)


def main():
    print("🔍 Démarrage du scraping MNBAQ – Activités Familles")
    print(f"   Source : {LIST_URL}\n")

    # ── Étape 1 : récupérer toutes les pages de listing ──
    first_page = fetch_page(LIST_URL)
    if not first_page:
        print("❌ Impossible d'accéder à la page principale.")
        sys.exit(1)

    total_pages = get_total_pages(first_page)
    print(f"📄 {total_pages} page(s) de résultats détectée(s).")

    all_cards = []
    all_cards.extend(parse_listing_page(first_page))

    for page_num in range(2, total_pages + 1):
        url = f"{LIST_URL}?page={page_num}"
        print(f"   → Page {page_num}/{total_pages} : {url}")
        soup = fetch_page(url)
        if soup:
            all_cards.extend(parse_listing_page(soup))
        time.sleep(0.8)  # politesse

    # Dédoublonnage par URL
    seen = set()
    unique_cards = []
    for c in all_cards:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique_cards.append(c)

    print(f"\n✅ {len(unique_cards)} événement(s) unique(s) trouvé(s) dans le listing.")
    print(f"📅 Filtre : {DATE_MIN.strftime('%d %B %Y')} → {DATE_MAX.strftime('%d %B %Y')}\n")

    # ── Étape 2 : récupérer les détails + filtrer par date ──
    evenements = []
    skipped = 0
    for i, card in enumerate(unique_cards):
        print(f"   [{i+1}/{len(unique_cards)}] {card['titre']}")
        detail = scrape_event_detail(card["url"])
        time.sleep(0.6)

        # ── Filtre de date ──
        dates_text = detail.get("dates_text", "")
        if dates_text and not event_in_window(dates_text):
            print(f"        ⏩ Hors fenêtre ({dates_text[:60]}) – ignoré.")
            skipped += 1
            continue

        prix_raw = detail.get("prix_raw") or card.get("prix_card", "")
        prix = normalize_price(prix_raw)

        lieu = detail.get("lieu") or "MNBAQ"
        description = detail.get("description", "")
        if not description:
            description = f"Activité au Musée national des beaux-arts du Québec : {card['titre']}."

        image = detail.get("image", "")
        if not image:
            image = "https://via.placeholder.com/500x300?text=MNBAQ"

        age = detect_age(description, card["titre"])
        theme = detect_theme(card["titre"], card.get("type_activite", ""))

        evenement = {
            "titre": card["titre"],
            "lieu": lieu,
            "theme": theme,
            "age": age,
            "semaine": build_semaine(len(evenements)),
            "prix": prix,
            "image": image,
            "description": description,
            "URL": card["url"],
        }
        evenements.append(evenement)

    # ── Étape 3 : écriture du JSON ──
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(evenements, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 Terminé ! {len(evenements)} événement(s) exporté(s) dans « {OUTPUT_FILE} » ({skipped} hors fenêtre ignoré(s)).")
    return OUTPUT_FILE


if __name__ == "__main__":
    main()
