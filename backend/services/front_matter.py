"""
En-tête (« front-matter ») des fichiers Markdown déposés par les applications
=============================================================================
Plan « Recevoir la documentation des autres applications », étape 3. Format attendu, en TOUT début
de fichier :

    ---
    appli: composeur-yealink
    version: 1.5.18
    titre: Guide du Composeur Yealink T54W
    ---

Volontairement minimal et STRICT : uniquement des lignes `clé: valeur` (pas de YAML complet, donc
ni PyYAML ni exécution de quoi que ce soit). Seules les clés connues sont gardées, valeurs bornées.
Un en-tête absent ou mal formé → `(None, texte d'origine)` : l'import continue normalement.
"""
import re

CLES = ("appli", "version", "titre")
EXTENSIONS = ("md", "markdown")
_LIGNE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
_MAX_VALEUR = 200
_MAX_LIGNES = 40


def lire(texte: str | None) -> tuple[dict | None, str]:
    """Sépare l'en-tête du corps. Rend `(en_tete | None, corps)` ; le corps est le texte SANS l'en-tête."""
    if not texte:
        return None, texte or ""
    brut = texte.lstrip("﻿")
    lignes = brut.splitlines()
    if not lignes or lignes[0].strip() != "---":
        return None, texte
    fin = next((i for i in range(1, min(len(lignes), _MAX_LIGNES + 2)) if lignes[i].strip() in ("---", "...")), None)
    if fin is None:
        return None, texte
    en_tete: dict = {}
    for ligne in lignes[1:fin]:
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        m = _LIGNE.match(ligne)
        if not m:
            return None, texte              # ligne non conforme : on n'interprète rien
        cle, valeur = m.group(1).lower(), m.group(2)
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        if cle in CLES and valeur:
            en_tete[cle] = valeur[:_MAX_VALEUR]
    corps = "\n".join(lignes[fin + 1:]).lstrip("\n")
    return (en_tete or None), corps
