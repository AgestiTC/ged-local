# conftest.py racine du backend
# Ajoute le répertoire backend/ au sys.path pour les imports relatifs dans les tests.

import sys
from pathlib import Path

# Permet d'importer "from services.xxx import" directement depuis backend/
sys.path.insert(0, str(Path(__file__).parent))
