"""
Contributeurs fiscaux livrés avec l'application.

Ajouter un module fiscal = ajouter un fichier ici et une ligne dans `installer_tous()`.
**Aucune ligne d'interface à toucher** : l'onglet affiche ce que le registre lui rend.
"""

from services.fiscalite.contributeurs import emploi_domicile, ged_pieces


def installer_tous() -> None:
    """Enregistre tous les contributeurs livrés. Idempotent (cf. `registre.enregistrer`)."""
    ged_pieces.installer()
    emploi_domicile.installer()
