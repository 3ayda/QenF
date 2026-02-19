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
            
            # --- NOUVELLE STRATÉGIE : LE SCANNER ---
            # On cherche tout ce qui a la classe "title" ou qui ressemble à un titre d'activité
            # Les sites modernes utilisent souvent des classes comme 'c-card__title'
            potential_titles = soup.find_all(class_=lambda x: x and ('title' in x or 'activity' in x))
            
            if not potential_titles:
                # Plan B : On cherche toutes les balises h2 et h3 sans distinction
                potential_titles = soup.find_all(['h2', 'h3'])
    
            for element in potential_titles:
                titre = element.get_text().strip()
                
                # On cherche des mots-clés pour filtrer les menus/liens inutiles
                if len(titre) > 5 and any(word in titre.lower() for word in ['famille', 'atelier', 'créatif', 'relâche']):
                    
                    # Éviter les doublons
                    if any(e['titre'] == titre for e in self.events): continue
    
                    # On tente de trouver l'image la plus proche de ce titre
                    parent = element.find_parent(['div', 'article', 'section'])
                    img_url = "https://via.placeholder.com/500x300?text=MNBAQ"
                    if parent:
                        img = parent.find('img')
                        if img and img.has_attr('src'):
                            img_url = img['src']
                            if img_url.startswith('/'): img_url = "https://www.mnbaq.org" + img_url
    
                    self.events.append({
                        "titre": titre,
                        "lieu": "MNBAQ (Québec)",
                        "theme": "arts",
                        "age": "Famille",
                        "semaine": "1",
                        "prix": "Gratuit / Inclus",
                        "image": img_url,
                        "description": "Une activité culturelle pour la relâche au MNBAQ."
                    })
    
            # --- DIAGNOSTIC FINAL DANS LE LOG ---
            if len(self.events) == 0:
                print("DIAGNOSTIC : Aucune balise trouvée. Le site est probablement 100% JavaScript.")
                # On affiche les 10 premières classes CSS trouvées pour nous aider
                classes = [c for tag in soup.find_all(True) for c in tag.get('class', [])]
                print(f"Classes trouvées sur la page : {list(set(classes))[:15]}")
            else:
                print(f"Succès : {len(self.events)} activités trouvées !")
    
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
