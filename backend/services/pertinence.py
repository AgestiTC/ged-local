"""
Pertinence — gate ABSOLU « ce document répond-il vraiment à la requête ? »
==========================================================================
Le score renvoyé par la recherche est **normalisé par le meilleur résultat du lot**
(`score / max`) : le premier vaut donc toujours ~100 %, même quand tout le lot est
hors-sujet. Il ne peut pas servir à détecter « aucun document pertinent » — le top
survit à n'importe quel seuil.

Ce module fournit la mesure **absolue**, calibrée le 02/07/2026 sur corpus réel
(cf. docs/plan-recherche-pertinence-seuil.md §3.3) :

    pertinent = (cosinus >= SEUIL_HAUT)  OU  (cosinus >= SEUIL_BAS  ET  match lexical)

Le cosinus seul ne suffit pas : son plancher est haut (~0.51 pour une requête totalement
hors-sujet comme « recette de tarte aux pommes ») et il y a chevauchement — « dossier de
mariage », sans aucune réponse dans le corpus, score 0.657, au-dessus de « contrat de
location » qui en a une (0.618). Aucun seuil unique ne sépare les deux.

Le **match full-text** (`plainto_tsquery @@`) est le discriminant qui manquait : les
requêtes sans réponse ne matchent aucun document, les vraies requêtes moyennes si.
"""

# Surchargeables en base via runtime_config (`search_cos_haut` / `search_cos_bas`).
# Historique : 0.72 / 0.60 (calibration 02/07, corpus dev ~520 docs).
# Re-calibré le 16/07/2026 sur le corpus NAS réel (56 k docs) : le plancher cosinus y est
# nettement plus haut (icônes/zips ~0.62-0.65 sur n'importe quelle requête), donc SEUIL_BAS
# est monté 0.60 → 0.65 pour rejeter les faux positifs (« dossier de mariage » : cerfa 0.64,
# questionnaire 0.63 tombent). Les requêtes témoins « recette » / « mariage » rendent alors 0
# pertinent ; « facture » / « contrat » / « attestation » gardent leurs bons résultats.
SEUIL_HAUT_DEFAUT = 0.72   # haute confiance : le sens suffit, pas besoin des mots
SEUIL_BAS_DEFAUT = 0.65    # accepté seulement si les mots sont là aussi

ELEVEE = "elevee"
MOYENNE = "moyenne"
FAIBLE = "faible"


def seuils() -> tuple[float, float]:
    """Seuils effectifs (haut, bas) : config en base si valide, sinon calibration par défaut."""
    from services import runtime_config

    def lire(cle: str, defaut: float) -> float:
        try:
            valeur = float(runtime_config.effective(cle))
        except (TypeError, ValueError):
            return defaut
        # Un cosinus vit dans [0, 1] : une valeur hors bornes désactiverait le gate en silence.
        return valeur if 0.0 < valeur <= 1.0 else defaut

    return lire("search_cos_haut", SEUIL_HAUT_DEFAUT), lire("search_cos_bas", SEUIL_BAS_DEFAUT)


def evaluer(
    cosinus: float | None, match_texte: bool, haut: float, bas: float
) -> tuple[bool, str]:
    """
    Applique le gate à un document → (pertinent, étiquette).

    `cosinus` vaut None quand la mesure sémantique n'existe pas pour ce document :
    recherche en mode texte pur, ou document trouvé lexicalement mais absent du top
    sémantique. Le match lexical fait alors foi — c'est le signal fort de la calibration,
    et les requêtes que l'on veut rejeter n'en ont aucun.
    """
    if cosinus is not None and cosinus >= haut:
        return True, ELEVEE
    if match_texte and (cosinus is None or cosinus >= bas):
        return True, MOYENNE
    return False, FAIBLE
