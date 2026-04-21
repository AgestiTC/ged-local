# Rapport comparatif — DocFlow AI

## Vue d'ensemble

Le mode **Comparatif** permet de comparer plusieurs candidats, sociétés ou dossiers côte à côte, et d'exporter le résultat dans un fichier Excel rempli automatiquement par l'IA.

**Cas d'usage typiques :**
- Comparer des offres de candidats (CV, lettres de motivation)
- Évaluer des prestataires ou fournisseurs
- Analyser des dossiers de réponse à appel d'offres

---

## Prérequis

1. **Documents indexés** : les fichiers à comparer doivent être importés et enrichis (statut `enriched`)
2. **Template Excel** : un fichier `.xlsx` avec les colonnes souhaitées en ligne 1

---

## Préparer un template Excel

Le template Excel définit les colonnes du tableau comparatif. L'IA remplira une **ligne par groupe** en extrayant les informations correspondantes dans les documents.

**Format attendu :**
- Ligne 1 : en-têtes de colonnes (noms des informations à extraire)
- Le reste du tableau sera rempli automatiquement

**Exemple de template :**

| Nom | Expérience (années) | Compétences clés | Prétentions salariales | Disponibilité |
|-----|---------------------|------------------|------------------------|---------------|
| *(rempli par l'IA)* | | | | |

**Uploader le template :** Page **Paramètres → Templates** → glisser le fichier `.xlsx`

---

## Utiliser le mode Comparatif

### Étape 1 — Sélectionner le mode

Dans la page **Rapports**, sélectionner le mode **Comparatif** (icône graphique).

### Étape 2 — Construire les groupes (GroupBuilder)

Chaque groupe représente un candidat ou une société. Deux méthodes :

#### Méthode automatique (recommandée)

Si les fichiers ont été importés par dossier (tag automatique) :
→ Cliquer sur **"Charger les groupes depuis les dossiers importés"**

Le système lit le premier tag de chaque document et crée un groupe par tag.

```
OFFRE_MASSON/   → Groupe "OFFRE_MASSON" avec tous ses fichiers
OFFRE_DUPONT/   → Groupe "OFFRE_DUPONT" avec tous ses fichiers
```

#### Méthode manuelle

1. Cliquer sur **"Ajouter un candidat / société"**
2. Saisir le nom du groupe
3. Déplier le groupe (chevron) et cocher les documents à inclure
4. Utiliser la recherche pour filtrer rapidement les documents

#### Actions sur les documents dans un groupe

Au survol d'un document dans un groupe :
- **Flèche →** : déplacer vers un autre groupe
- **× rouge** : retirer du groupe (le document reste dans la GED)

### Étape 3 — Choisir le template et les instructions

- Sélectionner un template Excel dans le menu déroulant
- (Optionnel) Ajouter des instructions supplémentaires pour guider l'IA

### Étape 4 — Lancer la comparaison

Cliquer sur **"Générer le rapport comparatif"**.

---

## Progression en temps réel (SSE)

Après le lancement, la colonne droite affiche la progression groupe par groupe :

```
⏳ OFFRE_MASSON    [en cours...]
✓  OFFRE_DUPONT   [terminé]
○  OFFRE_MARTIN   [en attente]

████████░░░░  67%
```

États possibles par groupe :
| Icône | Signification |
|-------|---------------|
| `○` cercle gris | En attente |
| `⟳` spinner | Analyse en cours |
| `✓` vert | Terminé |
| `✗` rouge | Erreur |

---

## Téléchargement du résultat

Une fois tous les groupes traités :
- Le fichier Excel est **téléchargé automatiquement**
- Un bouton de téléchargement manuel reste disponible si le téléchargement automatique échoue

Le fichier est nommé `comparatif_YYYYMMDD_HHMMSS.xlsx` et stocké dans `storage/exports/`.

---

## Fonctionnement interne

### Analyse par groupe

Pour chaque groupe, l'IA reçoit :
- Le contenu textuel de tous les documents du groupe (tronqué à 60 000 caractères si nécessaire)
- La liste des colonnes du template à remplir
- Les instructions supplémentaires (si fournies)

L'IA retourne un JSON `{colonne: valeur}`. Si une information est absente, la cellule contient `N/A`.

### Modèle utilisé

Par défaut : modèle configuré dans les paramètres (`mistral` ou `mixtral`). Peut être sélectionné manuellement.

### Remplissage Excel

Le template original n'est pas modifié. Un nouveau fichier est créé :
- Ligne 1 : en-têtes (copiées depuis le template)
- Ligne 2+ : une ligne par groupe, colonnes remplies par l'IA

---

## API

```
POST /api/generate/compare
Body: {
  "groupes": [
    {"nom": "OFFRE_MASSON", "document_ids": ["uuid1", "uuid2"]},
    {"nom": "OFFRE_DUPONT", "document_ids": ["uuid3"]}
  ],
  "template_id": "uuid-template",
  "model": "mistral:latest",          // optionnel
  "instructions": "Sois concis."      // optionnel
}
→ 202 { "job_id": "...", "stream_url": "/api/generate/compare/stream/{job_id}" }

GET /api/generate/compare/stream/{job_id}   → SSE (text/event-stream)
GET /api/generate/compare/download/{job_id} → fichier Excel
```

### Événements SSE

```json
{"groupe": "OFFRE_MASSON", "statut": "running", "index": 1, "total": 3}
{"groupe": "OFFRE_MASSON", "statut": "done",    "index": 1, "total": 3}
{"statut": "complete", "download_url": "/api/generate/compare/download/{job_id}"}
{"statut": "failed",   "erreur": "message d'erreur"}
```
