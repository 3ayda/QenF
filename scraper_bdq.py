"""
scraper_bdq.py – Activités jeunesse / familles / adolescents
               Bibliothèque de Québec  (bibliothequedequebec.qc.ca)

Stratégie :
  1. Scrape la page listing /activites  (HTML statique, 152+ activités)
  2. Pour chaque activité, scrape la page détail pour lire le champ "Public"
  3. Garde : Enfants (0-5), Enfants (6-12), Adolescents, Tous,
             Familles, réservée aux familles
  4. Exclut : Adultes, Aînés, Nouveaux arrivants (seuls)

Usage : python scraper_bdq.py   → ajoute au fichier evenements.json
"""

import json, re, sys, time
from datetime import date
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from quartier import resoudre_quartier

# ── Constantes ────────────────────────────────────────────────────
BASE_URL    = "https://www.bibliothequedequebec.qc.ca"
LIST_URL    = f"{BASE_URL}/activites"
OUTPUT_FILE = "evenements.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9",
}

# Publics acceptés (sous-chaîne, insensible à la casse)
PUBLICS_OK = [
    "enfants", "adolescent", "famille", "familles", "tous", "tout public",
]
# Publics exclusifs adultes à rejeter quand c'est le SEUL public listé
PUBLICS_ADULTES = ["adultes", "aînés", "aines", "nouveaux arrivants"]

MONTHS_FR = {
    "janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,
}

_today    = date.today()
_nm       = _today.month % 12 + 1
_ny       = _today.year + (_today.month // 12)
DATE_MIN  = date(_today.year, _today.month, 1)
DATE_MAX  = date(_ny, _nm,
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
    """True si la date/plage chevauche DATE_MIN–DATE_MAX."""
    if not date_str:
        return True  # date inconnue → on garde
    D = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"
    m = re.search(rf"({D})\s+au\s+({D})", date_str, re.I)
    if m:
        s = parse_date_fr(m.group(1))
        e = parse_date_fr(m.group(2))
        if s and e:
            return s <= DATE_MAX and e >= DATE_MIN
    d = parse_date_fr(date_str)
    if d:
        return DATE_MIN <= d <= DATE_MAX
    return True


def public_ok(publics_text):
    """
    Retourne True si le texte du champ Public contient au moins un public cible
    acceptable ET n'est pas exclusivement adulte/aîné.
    """
    t = publics_text.lower()
    if not t:
        return True  # pas de champ Public → on garde
    has_ok    = any(p in t for p in PUBLICS_OK)
    only_adult = all(p in t for p in PUBLICS_ADULTES if p in t) and not has_ok
    return has_ok and not only_adult


def detect_age_bdq(public_text, description):
    """Infère le champ age à partir du texte Public de la BDQ."""
    t = public_text.lower() + " " + description.lower()
    if "0-5" in t or "0 à 5" in t or "bébé" in t or "bambin" in t:
        return "0-5 ans"
    if "6-12" in t or "6 à 12" in t:
        return "6-12 ans"
    if "adolescent" in t:
        return "Adolescents"
    if "enfant" in t:
        return "Enfants"
    return "Tous"


def detect_theme_bdq(categorie, titre):
    combined = (categorie + " " + titre).lower()
    if "atelier" in combined:                         return "arts"
    if "jeunesse" in combined or "enfant" in combined:return "arts"
    if "cinéma" in combined or "cinema" in combined:  return "cinéma"
    if "exposition" in combined:                      return "exposition"
    if "spectacle" in combined:                       return "événement spécial"
    if "technologie" in combined or "numérique" in combined: return "arts"
    if "littér" in combined or "conte" in combined:   return "arts"
    return "événement spécial"


def normalize_price(raw):
    if not raw:
        return "Voir le site"
    low = raw.lower().strip()
    if "gratuit" in low:
        return "Gratuit"
    return raw.strip()


# ── Listing ───────────────────────────────────────────────────────
def parse_listing(soup):
    """
    Extrait les cartes d'activités de la page listing de la BDQ.
    Retourne une liste de dicts avec url, titre, image, description_courte.
    """
    events = []
    seen   = set()

    for a in soup.select("a[href*='/activites/']"):
        href = a.get("href", "")
        # Liens de détail : /activites/{id}/{slug}
        if not re.search(r"/activites/\d+/", href):
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        seen.add(full_url)

        # Titre = texte du h3 dans la carte parente, ou texte du lien
        card  = a.find_parent(["li", "article", "div"])
        h3    = card.find("h3") if card else None
        titre = h3.get_text(strip=True) if h3 else a.get_text(strip=True)
        if not titre:
            continue

        # Image
        img     = card.find("img") if card else None
        image   = img.get("src", "") if img else ""

        # Description courte (paragraphe dans la carte)
        p       = card.find("p") if card else None
        desc_c  = p.get_text(" ", strip=True) if p else ""

        events.append({
            "titre":  titre,
            "url":    full_url,
            "image":  image,
            "desc_courte": desc_c,
        })

    return events


# ── Détail ────────────────────────────────────────────────────────
def scrape_detail(url):
    """
    Scrape une page de détail d'activité BDQ.
    La page contient un tableau avec colonnes Date | Heure | Lieu | Places | Détails
    C'est là qu'on trouve la branche de bibliothèque et la date exacte.
    """
    soup = fetch(url)
    if not soup:
        return {}

    body = soup.find("main") or soup.body
    if not body:
        return {}

    full_text = body.get_text(" ", strip=True)

    # ── Public ── (format: <strong>Public :</strong>\nTous)
    public_text = ""
    for strong in body.find_all("strong"):
        if "public" in strong.get_text(strip=True).lower():
            # Value is the next text node or sibling
            nxt = strong.next_sibling
            if nxt:
                public_text = str(nxt).strip().lstrip(":").strip()
            if not public_text:
                parent = strong.parent
                txt = parent.get_text(" ", strip=True)
                m = re.search(r"Public\s*[:\-]?\s*(.+)", txt, re.I)
                if m:
                    public_text = m.group(1).strip()
            break
    if not public_text:
        if re.search(r"r[eé]serv[eé]e?\s+aux\s+familles", full_text, re.I):
            public_text = "Familles"

    # ── Table : Date + Lieu ──
    # The schedule table has columns: Date | Heure | Lieu | Places | Détails
    lieu = "Bibliothèque de Québec"
    date_str = ""

    for table in body.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "lieu" not in headers and "date" not in headers:
            continue
        # Find column indices
        date_col = next((i for i, h in enumerate(headers) if "date" in h), None)
        lieu_col = next((i for i, h in enumerate(headers) if "lieu" in h), None)
        prix_col = next((i for i, h in enumerate(headers) if "place" in h or "entrée" in h or "prix" in h), None)

        for row in table.find_all("tr")[1:]:  # skip header row
            cells = row.find_all(["td","th"])
            if date_col is not None and date_col < len(cells):
                raw_date = cells[date_col].get_text(" ", strip=True)
                # Handles formats:
                # "Du 17 février au 29 mars 2026"  (year only at end)
                # "17 février 2026 au 29 mars 2026"
                # "17 février 2026"
                DY  = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}"  # with year
                DNY = r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+"            # without year
                # Try range with year on both sides first
                m = re.search(rf"({DY})\s+au\s+({DY})", raw_date, re.I)
                if m:
                    date_str = f"{m.group(1)} au {m.group(2)}"
                else:
                    # Try "Du X mois au Y mois YYYY" — year only on end date
                    m2 = re.search(
                        rf"(?:du\s+)?({DNY})\s+au\s+({DY})",
                        raw_date, re.I
                    )
                    if m2:
                        # Extract year from end date and infer for start
                        year = re.search(r"\d{4}", m2.group(2)).group(0)
                        date_str = f"{m2.group(1)} {year} au {m2.group(2)}"
                    else:
                        m3 = re.search(DY, raw_date, re.I)
                        if m3:
                            date_str = m3.group(0)
            if lieu_col is not None and lieu_col < len(cells):
                t = cells[lieu_col].get_text(strip=True)
                if t and t.lower() not in ("lieu", "-", ""):
                    lieu = t
            break  # only first data row needed

    # ── Prix (from table "Places disponibles" cell or text) ──
    prix_raw = ""
    if "entrée libre" in full_text.lower() or "accès libre" in full_text.lower():
        prix_raw = "Gratuit"
    else:
        m = re.search(r"(\d[\d\s,\.]*\$[^\n]{0,40}|gratuit)", full_text, re.I)
        if m:
            prix_raw = m.group(0).strip()

    # ── Description ── (first substantial <p>, skip breadcrumb)
    desc = ""
    for p in body.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 80 and "accueil" not in t.lower()[:20]:
            desc = t[:400]
            break

    # ── Catégorie ──
    categorie = ""
    for a in body.select("a"):
        href = a.get("href","")
        if "javascript" in href and "Categorie" in href:
            categorie = a.get_text(strip=True)
            break

    return {
        "public":      public_text,
        "date_str":    date_str,
        "lieu":        lieu,
        "prix_raw":    prix_raw,
        "description": desc,
        "categorie":   categorie,
    }


# ── Main ──────────────────────────────────────────────────────────
def main():
    print("🔍 Scraping – Bibliothèque de Québec")
    print(f"   Source : {LIST_URL}\n")

    soup = fetch(LIST_URL)
    if not soup:
        print("❌ Impossible d'accéder à la page listing.")
        return []

    cards = parse_listing(soup)
    print(f"📋 {len(cards)} activités trouvées sur la page listing.")
    print(f"📅 Filtre : {DATE_MIN} → {DATE_MAX}\n")

    evenements = []
    skipped = 0

    for i, card in enumerate(cards):
        print(f"   [{i+1}/{len(cards)}] {card['titre']}")
        detail = scrape_detail(card["url"])
        time.sleep(0.5)

        if not detail:
            skipped += 1
            continue

        # Filtre Public
        if not public_ok(detail.get("public", "")):
            print(f"        ⏩ Public adulte/aîné – ignoré ({detail.get('public','')})")
            skipped += 1
            continue

        # Filtre date
        date_str = detail.get("date_str", "")
        if not in_window(date_str):
            print(f"        ⏩ Hors fenêtre – ignoré.")
            skipped += 1
            continue

        lieu = detail.get("lieu") or "Bibliothèque de Québec"
        desc = detail.get("description") or card.get("desc_courte", "")
        prix = normalize_price(detail.get("prix_raw", ""))

        evenements.append({
            "titre":       card["titre"],
            "lieu":        lieu,
            "quartier":    resoudre_quartier(lieu),
            "theme":       detect_theme_bdq(detail.get("categorie",""), card["titre"]),
            "age":         detect_age_bdq(detail.get("public",""), desc),
            "semaine":     "",
            "date":        date_str,
            "prix":        prix,
            "image":       card.get("image", ""),
            "description": desc,
            "URL":         card["url"],
        })

    print(f"\n✅ BDQ : {len(evenements)} événements retenus ({skipped} ignorés).")
    return evenements


if __name__ == "__main__":
    results = main()
    # Merge with existing evenements.json if present
    try:
        existing = json.load(open(OUTPUT_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    # Remove old BDQ entries then add fresh ones
    existing = [e for e in existing if "bibliothequedequebec" not in e.get("URL","")]
    existing.extend(results)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"💾 {len(existing)} événements total dans {OUTPUT_FILE}.")
