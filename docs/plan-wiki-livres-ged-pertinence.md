# Plan — Wiki lisible/indexé + GED par pertinence

> Origine : retours utilisateur du **2026-07-14**. Trois chantiers liés autour de BookStack
> (`wiki.agesti.fr`) et de la page GED. Service existant réutilisé : `backend/services/bookstack_service.py`.

## Décisions (Q/R du 2026-07-14)

| Question | Réponse |
|----------|---------|
| Ouverture d'un livre depuis « Liste des livres » | **Les deux** : lecture intégrée in-app **+** bouton « Ouvrir dans BookStack ↗ » |
| Granularité d'indexation des livres | **1 document par PAGE** BookStack |
| Maquette GED (résultats par pertinence) | **« Livres épinglés + tranches »** (validée) ; la section Livres est elle aussi repliable |
| Ordre de livraison | **Chantier 1 → 2 → 3** (Liste des livres, puis Indexation, puis Refonte GED) |

Maquettes ASCII validées (3 vues : GED groupé, Liste des livres, Lecture intégrée) — cf. conversation.

---

## Chantier 1 — Liste des livres (Wiki lisible) 🥇

**But** : une page listant les livres BookStack avec **couvertures en miniature**, ouvrant soit la
**lecture intégrée**, soit BookStack.

**Backend** (`bookstack_service` + nouveau `routers/wiki.py`) :
- `list_books()` existe déjà. Ajouter : `get_book(id)` (détail + `contents` = chapitres/pages),
  `get_page(id)` (HTML rendu), `cover_bytes(book)` (télécharge la couverture **authentifiée** → proxy).
- Endpoints : `GET /api/wiki/books` · `GET /api/wiki/books/{id}` · `GET /api/wiki/pages/{id}` ·
  `GET /api/wiki/books/{id}/cover` (image proxifiée, placeholder si aucune).

**Frontend** :
- `wikiApi` (books, book, page, coverUrl).
- Page **`/wiki/livres`** (`WikiBooksPage`) : grille de cartes (couverture, titre, description, nb pages) + filtre.
- Page **`/wiki/livres/:id`** (`WikiBookReader`) : sommaire (chapitres/pages) + rendu de la page + bouton « Ouvrir dans BookStack ↗ ».
- Sidebar : sous-menu Wiki → ajouter **« Liste des livres »** (au-dessus de Publier).

**Risques** : couvertures = fetch authentifié (proxy obligatoire) ; rendu HTML de page à assainir (sanitize).

---

## Chantier 2 — Indexation des livres (lus par l'IA, cherchables) 🥈

**But** : rendre le contenu des livres **cherchable** dans la GED ; les pages apparaissent sous la
**catégorie « livre »**.

**Backend** (handler dédié, pattern `connector_jobs.py` pour éviter le WIP de `job_handlers.py`) :
- `@register("index_wiki")` : parcourt books → pages. Pour **chaque page** : upsert d'un `documents` :
  - `chemin = wiki://{book_id}/{page_id}` (identifiant stable), `source = 'wiki'`, `nom` = titre de page,
    `extension = 'wiki'`.
  - `texte_extrait` = HTML → texte, `metadonnees_ia.categorie = 'livre'` (**forcée**),
    `sous_categorie` = nom du livre, `tags = [nom du livre]`.
  - **Embeddings** (chunk + embed) pour la recherche sémantique.
  - **Idempotence** : hash sur `page_id + updated_at` BookStack → ré-indexe si modifié ; **supprime** les
    docs des pages retirées.
- Déclenchement : bouton **« Indexer le wiki »** (page Liste des livres et/ou Paramètres → BookStack).
  Resync périodique = **option ultérieure**.

**Frontend** : bouton « Indexer le wiki » + suivi de job (réutilise l'UI de progression existante).

**Risques** : volume (beaucoup de pages) ; garder l'indexation **hors event-loop** (worker dédié, déjà en place).

---

## Chantier 3 — Refonte GED par pertinence 🥉

**But** : résultats de recherche en **sections repliables** : 📚 Livres épinglés, puis tranches de %,
puis « Tous ».

**Backend** (`routers/search.py`) :
- Exposer une **pertinence ABSOLUE** par résultat, **pas** le % normalisé-par-max.
  ⚠️ **Point clé** (cf. Session 2026-07-02) : le score affiché est normalisé par le meilleur du lot →
  le top vaut toujours ~100 %. Les **tranches doivent s'appuyer sur le cosinus brut** (`1 - distance`).
- Mapper cosinus → tranche. **Recoupe** `docs/plan-recherche-pertinence-seuil.md` (gate `0.72/0.60`) —
  idéalement livrer les deux ensemble (même normalisation).

**Frontend** (`GEDPage` / `AllDocumentsView`) :
- Nouveau **« Grouper par : Pertinence »** (à côté de Aucun/Extension/Catégorie/Tag).
- Sections **repliables** (réutilise `CollapsibleSection`), état de repli **persistant** (localStorage) :
  1. **📚 Livres (wiki)** — `categorie = 'livre'`, épinglée en tête (visible aussi hors recherche).
  2. 🟢 **100–80 %** · 🟡 **80–50 %** · 🟠 **50–30 %** · 🔴 **30–0 %** (bornes validées par l'utilisateur).
  3. **📄 Tous les fichiers** — vue à plat actuelle.

**Risques** : calibration des bornes de tranche sur le cosinus absolu (à valider sur le corpus NAS réel).

---

## Transverse

- Chaque livraison = **rebuild images + redéploiement** (Proxmox : `docker compose pull && up -d`).
- Prérequis : **BookStack configuré** (`bookstack_url` + token) — déjà en place (`wiki.agesti.fr`).
- Tests : pytest (backend wiki/index), vitest (composants GED groupés).
