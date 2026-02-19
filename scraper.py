import requests
from bs4 import BeautifulSoup
import json

class QuebecFamilyScraper:
    def __init__(self):
        # Liste pour stocker nos dictionnaires d'événements
        self.events = []
        # Le "User-Agent" simule un navigateur pour ne pas être 
            
    def scrape_mnbaq(self):
        url = "https://www.mnbaq.org/programmation/famille"
        # On imite un iPad réel pour contourner les protections de base
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr-ca,fr;q=0.9',
            'Referer': 'https://www.google.com/'
        }
    
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            print(f"DEBUG - Status Code: {response.status_code}")
            
            # On affiche un extrait pour voir si le contenu est là
            print(f"DEBUG - Extrait HTML: {response.text[:500].replace('', '')}")
    
            soup = BeautifulSoup(response.text, 'html.parser')

            # PLAN C : On cherche spécifiquement les liens qui pointent vers une activité
            # Souvent, le titre est DANS un lien vers l'activité
            liens_activites = soup.find_all('a', href=True)
            
            for lien in liens_activites:
                href = lien['href']
                # On cherche les liens qui contiennent "/activite/"
                if '/activite/' in href or '/activites/' in href:
                    titre = lien.text.strip()
                    
                    # On ignore les textes trop courts ou les doublons
                    if len(titre) > 10 and not any(e['titre'] == titre for e in self.events):
                        # On remonte au parent pour essayer de trouver une image
                        parent = lien.find_parent(['div', 'article', 'section'])
                        img_url = "https://via.placeholder.com/500x300?text=MNBAQ"
                        if parent:
                            img = parent.find('img')
                            if img and img.has_attr('src'):
                                img_url = img['src']
                                if img_url.startswith('/'): img_url = "https://www.mnbaq.org" + img_url

                        self.events.append({
                            "titre": titre,
                            "lieu": "MNBAQ (Grande Allée)",
                            "theme": "arts",
                            "age": "Famille",
                            "semaine": "1",
                            "prix": "Gratuit / Inclus",
                            "image": img_url,
                            "description": "Activité découverte au Musée national des beaux-arts du Québec."
                        })
    
            print(f"Résultat final : {len(self.events)} activités trouvées.")
    
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
