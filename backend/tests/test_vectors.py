"""
Tests du helper Matryoshka (`utils.vectors.matryoshka_prefix`).

Fonction PURE au cœur de la recherche sémantique accélérée (E7) : dérive un préfixe 1024-d
L2-normalisé d'un embedding 4096-d (indexable ANN), sans ré-embed. Une erreur ici fausserait
tout le classement de la 1ᵉ passe.
"""

import math

from utils.vectors import SMALL_DIM, matryoshka_prefix


def test_longueur_prefixe():
    out = matryoshka_prefix([0.5] * 4096)
    assert out is not None and len(out) == SMALL_DIM == 1024


def test_prefixe_est_normalise():
    out = matryoshka_prefix([3.0] * 4096)
    norme = math.sqrt(sum(x * x for x in out))
    assert abs(norme - 1.0) < 1e-9


def test_prend_bien_le_debut():
    # Les 1024 premières composantes valent 2, le reste 9 → seules les premières comptent.
    vec = [2.0] * 1024 + [9.0] * (4096 - 1024)
    out = matryoshka_prefix(vec)
    # Toutes égales → après normalisation, chaque composante = 1/sqrt(1024).
    attendu = 1.0 / math.sqrt(1024)
    assert all(abs(x - attendu) < 1e-9 for x in out)


def test_vecteur_trop_court_rend_none():
    assert matryoshka_prefix([0.1] * 512) is None
    assert matryoshka_prefix([]) is None
    assert matryoshka_prefix(None) is None


def test_vecteur_nul_rend_none():
    # Norme nulle → pas de normalisation possible.
    assert matryoshka_prefix([0.0] * 4096) is None
