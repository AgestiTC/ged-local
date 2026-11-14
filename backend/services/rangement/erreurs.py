"""Erreurs métier du module Rangement — remplace la `BusinessError` du socle de rangement."""


class InventaireRefus(ValueError):
    """Demande refusée, avec un message lisible et un code stable (l'API répond 400 ou 409)."""

    def __init__(self, message: str, code: str, statut: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.statut = statut


class RangementRefuse(ValueError):
    """Lot de rangement impossible (rien n'a bougé), ou ligne refusée : message lisible."""
