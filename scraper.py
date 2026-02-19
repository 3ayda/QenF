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
        url = "https://www.mnbaq.org/programmation/famille"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # On cherche tous les conteneurs qui pourraient être une carte
            # (souvent des balises <article> ou des <div> avec beaucoup de contenu)
            potentiels = soup.find_all(['article', 'div', 'section'])
            
            for item in potentiels:
                # On cherche un titre à l'intérieur
                titre_el = item.find(['h2', 'h3', 'h4'])
                if not titre_el or len(titre_el.text.strip()) < 3:
                    continue
                    
                titre = titre_el.text.strip()
                
                # FILTRE : On ne veut que les trucs de famille/ateliers
                mots_cles = ['famille', 'atelier', 'enfant', 'relâche', 'dimanche', 'créatif']
                if any(mot in titre.lower() for mot in mots_cles):
                    
                    # On évite les doublons
                    if any(e['titre'] == titre for e in self.events):
                        continue
    
                    # On tente de trouver une image dans ce bloc
                    img_el = item.find('img')
                    img_url = img_el['src'] if img_el and img_el.has_attr('src') else "https://via.placeholder.com/500x300?text=MNBAQ"
                    
                    # Si l'URL de l'image est relative (ex: /img.jpg), on ajoute le domaine
                    if img_url.startswith('/'):
                        img_url = "https://www.mnbaq.org" + img_url
    
                    self.events.append({
                        "titre": titre,
                        "lieu": "MNBAQ (Plaines d'Abraham)",
                        "theme": "arts",
                        "age": "Famille",
                        "semaine": "1", # On pourra affiner avec la date plus tard
                        "prix": "Gratuit / Inclus",
                        "image": img_url,
                        "description": "Une activité culturelle pour stimuler la créativité des petits et grands."
                    })
            
            print(f"Bulldozer a trouvé {len(self.events)} activités au MNBAQ.")
    
        except Exception as e:
            print(f"Erreur Bulldozer : {e}")

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
