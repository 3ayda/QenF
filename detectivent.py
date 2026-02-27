"""
Detectivent - Agent de verification des evenements
====================================================
Charge evenements.json, visite chaque URL, compare les champs
affiches sur la carte (titre, date, prix, lieu, description) avec
ce qui est reellement sur la page source, puis ecrit error_events.json
listant toutes les divergences trouvees.

Usage:
    python detectivent.py                    # verifie evenements.json
    python detectivent.py --input mon.json   # fichier alternatif
    python detectivent.py --limit 10         # teste seulement les 10 premiers
    python detectivent.py --url https://...  # teste un seul evenement
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────

INPUT_FILE  = "evenements.json"
OUTPUT_FILE = "error_events.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-CA,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Similarity threshold: below this → flag as mismatch
TITLE_SIM_THRESHOLD = 0.72   # titles can be truncated/reformatted
TEXT_SIM_THRESHOLD  = 0.50   # descriptions are often summarised

MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}

# ─────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────

def norm(s: str) -> str:
    """Lowercase, collapse whitespace, remove punctuation noise."""
    s = (s or "").lower().strip()
    s = re.sub(r"['\u2018\u2019\u201c\u201d]", "'", s)   # normalise quotes
    s = re.sub(r"\s+", " ", s)
    return s


def similarity(a: str, b: str) -> float:
    """Sequence-matcher similarity ratio 0.0–1.0."""
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def contains(needle: str, haystack: str) -> bool:
    """True if needle (normalised) is a substring of haystack (normalised)."""
    return norm(needle) in norm(haystack)


def parse_dates_in_text(text: str):
    """Return all (day, month_num, year) tuples found in text."""
    found = []
    for m in re.finditer(
        r"(\d{1,2})\s+([A-Za-z\u00C0-\u024F]+)\s+(\d{4})", text, re.I
    ):
        month = MONTHS_FR.get(m.group(2).lower())
        if month:
            try:
                found.append(date(int(m.group(3)), month, int(m.group(1))))
            except ValueError:
                pass
    return found


def dates_overlap(card_date_str: str, page_dates: list) -> bool:
    """
    True if at least one date from page_dates falls within (or matches)
    the card's date range/single date.
    """
    if not card_date_str or not page_dates:
        return True   # can't verify → not flagged

    # Parse card date
    card_dates = parse_dates_in_text(card_date_str)
    if not card_dates:
        return True

    # Build card range [start, end]
    card_start = min(card_dates)
    card_end   = max(card_dates)

    for pd in page_dates:
        if card_start <= pd <= card_end:
            return True
    return False


def extract_amounts(text: str) -> list:
    """Extract all dollar amounts as floats from a string."""
    amounts = []
    for m in re.finditer(r"\$?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*\$?", text):
        try:
            v = float(m.group(1).replace(",", "."))
            if 1 <= v <= 999:
                amounts.append(v)
        except ValueError:
            pass
    return amounts


def prices_compatible(card_prix: str, page_text: str) -> bool:
    """
    True if the card price is compatible with what the page says.
    Gratuit must appear on page; dollar amounts must be roughly present.
    """
    if not card_prix or card_prix.lower() in ("voir le site", ""):
        return True

    cp = norm(card_prix)
    pt = norm(page_text)

    if "gratuit" in cp:
        return "gratuit" in pt

    if "inclus" in cp:
        return "inclus" in pt or "gratuit" in pt

    card_amounts = extract_amounts(card_prix)
    if not card_amounts:
        return True  # can't verify

    page_amounts = extract_amounts(page_text)
    if not page_amounts:
        return False   # card has price, page has none

    # Each card amount should appear somewhere on the page (within 10% tolerance)
    for ca in card_amounts:
        if not any(abs(pa - ca) / ca < 0.10 for pa in page_amounts):
            return False
    return True


# ─────────────────────────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code in (404, 410):
                return None   # dead link — not worth retrying
            time.sleep(2 ** attempt)
        except requests.RequestException:
            time.sleep(2 ** attempt)
    return None


# ─────────────────────────────────────────────────────────────────
# PAGE EXTRACTION  (source-agnostic)
# ─────────────────────────────────────────────────────────────────

def extract_page_data(soup: BeautifulSoup, url: str) -> dict:
    """
    Extract the key fields from a source event page.
    Works for MNBAQ, BDQ, MCQ, Moulin des Jésuites, Gestev, etc.
    Returns a dict with keys: titre, date_str, prix_raw, lieu, description, full_text.
    """
    body = soup.find("main") or soup.find("article") or soup.body
    if not body:
        return {}

    full_text = body.get_text(" ", strip=True)

    # ── Title ──
    titre = ""
    # og:title is the most reliable
    og = soup.find("meta", property="og:title")
    if og:
        titre = og.get("content", "").strip()
    if not titre:
        h1 = body.find("h1")
        if h1:
            titre = h1.get_text(strip=True)

    # ── Description ──
    desc = ""
    og_desc = soup.find("meta", property="og:description") or \
              soup.find("meta", attrs={"name": "description"})
    if og_desc:
        v = og_desc.get("content", "").strip()
        if len(v) > 30:
            desc = v

    if not desc:
        for p in body.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 60 and not re.search(
                r"cookie|©|newsletter|abonnez|javascript|droits réservés", t, re.I
            ):
                desc = t[:500]
                break

    # ── Dates ──
    # Try JSON-LD first (most structured)
    date_str = ""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                for key in ("startDate", "endDate", "datePublished"):
                    v = item.get(key, "")
                    if v:
                        date_str = v
                        break
        except Exception:
            pass
        if date_str:
            break

    # Fallback: regex on full text — restrict to sections before "Autres activités"
    if not date_str:
        # Cut text at "Autres activités" to avoid cross-contamination
        cut_idx = full_text.lower().find("autres activit")
        search_text = full_text[:cut_idx] if cut_idx > 0 else full_text

        DATE_RANGE = re.compile(
            r"(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})"
            r"\s+au\s+"
            r"(\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4})",
            re.I
        )
        DATE_LIST = re.compile(
            r"\d{1,2}\s+[A-Za-z\u00C0-\u024F]+\s+\d{4}", re.I
        )
        m = DATE_RANGE.search(search_text)
        if m:
            date_str = f"{m.group(1)} au {m.group(2)}"
        else:
            all_d = DATE_LIST.findall(search_text)
            if len(all_d) >= 2:
                date_str = f"{all_d[0]} au {all_d[-1]}"
            elif len(all_d) == 1:
                date_str = all_d[0]

    # ── Price ──
    prix_raw = ""
    for pattern in [
        r"(?:prix|tarif|coût|admission|billet)[^\n:]*:?\s*([^\n]{3,60})",
        r"(gratuit\b[^\n]{0,40})",
        r"(membre\s*:[^\n]{3,50})",
        r"(inclus\s+avec[^\n]{3,50})",
        r"(\d+[\s,\.]\d*\s*\$[^\n]{0,40})",
        r"(\$\s*\d+[^\n]{0,40})",
    ]:
        m = re.search(pattern, full_text, re.I)
        if m:
            prix_raw = m.group(1).strip()
            break

    # ── Lieu ──
    lieu = ""
    venue_patterns = [
        r"(Centre\s+Vidéotron|Centre\s+Videotron)",
        r"((?:Centre|Salle|Colisée|Amphithéâtre|Aréna|Théâtre|Pavillon|"
        r"Bibliothèque|Moulin|Maison)[^,\n\.\<]{3,60})",
        r"(\d{1,4}\s+[A-Za-z\u00C0-\u024F][^,\n]{5,50},\s*Québec)",
    ]
    for vp in venue_patterns:
        m = re.search(vp, full_text, re.I)
        if m:
            lieu = m.group(1).strip()
            break

    # JSON-LD location fallback
    if not lieu:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    loc = item.get("location", {})
                    if isinstance(loc, dict):
                        lieu = loc.get("name", "") or ""
            except Exception:
                pass
            if lieu:
                break

    return {
        "titre":      titre,
        "date_str":   date_str,
        "prix_raw":   prix_raw,
        "lieu":       lieu,
        "description": desc,
        "full_text":  full_text[:3000],   # for debugging
    }


# ─────────────────────────────────────────────────────────────────
# VERIFICATION CORE
# ─────────────────────────────────────────────────────────────────

def verify_event(ev: dict) -> dict | None:
    """
    Fetch ev["URL"], compare all fields against the stored card data.
    Returns an error report dict if issues found, else None.
    """
    url = ev.get("URL", "").strip()
    if not url:
        return {
            "event": ev,
            "errors": [{"field": "URL", "issue": "URL manquante", "card_value": "", "page_value": ""}],
            "url_status": "missing",
        }

    soup = fetch(url)
    if soup is None:
        return {
            "event": ev,
            "errors": [{"field": "URL", "issue": "URL inaccessible (404/timeout)", "card_value": url, "page_value": ""}],
            "url_status": "unreachable",
        }

    page = extract_page_data(soup, url)
    errors = []

    # ── 1. Titre ──
    card_titre = ev.get("titre", "")
    page_titre = page.get("titre", "")
    if card_titre and page_titre:
        sim = similarity(card_titre, page_titre)
        if sim < TITLE_SIM_THRESHOLD and not contains(card_titre, page_titre):
            errors.append({
                "field":       "titre",
                "issue":       f"Titre divergent (similarité {sim:.0%})",
                "card_value":  card_titre,
                "page_value":  page_titre,
            })

    # ── 2. Date ──
    card_date = ev.get("date", "")
    page_date = page.get("date_str", "")
    page_full = page.get("full_text", "")

    if card_date:
        card_date_objects = parse_dates_in_text(card_date)
        page_date_objects = parse_dates_in_text(page_full)   # broad search on full text

        if card_date_objects and page_date_objects:
            # At least the first card date should appear somewhere on the page
            card_start = min(card_date_objects)
            # Allow ±3 day tolerance for date-of-next-occurrence logic
            if not any(abs((pd - card_start).days) <= 3 for pd in page_date_objects):
                errors.append({
                    "field":       "date",
                    "issue":       "Date carte non retrouvée sur la page",
                    "card_value":  card_date,
                    "page_value":  page_date or "(aucune date trouvée)",
                })
        elif card_date and not page_date_objects:
            errors.append({
                "field":       "date",
                "issue":       "La carte a une date mais la page n'en affiche aucune",
                "card_value":  card_date,
                "page_value":  "(aucune date trouvée)",
            })

    # ── 3. Prix ──
    card_prix = ev.get("prix", "")
    if not prices_compatible(card_prix, page_full):
        errors.append({
            "field":      "prix",
            "issue":      "Prix carte incompatible avec la page",
            "card_value": card_prix,
            "page_value": page.get("prix_raw", "(non trouvé)"),
        })

    # ── 4. Lieu ──
    card_lieu = ev.get("lieu", "")
    page_lieu = page.get("lieu", "")
    # Only flag if both have a value and they clearly don't match
    if card_lieu and page_lieu:
        if similarity(card_lieu, page_lieu) < 0.50 and not contains(page_lieu, card_lieu) and not contains(card_lieu, page_lieu):
            errors.append({
                "field":      "lieu",
                "issue":      "Lieu carte différent de la page",
                "card_value": card_lieu,
                "page_value": page_lieu,
            })

    # ── 5. Description ──
    card_desc = ev.get("description", "")
    page_desc = page.get("description", "")
    # Flag only if card has a substantial description that has no overlap with the page
    if card_desc and len(card_desc) > 60 and page_desc:
        sim = similarity(card_desc[:200], page_desc[:200])
        # Also check if key phrases from the card description appear on the full page
        first_sentence = re.split(r"[.!?]", card_desc)[0].strip()
        if sim < TEXT_SIM_THRESHOLD and not contains(first_sentence, page_full):
            errors.append({
                "field":      "description",
                "issue":       f"Description carte divergente de la page (similarité {sim:.0%})",
                "card_value":  card_desc[:150] + "…",
                "page_value":  page_desc[:150] + "…",
            })

    # ── 6. Image reachable ──
    card_image = ev.get("image", "")
    if card_image:
        try:
            r = requests.head(card_image, headers=HEADERS, timeout=8, allow_redirects=True)
            if r.status_code >= 400:
                errors.append({
                    "field":      "image",
                    "issue":      f"Image inaccessible (HTTP {r.status_code})",
                    "card_value": card_image[:80] + "…",
                    "page_value": "",
                })
        except requests.RequestException as e:
            errors.append({
                "field":      "image",
                "issue":      f"Image inaccessible ({type(e).__name__})",
                "card_value": card_image[:80] + "…",
                "page_value": "",
            })

    if errors:
        return {
            "event":       ev,
            "errors":      errors,
            "url_status":  "ok",
            "verified_at": datetime.now().isoformat(timespec="seconds"),
        }
    return None


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

BANNER = r"""
 ____       _            _   _                 _
|  _ \  ___| |_ ___  ___| |_(_)_   _____ _ __ | |_
| | | |/ _ \ __/ _ \/ __| __| \ \ / / _ \ '_ \| __|
| |_| |  __/ ||  __/ (__| |_| |\ V /  __/ | | | |_
|____/ \___|\__\___|\___|\__|_| \_/ \___|_| |_|\__|
"""


def load_events(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Support both {"evenements": [...]} and [...]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("evenements", "events", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Flat dict of a single event?
        if "URL" in data:
            return [data]
    raise ValueError(f"Format non reconnu dans {path}")


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(description="Detectivent – vérificateur d'événements")
    parser.add_argument("--input",  default=INPUT_FILE,  help="Fichier JSON source")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Fichier JSON erreurs")
    parser.add_argument("--limit",  type=int, default=0,  help="Limiter à N événements")
    parser.add_argument("--url",    default="",           help="Vérifier un seul URL")
    parser.add_argument("--delay",  type=float, default=0.8, help="Délai entre requêtes (s)")
    args = parser.parse_args()

    # ── Load events ──
    if args.url:
        events = [{"titre": "?", "URL": args.url}]
    else:
        try:
            events = load_events(args.input)
        except FileNotFoundError:
            print(f"❌  Fichier introuvable : {args.input}")
            sys.exit(1)

    if args.limit:
        events = events[:args.limit]

    total = len(events)
    print(f"🔍  {total} événement(s) à vérifier depuis « {args.input} »")
    print(f"⏱   Délai entre requêtes : {args.delay}s\n")
    print("─" * 60)

    errors_found = []
    ok_count     = 0
    skip_count   = 0

    for i, ev in enumerate(events, 1):
        titre = ev.get("titre", "?")[:55]
        url   = ev.get("URL", "")
        print(f"  [{i:>3}/{total}] {titre:<55}", end=" ", flush=True)

        if not url:
            print("⚠️  URL manquante")
            skip_count += 1
            continue

        result = verify_event(ev)

        if result is None:
            print("✅")
            ok_count += 1
        else:
            error_labels = ", ".join(e["field"] for e in result["errors"])
            print(f"❌  [{error_labels}]")
            for e in result["errors"]:
                print(f"       ↳ {e['field']}: {e['issue']}")
                if e.get("card_value"):
                    print(f"          carte → {str(e['card_value'])[:80]}")
                if e.get("page_value"):
                    print(f"          page  → {str(e['page_value'])[:80]}")
            errors_found.append(result)

        if i < total:
            time.sleep(args.delay)

    # ── Summary ──
    print("\n" + "─" * 60)
    print(f"\n📊  Résultats :")
    print(f"   ✅  {ok_count} événement(s) correct(s)")
    print(f"   ❌  {len(errors_found)} événement(s) avec erreurs")
    if skip_count:
        print(f"   ⚠️   {skip_count} événement(s) ignoré(s) (URL manquante)")

    # ── Write output ──
    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file":  args.input,
        "total_checked": total,
        "errors_count": len(errors_found),
        "errors": errors_found,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n💾  Résultats écrits dans « {args.output} »")

    if errors_found:
        print(f"\n⚠️   {len(errors_found)} carte(s) à corriger — consultez {args.output}")
    else:
        print("\n🎉  Toutes les cartes sont conformes aux pages sources !")


if __name__ == "__main__":
    main()
