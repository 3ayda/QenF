"""
scraper.py – Orchestrateur principal
Appelle tous les scrapers de sources et produit un evenements.json unifié.

Sources :
  - MNBAQ       (scraper_mnbaq.py)
  - Bibliothèque de Québec  (scraper_bdq.py)
  - Moulin des Jésuites     (scraper_moulin.py)
"""

import json, sys

OUTPUT_FILE = "evenements.json"

def run_scraper(module_name, label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    try:
        import importlib
        mod = importlib.import_module(module_name)
        return mod.main()
    except Exception as e:
        print(f"❌ Erreur dans {module_name}: {e}")
        import traceback; traceback.print_exc()
        return []

if __name__ == "__main__":
    all_events = []

    all_events += run_scraper("scraper_mnbaq",  "MNBAQ – Activités Familles")
    all_events += run_scraper("scraper_bdq",    "Bibliothèque de Québec")
    all_events += run_scraper("scraper_moulin", "Moulin des Jésuites")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"🎉 Total : {len(all_events)} événements exportés dans {OUTPUT_FILE}")
    print(f"{'='*60}")
