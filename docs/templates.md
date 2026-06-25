# Gestion des templates — DocFlow AI

## Types de templates

| Type | Extension | Usage |
|------|-----------|-------|
| **DOCX** | `.docx` | Rapport structuré avec champs `{{ variable }}` |
| **XLSX** | `.xlsx` | Tableau comparatif multi-groupes |
| **PDF** | `.pdf` | Template statique (champs détectés si présents) |

---

## Templates DOCX — Remplissage de champs

### Préparer un template DOCX

Dans votre document Word, indiquez les emplacements à remplir avec la syntaxe `{{ nom_du_champ }}`.

**Exemple :**
```
Candidat : {{ nom }}
Poste visé : {{ poste }}
Expérience : {{ experience }} ans
Résumé : {{ resume }}
```

DocFlow détecte automatiquement tous les champs `{{ ... }}` lors de l'upload.

### Uploader un template DOCX

1. Aller sur la page **Paramètres → Templates**
2. Glisser le fichier `.docx` sur la zone de dépôt (ou cliquer pour parcourir)
3. Le système détecte et affiche les champs trouvés

### Utiliser un template DOCX

Dans la page **Rapports** :
1. Sélectionner le mode **Template**
2. Choisir le template dans le menu déroulant
3. Sélectionner les documents sources dans la colonne gauche
4. (Optionnel) Ajouter des instructions
5. Cliquer sur **Générer**

L'IA analyse les documents et remplit chaque champ `{{ ... }}` avec la valeur extraite.

---

## Templates XLSX — Rapport comparatif

### Préparer un template XLSX

Le template Excel pour le mode comparatif suit une règle simple :
- **Ligne 1** : en-têtes de colonnes = informations à extraire
- Les autres lignes sont ignorées (elles seront remplacées par les données)

**Exemple :**

| Nom complet | Poste actuel | Années d'expérience | Formation | Disponibilité | Prétentions |
|-------------|--------------|---------------------|-----------|---------------|-------------|

DocFlow détecte les colonnes de la ligne 1 comme champs à remplir. Il détecte aussi les patterns `{{ champ }}` dans le reste du classeur.

### Uploader un template XLSX

Même procédure que pour les DOCX : **Paramètres → Templates** → glisser le fichier `.xlsx`.

### Utiliser un template XLSX

Le template XLSX est utilisé exclusivement dans le mode **Comparatif**.  
Voir [rapport-comparatif.md](rapport-comparatif.md) pour le workflow complet.

---

## Gestion des templates (page Paramètres)

### Lister les templates

La page Paramètres affiche tous les templates uploadés avec :
- Nom et type (DOCX / XLSX / PDF)
- Nombre de champs détectés
- Date d'upload

### Supprimer un template

Cliquer sur le bouton supprimer dans la liste. Le fichier physique est effacé du disque.

---

## API Templates

```
GET    /api/templates              → liste tous les templates
POST   /api/templates              → uploader un template (multipart/form-data)
GET    /api/templates/{id}         → détail + liste des champs détectés
DELETE /api/templates/{id}         → supprimer (DB + fichier disque)
```

**Réponse POST :**
```json
{
  "id": "uuid",
  "nom": "Grille évaluation candidats",
  "type": "xlsx",
  "nb_champs": 6,
  "champs": [
    {"nom": "Nom complet", "type": "texte", "description": null},
    {"nom": "Années d'expérience", "type": "texte", "description": null}
  ]
}
```

---

## Stockage

Les fichiers templates sont stockés dans `storage/templates/` (volume Docker persistant).  
En cas de conflit de nom, un suffixe aléatoire est ajouté automatiquement.
