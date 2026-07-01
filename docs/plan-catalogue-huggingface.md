# Plan — Page « Catalogue HuggingFace » (tuiles de modèles)

> Consigné le 01/07/2026, à la demande de l'utilisateur : une **page HuggingFace** avec un
> **catalogue en tuiles** de modèles récents et maintenus, triés par catégorie, avec date,
> version, tags « maintenu » et « censored/uncensored ».

## ❓ Besoin

Une page qui **explore le hub HuggingFace** et présente des modèles pertinents pour Matothèque
sous forme de **cartes (tuiles)**, pour choisir/installer facilement de nouveaux modèles.

**Critères demandés :**
- Modèles de **≤ 2 ans** (récents) **et toujours maintenus**.
- **Regroupés par catégorie = fonction du modèle** (raisonnement/LLM, embeddings, vision/OCR, audio…).
- Chaque carte affiche : **catégorie**, **version/variante**, **date de mise en ligne** (+ dernière MAJ),
  **tag « toujours maintenu »**, **tag censored / uncensored** 😈, popularité (downloads/likes), cadenas si **gated**.

## ⚠️ Contraintes NON négociables (rappel — cf. mémoire « sortie Internet »)

- La page **contacte HuggingFace** (API `huggingface.co/api/models`) → c'est une **sortie Internet**.
  → **Confirmation** avant chaque appel (garde-fou), et **rattachement** à la logique
    « Demandes Mise à jour internet ».
- **ZÉRO fuite** : on n'envoie **que** le token HF (auth) + les **filtres de recherche publics**
  (catégorie, tri). **Jamais** un document, tag, résumé, nom de fichier.
- Une fois un modèle **installé, tout tourne 100% local** (Ollama). HF n'intervient qu'au
  **téléchargement**.

## Source de données

`GET https://huggingface.co/api/models` (avec `Authorization: Bearer <token>` si configuré).
Paramètres utiles : `pipeline_tag`, `sort=lastModified|downloads|likes`, `direction=-1`, `limit`,
`full=true`, `filter=<tag>`. Champs exploités par carte :

| Champ HF | Usage carte |
|---|---|
| `id` (`org/model`) | nom + lien |
| `pipeline_tag` | **catégorie / fonction** |
| `tags[]` | détection uncensored, langue, quantization, `gguf` |
| `createdAt` | **date de mise en ligne** |
| `lastModified` | **dernière MAJ** → tag « maintenu » |
| `downloads`, `likes` | popularité |
| `gated` | cadenas (accès restreint) |
| `library_name` | compat (gguf/ollama) |

## Règles de filtrage / tags

- **≤ 2 ans** : `createdAt >= now - 2 ans` (ou `lastModified`).
- **« Toujours maintenu »** : `lastModified >= now - 6 mois` (badge vert).
- **Catégorie (fonction)** — mapping `pipeline_tag` → rôle projet :
  - **Raisonnement / LLM** : `text-generation`
  - **Embeddings** : `feature-extraction`, `sentence-similarity`
  - **Vision / OCR** : `image-text-to-text`, `image-to-text`, `visual-question-answering`
  - **Audio** (openplaud/Voxtral) : `automatic-speech-recognition`
- **Censored / Uncensored** 😈 : **heuristique** (pas de flag HF officiel) — `id`/`tags` contiennent
  `uncensored|abliterated|dolphin` → 😈 ; sinon « officiel/standard ». (Afficher « indéterminé » honnêtement.)
- **Installable via Ollama** : `gguf` dans `tags`/`library_name` → bouton « Installer » actif
  (`ollama pull hf.co/<id>:<quant>`) ; sinon carte « info seule » (pull non direct).

## Architecture

### Backend — `routers/huggingface.py`
- `GET /api/huggingface/catalog?category=&maintained=&max_age_years=2&sort=&limit=`
  → appelle l'API HF (token depuis config, déchiffré), applique les filtres âge/maintenu,
  normalise en `{id, categorie, version, created_at, last_modified, maintained, uncensored,
  gated, downloads, likes, gguf}`. **Cache mémoire court** (ex. 10 min) pour limiter les appels.
- Réutilise le pull existant (`ollama pull`) pour l'installation (déjà branché + confirmé).

### Frontend — `HuggingFacePage.tsx` (+ route + entrée sidebar)
- **Garde-fou** : au 1er chargement / rafraîchissement → **modal de confirmation réseau**
  (réutilise `netConfirm`) ; rien ne part sans validation.
- **Filtres** en haut : catégorie (onglets/segments), « maintenu seulement », tri (récent/populaire),
  recherche texte.
- **Grille de tuiles** : par carte → nom, **badge catégorie**, **date mise en ligne** + **dernière MAJ**,
  badge **« maintenu »** (vert), **😈 / officiel**, downloads/likes, cadenas gated,
  bouton **« Installer »** (si gguf) → confirmation → `ollama pull` (progression réutilisée).
- **Regroupement par catégorie** (sections) conformément à la demande.

## Phasage

- **Phase 1 — Backend** : router `huggingface.py` + endpoint catalogue (appel HF, filtres âge/maintenu,
  normalisation, cache) + mapping catégories + heuristique uncensored. Test avec le token « Agesti ».
- **Phase 2 — Frontend** : page + route + sidebar + grille de tuiles + filtres + badges
  (date, maintenu, 😈, gated) + garde-fou réseau (confirmation).
- **Phase 3 — Installation** : bouton « Installer » sur carte gguf → confirmation → `ollama pull`
  + progression → le modèle apparaît ensuite dans « Modèles installés ».

## Points d'attention

- **Volume d'appels HF** : mettre en cache + pas d'appel au simple montage (bouton « Charger le
  catalogue » explicite, confirmé).
- **gated** : certains modèles exigent d'avoir accepté les conditions sur HF (le pull peut échouer
  malgré le token) → message clair.
- **Uncensored = heuristique** : ne pas prétendre à une détection fiable ; afficher le doute.
- **Compat Ollama** : seuls les **GGUF** se pull directement ; les autres = « voir sur HF ».
- **Confidentialité** : la page est une **sortie Internet** → confirmation systématique, zéro donnée doc.

## Statut

- **À implémenter** (Phases 1→3). Rien encore codé — plan validé à cadrer avec l'utilisateur.
