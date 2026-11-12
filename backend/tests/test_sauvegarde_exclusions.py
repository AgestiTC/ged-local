"""Sauvegarde : les tables reconstructibles gardent leur structure, pas leurs données."""

from services import backup


def test_tables_reconstructibles_exclues_du_dump():
    args = backup.arguments_pg_dump("hote", "5432", "docflow", "docflow", "/tmp/x.dump")
    assert args[0] == "pg_dump" and args[-2:] == ["-f", "/tmp/x.dump"] and "-Fc" in args
    exclues = [a.split("=", 1)[1] for a in args if a.startswith("--exclude-table-data=")]
    assert exclues == list(backup.TABLES_RECONSTRUCTIBLES)
    # L'inventaire se refait par un scan, le corps des mails se retélécharge : inutile de les
    # sauvegarder. La structure, elle, reste dans le dump (jamais `--exclude-table`).
    assert {"inv_entrees", "inv_instantanes", "inv_envoi_dossiers", "mail_corps"} == set(exclues)
    assert not any(a.startswith("--exclude-table=") for a in args)


def test_ce_qui_ne_se_reconstruit_pas_reste_sauvegarde():
    """Emplacements, postes et historique des scans sont saisis ou accumulés : on les garde."""
    for table in ("inv_emplacements", "inv_postes", "inv_scans", "inv_doublons_passes"):
        assert table not in backup.TABLES_RECONSTRUCTIBLES
