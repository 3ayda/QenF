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
            
            # ÉTAPE 1 : On ramasse TOUS les titres H2, H3 et H4 de la page
            # C'est là que se cachent les noms des activités
            titres_potentiels = soup.find_all(['h2', 'h3', 'h4'])
            
            print(f"DEBUG : J'ai trouvé {len(titres_potentiels)} titres au total sur la page.")
    
            for el in titres_potentiels:
                titre = el.get_text().strip()
                
                # ÉTAPE 2 : Filtres simples pour garder les vraies activités
                if len(titre) < 10: continue # Trop court (ex: "Atelier")
                if "famille" not in titre.lower() and "atelier" not in titre.lower() and "défi" not in titre.lower():
                    # On garde quand même si c'est un titre important (H2 ou H3)
                    if el.name not in ['h2', 'h3']: continue
    
                # Éviter les doublons
                if any(e['titre'] == titre for e in self.events): continue
    
                # ÉTAPE 3 : Trouver l'image et le lien
                # On cherche l'image la plus proche du titre
                parent = el.find_parent(['div', 'article', 'section'])
                img_url = "https://via.placeholder.com/500x300?text=MNBAQ"
                if parent:
                    img = parent.find('img')
                    if img:
                        img_url = img.get('data-src') or img.get('src') or img_url
                        if img_url.startswith('/'): img_url = "https://www.mnbaq.org" + img_url
    
                # ÉTAPE 4 : Ajouter à la liste
                self.events.append({
                    "titre": titre,
                    "lieu": "MNBAQ (Grande Allée)",
                    "theme": "arts",
                    "age": "Famille",
                    "semaine": "1",
                    "prix": "Gratuit / Inclus",
                    "image": img_url,
                    "description": "Une activité culturelle au Musée national des beaux-arts du Québec."
                })
    
            print(f"Résultat final : {len(self.events)} activités trouvées.")
    
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
