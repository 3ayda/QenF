"""
quartier.py – Résolution automatique du quartier / arrondissement
               pour n'importe quelle adresse ou nom de lieu à Québec.

Logique :
  1. Cherche des mots-clés de quartiers précis dans le texte du lieu.
  2. Retourne le label affiché dans l'UI (options du filtre Quartier).

Étiquettes retournées (= valeurs <option> dans index.html) :
  "Vieux-Québec", "Montcalm", "La Cité-Limoilou",
  "Charlesbourg", "Les Rivières", "Beauport",
  "La Haute-Saint-Charles", "Sainte-Foy–Sillery–Cap-Rouge"

Usage :
    from quartier import resoudre_quartier
    q = resoudre_quartier("MNBAQ, Grande Allée Est, Québec")
    # → "Montcalm"
"""

import unicodedata


# ─────────────────────────────────────────────────────────────────
# TABLE DE CORRESPONDANCE
# Ordre important : règles les plus précises d'abord.
# ─────────────────────────────────────────────────────────────────

QUARTIER_RULES = [

    # ── Vieux-Québec ──────────────────────────────────────────────
    ([
        "vieux-québec", "vieux québec", "vieux-quebec", "vieux quebec",
        "haute-ville", "haute ville", "basse-ville", "basse ville",
        "petit-champlain", "petit champlain", "place royale",
        "château frontenac", "chateau frontenac", "terrasse dufferin",
        "rue saint-louis", "rue des remparts", "fortifications",
        "cap-blanc", "cap blanc", "colline parlementaire",
        "quartier latin", "rue d'auteuil", "côte de la fabrique",
        "rue buade", "porte saint-jean", "porte saint jean",
    ], "Vieux-Québec"),

    # ── Montcalm ──────────────────────────────────────────────────
    ([
        "montcalm",
        "grande allée", "grande allee",
        "avenue cartier", "av. cartier", "av cartier",
        "plaines d'abraham", "plaines abraham",
        "musée national des beaux-arts", "mnbaq",
        "grand théâtre", "grand theatre",
        "complexe méduse", "complexe meduse",
        "saint-sacrement", "saint sacrement",
        "boulevard rené-lévesque ouest",
    ], "Montcalm"),

    # ── Charlesbourg ──────────────────────────────────────────────
    ([
        "charlesbourg",
        "trait-carré", "trait carré", "trait carre", "trécarré", "trecarre",
        "bourg-royal", "bourg royal",
        "notre-dame-des-laurentides", "notre dame des laurentides",
        "orsainville",
        "des jésuites", "des jesuites", "moulin des jésuites",
        "boulevard henri-bourassa",
        "galeries charlesbourg",
        "zoo de québec", "zoo de quebec", "jardin zoologique",
        "parc des moulins",
    ], "Charlesbourg"),

    # ── Les Rivières ──────────────────────────────────────────────
    ([
        "les rivières", "les rivieres",
        "neufchâtel", "neufchatel",
        "lebourgneuf", "le bourg-neuf",
        "duberger", "les saules",
        "vanier",
        "boulevard hamel",
        "centre vidéotron", "centre videotron",
        "parc victoria", "expocité", "expocite",
    ], "Les Rivières"),

    # ── Beauport ──────────────────────────────────────────────────
    ([
        "beauport",
        "chute montmorency", "chutes montmorency", "montmorency",
        "d'estimauville", "d estimauville",
        "giffard", "villeneuve", "courville",
        "avenue royale",
    ], "Beauport"),

    # ── La Haute-Saint-Charles ────────────────────────────────────
    ([
        "la haute-saint-charles", "haute-saint-charles", "haute saint charles",
        "val-bélair", "val belair",
        "lac-saint-charles", "lac saint charles",
        "saint-émile", "saint emile",
        "loretteville", "lorette",
        "l'ancienne-lorette", "ancienne lorette", "ancienne-lorette",
        "wendake",
        "parc du mont bélair", "mont belair", "mont bélair",
    ], "La Haute-Saint-Charles"),

    # ── Sainte-Foy – Sillery – Cap-Rouge ─────────────────────────
    ([
        "sainte-foy", "sainte foy",
        "sillery",
        "cap-rouge", "cap rouge",
        "université laval", "universite laval", "ulaval",
        "cité universitaire", "cite universitaire",
        "cégep garneau", "cegep garneau",
        "place laurier", "place de la cité",
        "boulevard laurier",
        "promenade samuel-de-champlain", "promenade champlain",
        "chemin saint-louis",
        "avenue maguire",
        "pont pierre-laporte", "pont de québec",
        "du plateau", "pointe-de-sainte-foy",
    ], "Sainte-Foy–Sillery–Cap-Rouge"),

    # ── La Cité-Limoilou (attrape-tout pour le reste du centre) ───
    ([
        "la cité-limoilou", "la cite-limoilou",
        "cité-limoilou", "cite-limoilou",
        "saint-roch", "saint roch",
        "rue saint-joseph", "rue saint joseph",
        "saint-jean-baptiste", "saint jean baptiste",
        "faubourg saint-jean", "faubourg saint jean",
        "saint-sauveur", "saint sauveur",
        "limoilou", "vieux-limoilou", "vieux limoilou",
        "lairet", "maizerets",
        "3e avenue", "troisième avenue",
        "parc cartier-brébeuf", "parc cartier brebeuf",
        "bibliothèque gabrielle-roy", "bibliotheque gabrielle-roy",
    ], "La Cité-Limoilou"),
]


# ─────────────────────────────────────────────────────────────────
# NORMALISATION
# ─────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Minuscules sans accents pour comparaison robuste."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def resoudre_quartier(lieu: str) -> str:
    """
    Retourne le label de quartier/arrondissement pour un texte de lieu.
    Retourne "" si aucun match trouvé.

    Exemples :
        resoudre_quartier("MNBAQ, Grande Allée Est")  →  "Montcalm"
        resoudre_quartier("Chutes Montmorency")       →  "Beauport"
        resoudre_quartier("Lieu inconnu")             →  ""
    """
    if not lieu:
        return ""
    normalised = _normalise(lieu)
    for keywords, label in QUARTIER_RULES:
        for kw in keywords:
            if _normalise(kw) in normalised:
                return label
    return ""


# ─────────────────────────────────────────────────────────────────
# AUTO-TEST  (python quartier.py)
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cas = [
        ("MNBAQ – Pavillon Pierre Lassonde, Grande Allée Est",        "Montcalm"),
        ("Musée de la civilisation, rue Dalhousie, Vieux-Québec",     "Vieux-Québec"),
        ("Bibliothèque Gabrielle-Roy, rue Saint-Joseph, Saint-Roch",  "La Cité-Limoilou"),
        ("3e Avenue, Vieux-Limoilou",                                  "La Cité-Limoilou"),
        ("Centre Vidéotron, Les Rivières",                             "Les Rivières"),
        ("Chutes Montmorency, Beauport",                               "Beauport"),
        ("Université Laval, Sainte-Foy",                               "Sainte-Foy–Sillery–Cap-Rouge"),
        ("Galeries Charlesbourg",                                      "Charlesbourg"),
        ("Val-Bélair, La Haute-Saint-Charles",                         "La Haute-Saint-Charles"),
        ("Wendake, Nation Huronne-Wendat",                             "La Haute-Saint-Charles"),
        ("Grand Théâtre de Québec",                                    "Montcalm"),
        ("Porte Saint-Jean, Vieux-Québec",                             "Vieux-Québec"),
        ("Lieu totalement inconnu",                                    ""),
    ]

    print(f"\n{'Lieu':<57} {'Attendu':<32} {'Résultat':<32} Statut")
    print("─" * 130)
    ok = 0
    for lieu, attendu in cas:
        res = resoudre_quartier(lieu)
        match = "✅" if res == attendu else "❌"
        if res == attendu:
            ok += 1
        print(f"{lieu:<57} {attendu:<32} {res:<32} {match}")
    print(f"\n{'─'*130}")
    print(f"  {ok}/{len(cas)} tests réussis\n")
