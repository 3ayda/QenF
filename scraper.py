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
        """Extraction des données du MNBAQ"""
        url = "https://www.mnbaq.org/activites/famille"
        try:
            response = requests.get(url, headers=self.headers)
            # Vérifie si la page a bien été téléchargée (Code 200)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # On cherche les conteneurs d'événements (Sélecteurs à ajuster selon le site)
                for item in soup.select('.activity-card'):
                    # Création du dictionnaire avec la ponctuation correcte (clés: valeurs)
                    event_data = {
                        "titre": item.select_one('.title').text.strip(),
                        "lieu": "MNBAQ (Plaines d'Abraham)",
                        "theme": "arts",  # On met en minuscule pour correspondre au JS
                        "age": "3-12",     # Valeur par défaut si non trouvée
                        "semaine": "2",    # Idem
                        "prix": "Gratuit",
                        "image": item.find('img')['src'] if item.find('img') else "https://via.placeholder.com/500",
                        "description": item.select_one('.description').text.strip() if item.select_one('.description') else ""
                    }
                    self.events.append(event_data)
        except Exception as e:
            print(f"Erreur lors du scraping MNBAQ : {e}")

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
