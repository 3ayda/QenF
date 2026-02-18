import requests
from bs4 import BeautifulSoup
import json

class QuebecFamilyScraper:
    def __init__(self):
        # Liste pour stocker nos dictionnaires d'événements
        self.events = []
        # Le "User-Agent" simule un navigateur pour ne pas être bloqué
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def scrape_mnbaq(self):
    url = "https://www.mnbaq.org/activites/famille"
    try:
        response = requests.get(url, headers=self.headers)
        print(f"Status MNBAQ: {response.status_code}") # Doit être 200
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Test 1: On cherche TOUS les liens qui contiennent "activites"
        liens = soup.find_all('a', href=True)
        activites_potentielles = [l for l in liens if '/activites/' in l['href']]
        print(f"Nombre de liens d'activités trouvés: {len(activites_potentielles)}")

        # Test 2: Recherche par balise générique (plus robuste)
        # On cherche des articles ou des div qui ont une classe contenant 'card'
        cards = soup.find_all(['article', 'div'], class_=lambda x: x and 'card' in x.lower())
        print(f"Nombre de cartes trouvées: {len(cards)}")

        for item in cards:
            titre_el = item.find(['h2', 'h3', 'h4', 'span'], class_=lambda x: x and 'title' in x.lower())
            if not titre_el:
                titre_el = item.find(['h2', 'h3']) # Plan B

            if titre_el:
                titre = titre_el.text.strip()
                # On évite les doublons
                if not any(e['titre'] == titre for e in self.events):
                    self.events.append({
                        "titre": titre,
                        "lieu": "MNBAQ (Grande Allée)",
                        "theme": "arts",
                        "age": "Famille",
                        "semaine": "1",
                        "prix": "Gratuit",
                        "image": item.find('img')['src'] if item.find('img') else "https://via.placeholder.com/500",
                        "description": "Consultez le site du MNBAQ pour les détails de cet atelier."
                    })
    except Exception as e:
        print(f"Erreur MNBAQ : {e}")

    def enregistrer_json(self):
        """Génère le fichier que le site Web va lire"""
        # La ponctuation ici est vitale : indent=4 pour la lisibilité, ensure_ascii=False pour les accents québécois
        with open('evenements.json', 'w', encoding='utf-8') as f:
            json.dump(self.events, f, ensure_ascii=False, indent=4)
        print(f"Succès ! {len(self.events)} événements enregistrés dans evenements.json")

# --- EXECUTION ---
if __name__ == "__main__":
    scraper = QuebecFamilyScraper()
    scraper.scrape_mnbaq()
    # On pourrait ajouter scraper.scrape_moulin() ici
    scraper.enregistrer_json()
