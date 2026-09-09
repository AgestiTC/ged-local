"""
Test de garde — les `server_default` qui contiennent une apostrophe
===================================================================
Écrit après un incident réel (**v1.93.0, prod à terre**) : une colonne déclarée

    server_default="'{}'::jsonb"

part en base sous la forme ``'''{}''::jsonb'`` — SQLAlchemy ré-échappe les apostrophes
d'une **chaîne**. Sous PostgreSQL, le `CREATE TABLE` échoue (« invalid input syntax for
type json »), le backend refuse de démarrer, et le frontend rend 502.

**Aucun test fonctionnel ne pouvait l'attraper** : la suite tourne sous SQLite, qui accepte
ce défaut sans broncher. Le bug n'existe qu'en production. D'où ce test, qui ne teste pas un
comportement mais une **forme d'écriture** — le seul moyen de le voir avant le déploiement.

La forme correcte est `server_default=text("'{}'::jsonb")` : `models/publieur.py` l'utilisait
déjà, ce qui rend l'oubli d'autant plus bête. Les valeurs sans apostrophe (`"0"`, `"false"`)
ne posent aucun problème et restent autorisées telles quelles.
"""

import re
from pathlib import Path

import pytest

DOSSIER_MODELES = Path(__file__).resolve().parent.parent / "models"

# Capture le contenu d'un `server_default=` écrit sous forme de CHAÎNE littérale (simple ou
# double quote), en ignorant les `server_default=text(...)` et `server_default=func...`.
_RE_DEFAUT = re.compile(r"""server_default\s*=\s*(?P<q>["'])(?P<valeur>.*?)(?P=q)""", re.DOTALL)


def _fichiers_modeles() -> list[Path]:
    return sorted(p for p in DOSSIER_MODELES.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("fichier", _fichiers_modeles(), ids=lambda p: p.name)
def test_server_default_avec_apostrophe_passe_par_text(fichier: Path):
    """
    Un `server_default` contenant une apostrophe DOIT passer par `text(...)`.

    Sans quoi PostgreSQL reçoit une valeur doublement échappée et refuse la table — en
    production seulement, puisque SQLite l'accepte.
    """
    contenu = fichier.read_text(encoding="utf-8")
    fautifs = [
        m.group("valeur") for m in _RE_DEFAUT.finditer(contenu)
        if "'" in m.group("valeur")
    ]
    assert not fautifs, (
        f"{fichier.name} : server_default={fautifs!r} écrit comme une chaîne. "
        "SQLAlchemy ré-échappe les apostrophes → CREATE TABLE invalide sous PostgreSQL. "
        "Utiliser server_default=text(\"...\") (cf. models/publieur.py)."
    )


@pytest.mark.parametrize("fichier", _fichiers_modeles(), ids=lambda p: p.name)
def test_server_default_sans_cast_specifique_a_postgres(fichier: Path):
    """
    L'autre moitié du même piège, découverte en corrigeant la première.

    `text(...)` émet du **SQL brut**, donc un cast `::jsonb` part tel quel — et SQLite, sur
    laquelle tourne toute la suite, ne connaît pas cette syntaxe : la création des tables
    échoue et **plus aucun test ne peut s'exécuter**. Un `'{}'` seul suffit, PostgreSQL le
    coerce vers le type de la colonne.
    """
    contenu = fichier.read_text(encoding="utf-8")
    fautifs = [
        m.group(1) for m in
        re.finditer(r"""server_default\s*=\s*text\(\s*["'](.*?)["']\s*\)""", contenu)
        if "::" in m.group(1)
    ]
    assert not fautifs, (
        f"{fichier.name} : server_default=text({fautifs!r}) contient un cast PostgreSQL. "
        "text() émet du SQL brut : SQLite ne sait pas le lire et toute la suite tombe. "
        "Retirer le cast — le type de la colonne suffit."
    )
