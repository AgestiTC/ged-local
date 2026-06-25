# GED — Gestion Électronique de Documents

## Vue d'ensemble

La page **GED** permet de rechercher, consulter et gérer tous les documents indexés dans DocFlow AI.

---

## Recherche

### Recherche hybride (défaut)

La recherche combine deux approches :
- **Full-text** (poids 40 %) : PostgreSQL `ts_vector` sur le texte extrait et le nom de fichier
- **Sémantique** (poids 60 %) : cosine similarity via pgvector sur les embeddings `qwen3-embedding:8b`

Le score hybride est normalisé : `score_hybride = 0.4 × score_texte + 0.6 × score_sémantique`

### Modes de recherche

| Mode | Description |
|------|-------------|
| `hybrid` | Full-text + sémantique (recommandé) |
| `text` | Full-text uniquement (plus rapide) |
| `semantic` | Sémantique uniquement (nécessite que les embeddings soient générés) |

### Filtres disponibles

- **Catégorie** : catégorie déterminée par l'IA lors de l'enrichissement
- **Extension** : `pdf`, `docx`, `pptx`, `xlsx`, etc.
- **Tag** : filtrer par un tag spécifique (ex : `OFFRE_MASSON`)

---

## Métadonnées IA

Chaque document enrichi possède des métadonnées générées automatiquement :

| Champ | Description |
|-------|-------------|
| `categorie` | Catégorie principale du document |
| `sous_categorie` | Sous-catégorie |
| `tags` | Liste de tags (inclut le tag dossier si import par dossier) |
| `resume` | Résumé auto-généré |
| `langue` | Langue détectée |
| `entites` | Entités extraites : personnes, dates, lieux, organisations |
| `mots_cles` | Mots-clés extraits |
| `niveau_confidentialite` | `normal` / `confidentiel` / `restreint` |

### Modifier les métadonnées

Les tags, la catégorie, le résumé et autres champs sont **éditables** via l'interface (fiche document) ou l'API :

```
PATCH /api/documents/{id}/metadata
Body: { "tags": ["RH", "CV", "2024"], "categorie": "Ressources humaines" }
```

Seuls les champs fournis sont mis à jour. Les autres restent inchangés.

---

## Fiche document

La fiche document affiche :
- **Informations générales** : nom, extension, taille, date d'import, statut, source
- **Métadonnées IA** : catégorie, tags, résumé, entités, mots-clés
- **Historique des versions** : liste des versions détectées avec hash et date

---

## Historique des versions

DocFlow détecte automatiquement les nouvelles versions d'un document (même chemin, hash différent). Chaque version est enregistrée avec :
- Numéro de version
- Hash SHA256
- Taille
- Date de détection
- Résumé des changements (si généré par l'IA)

---

## Statistiques

`GET /api/documents/stats` retourne :
- Total de documents par statut (`pending`, `extracted`, `enriched`, `error`)
- Taille totale stockée
- Top 10 des catégories

---

## API GED

### Recherche

```
GET /api/search?q=rapport+annuel&type=hybrid&limit=20
GET /api/search?q=contrat&type=text&categorie=Juridique&extension=pdf
GET /api/search?q=budget&type=semantic&offset=20

GET /api/search/tags         → tous les tags avec fréquence
GET /api/search/categories   → toutes les catégories avec fréquence
```

**Réponse recherche :**
```json
{
  "query": "rapport annuel",
  "type": "hybrid",
  "total": 12,
  "resultats": [
    {
      "id": "uuid",
      "nom": "rapport_2024.pdf",
      "score": 0.8734,
      "metadonnees_ia": {
        "categorie": "Finance",
        "tags": ["rapport", "annuel", "2024"],
        "resume": "Rapport annuel consolidé...",
        "langue": "fr"
      }
    }
  ]
}
```

### Documents

```
GET    /api/documents                        → liste paginée
GET    /api/documents?statut=enriched        → filtrer par statut
GET    /api/documents?tag=OFFRE_MASSON       → filtrer par tag
GET    /api/documents?q=contrat&extension=pdf → recherche par nom
GET    /api/documents/{id}                   → détail complet
GET    /api/documents/{id}/text              → texte extrait brut
GET    /api/documents/{id}/metadata          → métadonnées IA
GET    /api/documents/{id}/versions          → historique versions
GET    /api/documents/{id}/jobs              → jobs associés
PATCH  /api/documents/{id}/metadata          → modifier les métadonnées
DELETE /api/documents/{id}                   → supprimer de l'index
POST   /api/documents/purge-duplicates       → nettoyer les doublons
```

**Paramètres de liste :**
| Paramètre | Type | Description |
|-----------|------|-------------|
| `page` | int | Numéro de page (défaut : 1) |
| `page_size` | int | Documents par page (1–100, défaut : 20) |
| `statut` | string | `pending` / `extracted` / `enriched` / `error` |
| `extension` | string | `pdf`, `docx`, `pptx`… |
| `source` | string | `watch` / `upload` / `drag_drop` |
| `q` | string | Recherche par nom de fichier |
| `tag` | string | Filtrer par tag exact |
