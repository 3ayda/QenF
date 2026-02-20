import requests
from bs4 import BeautifulSoup
import json

class QuebecFamilyScraper:
    def __init__(self):
        # Liste pour stocker nos dictionnaires d'événements
        self.events = []
        # Le "User-Agent" simule un navigateur pour ne pas être 
            
    def scrape_mnbaq(self):
        url = "https://www.mnbaq.org/programmation/familles"
        # On imite un iPad réel pour contourner les protections de base
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr-ca,fr;q=0.9',
            'Referer': 'https://www.google.com/'
        }
    
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # On cherche les conteneurs de cartes (le MNBAQ utilise souvent des <article> ou des classes 'c-card')
            # On va chercher tous les blocs qui contiennent un lien ET une image
            conteneurs = soup.find_all(['article', 'div'], class_=lambda x: x and ('card' in x or 'activity' in x))
    
            for card in conteneurs:
                # 1. Trouver le titre (souvent un h2 ou h3 avec une classe title)
                titre_el = card.find(['h2', 'h3', 'h4', 'a'], class_=lambda x: x and 'title' in x.lower())
                if not titre_el:
                    titre_el = card.find(['h2', 'h3'])
                
                if not titre_el: continue
                titre = titre_el.get_text().strip()
    
                # --- FILTRE DE QUALITÉ ---
                # On ignore les titres trop courts ou trop génériques
                if len(titre) < 10 or titre.lower() in ["atelier", "quoi faire en famille", "activités"]:
                    continue
    
                # 2. Trouver l'image (Gestion du Lazy Loading)
                img_el = card.find('img')
                img_url = "https://via.placeholder.com/500x300?text=MNBAQ"
                if img_el:
                    # On teste plusieurs sources possibles d'images sur les sites modernes
                    img_url = img_el.get('data-src') or img_el.get('srcset') or img_el.get('src') or img_url
                    # Nettoyage si c'est une liste d'images (srcset)
                    if ',' in img_url: img_url = img_url.split(',')[0].split(' ')[0]
                    if img_url.startswith('/'): img_url = "https://www.mnbaq.org" + img_url
    
                # 3. Trouver la description (le texte qui suit le titre)
                desc_el = card.find(['p', 'div'], class_=lambda x: x and 'description' in x.lower())
                description = desc_el.get_text().strip() if desc_el else "Découvrez cette activité familiale au musée."
                if len(description) > 150: description = description[:147] + "..."
    
                # Éviter les doublons
                if any(e['titre'] == titre for e in self.events): continue
    
                self.events.append({
                    "titre": titre,
                    "lieu": "MNBAQ (Grande Allée)",
                    "theme": "arts",
                    "age": "Tout âge",
                    "semaine": "1",
                    "prix": "Gratuit / Inclus",
                    "image": img_url,
                    "description": description
                })
    
            print(f"Scraping terminé : {len(self.events)} activités réelles trouvées.")
    
        except Exception as e:
            print(f"Erreur : {e}")  

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
