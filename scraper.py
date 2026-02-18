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
        response = requests.get(url, headers=self.headers)
        soup = BeautifulSoup(response.text, 'html.parser')
    
        # On cherche tous les articles ou blocs qui ressemblent à une carte
        for card in soup.find_all(['article', 'div'], class_=lambda x: x and 'card' in x.lower()):    
            titre = card.find(['h2', 'h3', 'h4'])
            if titre:
            self.events.append({
            "titre": titre.text.strip(),
            "lieu": "MNBAQ (Grande Allée)",
            "theme": "arts",
            "age": "3-12 ans",
            "semaine": "1", # À lier avec la fonction de date plus haut
            "prix": "Gratuit",
            "image": card.find('img')['src'] if card.find('img') else "https://via.placeholder.com/500",
            "description": "Atelier créatif pour toute la famille."
            })

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
    # Force un événement test pour vérifier l'affichage
    scraper.events.append({
    "titre": "Événement Test",
    "lieu": "Partout à Québec",
    "theme": "arts",
    "age": "all",
    "semaine": "1",
    "prix": "Gratuit",
    "image": "https://via.placeholder.com/500",
    "description": "Si vous voyez ceci, le pipeline fonctionne !"
    })
    scraper.enregistrer_json()
