# Créer un rapport — DocFlow AI

## Rapport libre

1. **Page Rapports** → Sélectionner les documents dans l'arborescence (ou drag & drop)
2. Choisir le mode : **Rapport libre**
3. Saisir ou sélectionner un prompt (ex: "Synthèse de direction en 10 points")
4. Choisir le modèle : `mixtral` (qualité) ou `mistral` (rapidité)
5. Cliquer **Générer**
6. Le rapport s'affiche progressivement (streaming)
7. Exporter en **PDF** ou **DOCX**

## Remplir un template

1. Uploader un template DOCX avec des champs `{{ nom_champ }}`
2. Sélectionner le mode **Remplir un template**
3. Sélectionner le template uploadé
4. Les champs détectés s'affichent
5. Ajouter des instructions optionnelles
6. Générer → le template est rempli avec les données des documents

## Classement / Tri

1. Sélectionner un ensemble de documents
2. Choisir le mode **Classement**
3. Utiliser un preset ou saisir les critères
4. Générer → liste classée avec justifications

## Prompts pré-enregistrés

Des prompts sont disponibles par défaut (chargés depuis `scripts/seed-prompts.json`) :
- Rapport de synthèse
- Classement alphabétique
- Extraction d'entités
- Analyse comparative
- Résumé exécutif
- Classement par priorité

Vous pouvez sauvegarder vos propres prompts.

## TODO Phase 2

Fonctionnalité à implémenter. Ce guide sera complété.
