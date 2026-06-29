# PLAN — Intégration BookStack (« Créer un tuto dans le wiki »)

> Roadmap de la fonctionnalité de publication de tutos sur le wiki **BookStack**
> depuis Matothèque. Document de pilotage — l'étude détaillée (architecture, fichiers,
> risques) est dans [`docs/faisabilite-bookstack.md`](docs/faisabilite-bookstack.md).

**Statut global : MVP livré et vérifié** ✅ — Date : 2026-06-29

---

## 1. Objectif

Permettre, depuis Matothèque, de **publier un contenu (rapport généré ou document
indexé) en page « tuto »** sur le wiki BookStack (`https://wiki.agesti.fr`), via son
API REST, avec gestion propre des révisions et de l'index de recherche.

---

## 2. Contexte technique (validé)

- API BookStack : `Authorization: Token <id>:<secret>`, endpoints
  `GET /api/books`, `GET /api/chapters`, `POST /api/pages` (`{book_id|chapter_id, name, markdown}`).
- Le wiki est **100 % markdown** → pas de conversion nécessaire.
- Matothèque dispose déjà de toute la plomberie : `httpx`+`tenacity`, chiffrement
  Fernet (`crypto.py`), config runtime (`runtime_config.py`), pattern routers, axios.

---

## 3. Lot 1 — MVP  ✅ FAIT

### Backend
- [x] `config.py` — `bookstack_url`, `bookstack_token_id`, `bookstack_token_secret`, `bookstack_timeout_ms`
- [x] `services/runtime_config.py` — clés dans `_DEFAULTS` + `SECRET_KEYS`
- [x] `services/bookstack_service.py` — `check_health`, `list_books`, `list_chapters`, `create_page`, `update_page`, `page_url` (secret déchiffré Fernet)
- [x] `routers/bookstack.py` — `GET /api/bookstack/targets`, `POST /api/bookstack/publish` (markdown direct **ou** `document_id`)
- [x] `routers/system.py` — `ConfigUpdate` étendu ; secret **chiffré à l'écriture** + **masqué à la lecture** ; `bookstack` dans statut + test de connexion
- [x] `main.py` — router monté

### Frontend
- [x] `api/index.ts` — `bookstackApi` (`targets`, `publish`) + types ; `testService` accepte `bookstack`
- [x] `components/common/PublishBookStackModal.tsx` — modale (titre + livre/chapitre + lien page créée)
- [x] `pages/SettingsPage.tsx` — section **« Wiki BookStack »** (URL + Token ID + Secret + Tester + Enregistrer)
- [x] `components/reports/ReportPreview.tsx` — bouton **« Wiki »** → publie le rapport généré

### Vérifications
- [x] Import backend OK + routes enregistrées
- [x] Test de connexion **live** : `POST /api/system/test/bookstack` → `ok: true` (sans persister le secret)
- [x] Frontend `tsc --noEmit` OK
- [x] Frontend `npm run build` (tsc + vite) OK

> ⚠️ `npm run lint` échoue dans le conteneur (ESLint ne trouve pas sa config, cherche
> dans `/app/e2e`) — **quirk d'environnement préexistant**, sans rapport avec ce lot.

---

## 4. Activation — ✅ FAIT & VALIDÉ (2026-06-29)

1. [x] **Compte de service** créé : `Support-matotheque` (support@agesti.fr), rôle **Editor**.
2. [x] Permission API : rôle dédié **« API Matotheque »** (uniquement `access-api`) ajouté
       au compte (rôles cumulés Editor + API). Évite d'ouvrir l'API à tous les éditeurs.
3. [x] **Jeton d'API** généré sur ce compte (token_id `9NPupHASBChayfGrR2jQcpHXry8vNxrL`).
4. [x] Matothèque → **Réglages → Wiki BookStack** : URL + jeton saisis et **enregistrés**
       (secret chiffré en base, masqué à la lecture). Statut : `ok: true, configure: true`.
5. [x] **Validation bout-en-bout** :
       - `GET /api/bookstack/targets` → 19 livres listés ;
       - `POST /api/bookstack/publish` → page créée (id 124) **au nom de Support-matotheque** ;
       - page de test **supprimée** (HTTP 204) — wiki propre.

➡️ **Lot 1 : terminé et validé.**

---

## 5. Ciblage avancé — Lot 1a & 1b (à faire)

> Remontée utilisateur (2026-06-29) : aujourd'hui on ne peut que **choisir** un livre
> ou un chapitre **déjà existant**. Il faut pouvoir **créer** la cible à la volée et/ou
> laisser **Matothèque proposer** un nom et un emplacement.

### Lot 1a — Choisir OU créer le livre / chapitre (+ suggestion Matothèque)  ✅ FAIT (2026-06-29)

**Remarque (limite initiale)** : la modale de publication ne listait que des livres/chapitres
existants ; aucune création à la volée, aucune proposition automatique de nom/position.

**Résolution (faisable — API disponible)** :
- Créer un livre : `POST /api/books` (`name` requis).
- Créer un chapitre : `POST /api/chapters` (`book_id` + `name` requis).
- Proposition Matothèque : réutiliser le LLM (Ollama) — proposer un **titre** et un
  **emplacement** par rapprochement thématique avec la liste des livres/chapitres existants.

**Plan d'action** :
- [x] Backend : `bookstack_service.create_book()` / `create_chapter()` + helpers idempotents
      `ensure_book()` / `ensure_chapter()` ; `POST /api/bookstack/publish` accepte désormais
      `new_book` / `new_chapter` (nom) en plus de `book_id` / `chapter_id`.
- [x] Backend : endpoint `POST /api/bookstack/suggest` → `{ titre, book_id|nouveau_livre, chapitre, raison }`
      à partir du contenu (LLM, sortie JSON ; id halluciné ignoré).
- [x] Frontend : modale avec options **« ➕ Nouveau livre »** / **« ➕ Nouveau chapitre »**
      (+ livre parent) + bouton **« Proposer »** qui pré-remplit titre + cible.
- [x] Idempotence : `ensure_book`/`ensure_chapter` réutilisent un livre/chapitre de même nom
      (comparaison insensible casse/espaces) avant de créer.

**Bonus (décision user 2026-06-29) — Module « Wiki » à part entière** :
- [x] Onglet **Wiki** dans la nav (à côté de Rapports / GED / Doublons / Réorganiser).
- [x] `pages/WikiPage.tsx` : arborescence du wiki (livres → chapitres) à gauche + composer
      (titre + Markdown, choisir/créer l'emplacement, « Proposer », « Publier ») à droite.
      Réutilise intégralement le moteur Lot 1a (`bookstackApi`). La modale reste le raccourci
      depuis les rapports.

**Vérifs** : `python -m py_compile` backend OK ; frontend `tsc --noEmit` OK.

### Lot 1c — Atelier de création unifié : Wiki = destination de l'étape ① (refonte UX, décision user 29/06)

> **Remontée user** : « la page WIKI doit intégrer l'IA pour l'aide à la création des documents ;
> j'imaginais une zone de prompt et une vue → en fait WIKI est un **bouton à mettre en étape ①
> dans Rapport** (et il faudra **changer le nom** de la page) ».

**Constat (audit)** : la page « Rapports » **est déjà un parcours guidé (stepper)** :
① Que produire · ② Documents · ③ Instructions · ④ Générer, avec un panneau **Résultat** à droite.
Elle produit en réalité **plusieurs sorties** (rapport rédigé, modèle rempli, classement, comparatif).
→ Le nom « Rapports » est **trop étroit**, et le **Wiki n'est pas une page à part** : c'est une **5ᵉ
destination** de ce même atelier. La page standalone `WikiPage` créée en 1a doit donc **fusionner**
dans cet atelier.

**Cible (maquette validée par le user)** — l'étape ① devient une **barre horizontale pleine largeur**
de destinations ; les étapes ②③④ restent en colonne gauche ; **Résultat** occupe toute la hauteur à droite :

```
┌──────────────────────────────────────────────────────────────────────┐
│ ① Que produire :  [Rapport] [Modèle] [Classement] [Comparatif] [📖 Wiki] │  ← pleine largeur
├───────────────────────────────────┬──────────────────────────────────┤
│ ② Documents (sources, optionnel)   │                                  │
│    [ Parcourir | Assistant IA ]    │            RÉSULTAT               │
├───────────────────────────────────┤   aperçu · stream · doc éditable  │
│ ③ Instructions (zone de prompt)    │   + barre d'actions               │
│    + Modèle IA (réglage avancé)    │   (Export · **Publier sur wiki**) │
├───────────────────────────────────┤                                  │
│ ④ Générer                          │                                  │
└───────────────────────────────────┴──────────────────────────────────┘
```

**Comportement quand destination = « 📖 Tuto wiki »** :
- ② Documents = **sources optionnelles** (on peut rédiger un tuto from scratch ou à partir de docs indexés).
- ③ Instructions = **la zone de prompt** demandée (« Rédige un tuto d'installation de X… ») → l'IA **rédige**
  le contenu Markdown (réutilise le pipeline de génération + streaming SSE existant).
- **Résultat** = le Markdown généré, **éditable** (la « vue »), avec l'action **« Publier sur le wiki »**
  → ouvre le flux Lot 1a (choisir/créer livre·chapitre + bouton « Proposer » titre/emplacement).

**Plan d'action** — ✅ **Livré le 2026-06-29** (décisions user : nom **« Créer »** ; Wiki **gardé en consultation**) :
- [x] **Renommé** l'onglet « Rapports » → **« Créer »** (nav `Sidebar`, icône `PenSquare` ; `/` reste l'index).
      *(MAJ CLAUDE.md / README : reporté — la marque interne « Rapports » reste dans la doc.)*
- [x] **Étape ① en barre horizontale pleine largeur** (au-dessus des 2 colonnes) ; destination **`wiki`**
      ajoutée à `OutputMode` (icône 📖 `BookOpen`, libellé « Tuto wiki »).
- [x] **Mode `wiki`** dans `reportStore.outputMode` (type `OutputMode` étendu) ; génération via le pipeline
      Ollama existant (prompt → Markdown, streaming SSE) ; ② Documents **optionnel** ; backend
      `/generate/report` accepte désormais **`document_ids` vide** (tuto « from scratch »).
- [x] **ResultPanel / ReportPreview** : mode wiki → rendu Markdown **éditable** (3ᵉ onglet « Éditer »,
      action store `editRapport`) + bouton **« Publier sur le wiki »** (réutilise `PublishBookStackModal`).
- [x] **`WikiPage` conservée** comme onglet **« Wiki » en consultation** (vue arbre livres→chapitres→pages) ;
      la composition est désormais possible aussi depuis l'atelier (destination 📖). *(décision : garder)*
- [x] Vérifs : `tsc --noEmit` OK ; backend `ast.parse` OK. **Parcours bout-en-bout** (générer → publier) :
      à valider en usage.

### Lot 1b — Choisir OU créer l'étagère (+ rattachement, + suggestion)

**Remarque** : aucune gestion des **étagères** (shelves), le niveau au-dessus des livres.
Impossible de choisir/créer une étagère ni d'y rattacher le livre publié.

**Résolution (faisable — API disponible)** :
- Lister : `GET /api/shelves` · Créer : `POST /api/shelves` (avec `books: [ids]`).
- Rattacher un livre à une étagère existante : `PUT /api/shelves/{id}` avec la **liste
  complète** des livres (lire l'existant → ajouter → renvoyer ; l'API **remplace** la liste).
- ⚠️ Modèle BookStack : un livre n'a pas de `shelf_id` ; l'appartenance est portée **côté
  étagère** (un livre peut être sur 0..n étagères).
- Proposition Matothèque : suggérer l'étagère par rapprochement thématique (même logique).

**Plan d'action** :
- [ ] Backend : `list_shelves()`, `create_shelf()`, `attach_book_to_shelf(shelf_id, book_id)`
      (lecture-modification-écriture de la liste `books`).
- [ ] Backend : exposer les étagères dans `/targets` (`shelves`) et accepter `shelf_id` /
      `new_shelf` dans `/publish`.
- [ ] Frontend : ajouter un 3ᵉ niveau **« Étagère »** (existante / + nouvelle) au-dessus du livre.
- [ ] Tests : création + rattachement + idempotence.

---

## 6. Lot 2 — Améliorations (backlog, hors MVP)

- [ ] Bouton **« Publier sur le wiki »** aussi depuis la **fiche document** (GED),
      pas seulement depuis les rapports.
- [ ] Table **`publications`** (document_id, service, external_id, external_url,
      published_at) pour **tracer** et permettre la **republication / mise à jour**
      (`update_page`) au lieu de recréer.
- [ ] **Pré-formatage** du contenu publié selon le gabarit « Modèle de tuto » du wiki
      (titre, bloc Prérequis, sections numérotées) — voir conventions de style.
- [ ] **Tests** pytest pour `bookstack_service` (health/configured/page_url) + test
      d'intégration du router (httpx mické).
- [ ] Choix d'un **livre par défaut** mémorisé dans la config (cible récurrente).
- [ ] Gestion des **doublons de titre** (avertir si une page du même nom existe déjà).

---

## 6. Risques & décisions

| Sujet | Décision |
|---|---|
| Jeton lié à un utilisateur | Compte de service dédié (Lot activation) |
| Expiration du jeton (403 « expired ») | Date lointaine + bouton « Tester » dans Réglages |
| Secret en base | Chiffré Fernet (`enc::`) + masqué dans l'API de config |
| Matothèque sans authentification | Accès réseau restreint (inchangé) |
| Qualité du markdown | MVP = contenu tel quel ; gabarit en Lot 2 |
