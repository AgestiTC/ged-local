"""
Aide à la déclaration d'impôts — registre, millésime et contributeurs.

Le paquet est volontairement **sans import au chargement** : `registre` et `millesime`
s'importent seuls, et l'installation des contributeurs est un geste explicite
(`contributeurs.installer_tous()`), appelé au démarrage de l'application. Un paquet qui
enregistrerait ses contributeurs par effet de bord rendrait les tests dépendants de
l'ordre des imports.
"""
