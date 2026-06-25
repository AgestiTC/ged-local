# Fonctionnement général — DocFlow AI

## Vue d'ensemble

DocFlow AI est une plateforme **100% locale** de gestion et d'analyse documentaire. Aucune donnée ne quitte votre réseau.

```
┌─────────────────────────────────────────────────────┐
│                 Interface Web (React)                │
│  Page Rapports │ Page GED │ Page Paramètres          │
└──────────────────────┬──────────────────────────────┘
                       │ REST API
              ┌────────▼────────┐
              │  FastAPI Backend │
              └──┬────┬────┬────┘
                 │    │    │
           Tika  │  Ollama│  PostgreSQL
           9998  │  11434 │  5432 + pgvector
```

## Services

| Service | Rôle | URL |
|---------|------|-----|
| **FastAPI** | API backend | `http://NAS:8000` |
| **React/Nginx** | Interface web | `http://NAS:3003` |
| **PostgreSQL + pgvector** | Base de données | interne Docker |
| **Apache Tika** | Extraction texte de tous formats | `http://NAS:9998` |
| **Ollama** | LLM local (génération + embeddings) | `http://PC-GAMER:11434` |
| **n8n** | Surveillance dossiers (optionnel) | `http://PC-GAMER:5678` |

## Modèles Ollama utilisés

| Modèle | Usage |
|--------|-------|
| `mixtral:latest` | Génération de rapports (modèle principal) |
| `mistral:latest` | Enrichissement IA rapide (catégorie, tags, résumé) |
| `qwen3-embedding:8b` | Embeddings vectoriels pour la recherche sémantique |

---

## Pipeline de traitement d'un document

```
Fichier importé (upload / drag-drop / dossier surveillé)
   │
   ▼
1. Calcul SHA256 → vérification doublon
   │
   ▼
2. Sauvegarde dans storage/uploads/
   │
   ▼
3. Insertion en DB  (statut = pending)
   │ Si folder_tag détecté → tag dossier appliqué immédiatement
   ▼
4. Apache Tika extrait le texte + métadonnées
   │ (PDF, DOCX, PPTX, XLSX, ZIP, ODT...)
   │ statut = extracted
   ▼
5. Ollama (mistral) enrichit le document :
   │ → catégorie, sous-catégorie
   │ → tags (fusionnés avec le tag dossier)
   │ → résumé
   │ → entités (personnes, dates, lieux, organisations)
   │ → mots-clés
   │ statut = enriched
   ▼
6. Génération des embeddings (qwen3-embedding:8b)
   │ → découpage en chunks de 500 tokens
   │ → vecteurs stockés dans pgvector
   ▼
Document prêt pour la recherche et les rapports
```

## Pages de l'interface

### Page Rapports (page principale)

3 colonnes :
- **Gauche** : import de fichiers (drag & drop) + liste des documents indexés
- **Centre** : choix du mode + configuration + prompt
- **Droite** : résultat / progression

4 modes de sortie :
1. **Rapport libre** — génère un rapport Markdown depuis les documents sélectionnés
2. **Template** — remplit un template DOCX avec les données extraites
3. **Classement** — trie ou classe les documents selon des critères
4. **Comparatif** — compare plusieurs candidats/sociétés et exporte un Excel

### Page GED

- Recherche hybride (full-text + sémantique)
- Filtres par catégorie, tags, type, date
- Fiche document avec métadonnées, résumé IA, historique des versions

### Page Paramètres

- Gestion des dossiers surveillés
- Configuration des modèles Ollama
- Gestion des prompts pré-enregistrés
- Gestion des templates
- Statistiques système et tests de connexion

---

## Statuts des documents

| Statut | Signification |
|--------|---------------|
| `pending` | Fichier reçu, extraction en attente |
| `extracted` | Texte extrait par Tika, enrichissement IA en attente |
| `enriched` | Enrichissement IA + embeddings terminés |
| `error` | Erreur lors du traitement |
