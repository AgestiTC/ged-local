"""
Connecteurs de sources externes (cloud / NAS distants) — LECTURE.
=================================================================
Chaque connecteur implémente la même interface `SourceConnector`
(test / browse / walk_files / fetch_to_temp) que le client SMB, de sorte que
le pipeline d'indexation existant les traite de façon uniforme.

Un **compte connecté = une ligne `Source`** (multi-comptes natif). L'importation
de ce package **enregistre** les connecteurs disponibles dans le registre.
"""
from services.connectors.base import SourceConnector, get_connector, register, types_supportes  # noqa: F401

# Enregistrement des connecteurs (à l'import du package).
from services.connectors import synology  # noqa: E402,F401
from services.connectors import gdrive     # noqa: E402,F401
