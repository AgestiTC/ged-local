"""Schéma de l'inventaire (`models/inventaire.py`) — ce qui se vérifie sans base."""

import re

from models import Base
from models.inventaire import SCHEMA_INVENTAIRE, TABLES, instructions_manquantes

_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)")
_INDEX = re.compile(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)")
_REFERENCE = re.compile(r"REFERENCES (\w+)")


def _tables_creees() -> list[str]:
    return [m.group(1) for sql in SCHEMA_INVENTAIRE if (m := _TABLE.search(sql))]


def _index_crees() -> list[str]:
    return [m.group(1) for sql in SCHEMA_INVENTAIRE if (m := _INDEX.search(sql))]


def test_les_neuf_tables_une_fois_chacune():
    assert _tables_creees() == list(TABLES)
    assert len(TABLES) == 9 and all(t.startswith("inv_") for t in TABLES)


def test_une_table_referencee_est_creee_avant():
    """Sur une base vide, les instructions se jouent dans l'ordre : une référence vers une table
    pas encore créée ferait échouer tout le schéma."""
    deja: set[str] = {"jetons_api"}   # table du socle, créée par create_all avant ce schéma
    for sql in SCHEMA_INVENTAIRE:
        table = _TABLE.search(sql)
        for cible in _REFERENCE.findall(sql):
            assert cible in deja, f"{cible} référencée avant d'être créée"
        if table:
            deja.add(table.group(1))


def test_que_des_instructions_rejouables():
    """Aucun ALTER, aucun DROP : le schéma se rejoue à chaque démarrage sans rien verrouiller."""
    for sql in SCHEMA_INVENTAIRE:
        assert _TABLE.match(sql.strip()) or _INDEX.match(sql.strip()), sql[:60]


def test_base_vide_tout_est_a_jouer():
    assert instructions_manquantes(set(), set()) == list(SCHEMA_INVENTAIRE)


def test_base_a_jour_rien_a_jouer():
    assert instructions_manquantes(set(TABLES), set(_index_crees())) == []


def test_seul_ce_qui_manque_est_joue():
    index = set(_index_crees()) - {"inv_entrees_tailles"}
    a_jouer = instructions_manquantes(set(TABLES) - {"inv_instantanes"}, index)
    assert len(a_jouer) == 2
    assert "inv_entrees_tailles" in a_jouer[0] and "inv_instantanes" in a_jouer[1]


def test_tables_hors_des_modeles_orm():
    """`create_all` ne doit pas tenter de les créer sous SQLite (index partiels, text_pattern_ops)."""
    assert not set(TABLES) & set(Base.metadata.tables)
