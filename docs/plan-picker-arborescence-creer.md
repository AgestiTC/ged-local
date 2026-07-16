# Plan — Créer › ② « Parcourir » : arborescence de dossiers au lieu de la liste plate

> **Statut : ✅ LIVRÉ (16/07/2026).** Backend `GET /documents/tree` (+ `flat=true`) dans
> `backend/routers/documents.py` ; front `frontend/src/components/files/IndexedDocsTree.tsx`
> monté dans `ReportsPage`. Testé sur le corpus NAS (56 k docs). Reste optionnel : shift-clic
> de plage, mémorisation des nœuds dépliés (cf. §5). Plan initial ci-dessous.
>
> Répond au retour utilisateur 16/07/2026 :
> « Dans Créer › ② Parcourir, mets l'**arborescence** (comme Paramètres › Dossiers indexés › Gérer)
> à la place de la liste plate "9197 docs". »
>
> Lié à : ROADMAP → *Session 2026-06-27* « Rapports — refonte en parcours guidé » (Étape ② picker) ·
> `[ref] Gestion des dossiers indexés`.

---

## 1. Le besoin

L'étape ② de la page **Créer** (onglet **Parcourir**) affiche aujourd'hui une **liste plate** de
documents : « 100 sur 9197 doc(s) », les 100 premiers seulement, sans structure. Impossible de se
repérer dans les milliers de fichiers du NAS ni de sélectionner « tout un dossier ».

**Comportement voulu :** un **arbre de dossiers** (source → dossier parent déplié → sous-dossiers
pliés) **exactement comme** `Paramètres › Dossiers indexés › Gérer`, mais dont les **feuilles sont les
fichiers**, chacun **cochable** pour l'ajouter à la sélection du rapport (au lieu de « retirer de
l'index » comme dans Paramètres).

---

## 2. L'existant (ce qu'on réutilise)

| Élément | Fichier | Rôle |
|---|---|---|
| Picker plat actuel | `frontend/src/components/files/FileExplorer.tsx` | monté dans l'onglet « Parcourir » de `ReportsPage` (`<FileExplorer />`, l.109) ; sélection via `documentStore.selectedIds` (toggle, selectMany, selectAll, shift-clic) |
| Arbre de dossiers | `frontend/src/components/ged/IndexedFolders.tsx` | rend l'arbre `IndexedTree` (dossiers + compteurs, pliage, tout cocher/décocher) — **modèle visuel de référence** |
| Endpoint arbre | `backend/routers/sources.py` → `GET /sources/{id}/indexed` (l.307) | dérive un arbre **de dossiers** des `documents.chemin` d'une source ; renvoie `{racine, nb_documents, arbre:[{chemin, nom, nb, enfants}]}` — **PAS de fichiers-feuilles, PAS d'`id` de document** |
| Sélection rapport | `frontend/src/stores/documentStore.ts` | `selectedIds`, `toggleSelect`, `selectMany`, `selectAll`, `deselectAll`, `fetchDocuments({texte, q, page, page_size})` |

⚠️ **Écart clé** : `IndexedFolders` sélectionne des **chemins de dossiers** pour **désindexer** ;
le picker Créer sélectionne des **`id` de documents** pour **alimenter un rapport**. On réutilise
donc la **présentation** (arbre replié/déplié, compteurs, tout cocher) mais **pas** la logique de
sélection — et l'arbre doit **descendre jusqu'aux fichiers**.

---

## 3. Conception cible

### 3.1 Backend — arbre avec fichiers-feuilles (nouvel endpoint)

`GET /sources/{id}/indexed` s'arrête aux dossiers. On ajoute un endpoint dédié au picker, qui
descend jusqu'aux fichiers **porteurs de texte** (mêmes critères que le picker plat : `texte=true`,
exclut les médias catalogués) :

```
GET /documents/tree?texte=true&q=&source_id=&dossier=
```
- Sans `dossier` → renvoie les **dossiers de 1er niveau** (par source) + compteurs — **léger**.
- Avec `dossier=<chemin>` → renvoie le **contenu direct** de ce dossier : sous-dossiers (avec
  compteurs) **et** fichiers `{id, nom, extension, statut, taille_octets}`.
- `q` (optionnel, débounce) → **recherche transverse** sur le nom (comportement actuel conservé) :
  quand `q` est renseigné, on retombe sur une **liste plate de résultats** (chercher dans tous),
  pas sur l'arbre — la structure n'a de sens que pour parcourir, pas pour chercher.

> **Pourquoi lazy (par dossier) et pas tout d'un coup** : 9197 feuilles = arbre JSON lourd à
> construire et à monter à chaque ouverture de l'étape ②. Le chargement **au dépliage** (comme un
> explorateur) garde l'ouverture instantanée. `IndexedFolders` charge tout l'arbre *de dossiers*
> d'un coup (léger : pas de feuilles) — ici on ne matérialise les fichiers que du dossier ouvert.

**Réutilisation** : le calcul de préfixe/base par source (`_prefixe_source`) et le regroupement par
`chemin` de `indexed_tree` sont directement transposables ; on ajoute juste le niveau « fichiers du
dossier » (SELECT `id, nom, extension, statut, taille_octets WHERE chemin LIKE base+dossier+'/%'` sans
sous-dossier plus profond) et le filtre `texte=true`.

### 3.2 Frontend — nouveau composant `IndexedDocsTree`

Nouveau `frontend/src/components/files/IndexedDocsTree.tsx` (calqué sur `IndexedFolders` pour le
rendu), branché sur `documentStore` :
- **Nœud dossier** : chevron déplier/replier → **lazy-fetch** `GET /documents/tree?dossier=…` au
  premier dépliage (spinner inline), compteur de docs, **case « cocher le dossier »** = sélectionne
  tous les fichiers **déjà chargés** du dossier (option : « cocher tout le dossier » déclenche le
  fetch récursif — à cadrer, cf. §5).
- **Nœud fichier** (feuille) : `StatutDot` + nom + extension/taille + **case à cocher** → `toggleSelect(id)`.
  **Shift-clic** = plage (réutilise `selectMany` sur les feuilles visibles à plat).
- En-tête : compteur « N sélectionné(s) », **filtre** (bascule arbre ↔ liste plate de résultats via `q`),
  **tout sélectionner** (sur les feuilles chargées), rafraîchir.
- **Multi-sources** : niveau racine = les **sources** (comme le 2ᵉ écran « nas-mato TOM ») quand il y
  en a plusieurs ; une seule source → on déplie directement son 1er niveau.

### 3.3 Intégration `ReportsPage`

- `renderDocsStep` : remplacer `<div className="h-[320px]"><FileExplorer /></div>` par
  `<IndexedDocsTree />`. Aucun autre changement (la sélection continue de vivre dans `documentStore`,
  consommée telle quelle par la génération).
- **Option prudente** : garder un **toggle « Liste ⇄ Arbre »** (défaut Arbre) pour ne pas perdre la
  liste plate/recherche transverse que certains préféreront — coût quasi nul, `FileExplorer` reste en
  place. À trancher (§5).

---

## 4. Phasage

- [ ] **Phase 1 — Backend** : `GET /documents/tree` (dossiers 1er niveau + contenu d'un dossier :
      sous-dossiers + fichiers-feuilles avec `id`), filtre `texte=true`, `q` → liste plate.
      Réutilise `_prefixe_source` + logique de `indexed_tree`. Tests (dossier racine, contenu d'un
      dossier, `q` transverse, source vide).
- [ ] **Phase 2 — Frontend** : `IndexedDocsTree` (lazy-fetch au dépliage, feuilles cochables →
      `documentStore`, shift-clic, tout cocher dossier, filtre ↔ liste). Remplace `<FileExplorer />`
      dans `renderDocsStep`.
- [ ] **Phase 3 — Finitions** : « cocher tout un dossier » (récursif, avec compteur), mémorisation
      des nœuds dépliés, éventuel toggle Liste ⇄ Arbre, vérif perf sur le vrai NAS (56 k docs).

---

## 5. Décisions à confirmer (avant de coder)

1. **Case « dossier »** : cocher un dossier = cocher seulement les fichiers **chargés**, ou
   **récursif** (tout le sous-arbre, quitte à fetch) ? → *reco : récursif avec compteur* (« 1046
   fichiers seront cochés »), sinon l'utilisateur croit avoir tout pris.
2. **Garder la liste plate** en option (toggle Liste ⇄ Arbre) ou **remplacer** franchement ? →
   *reco : toggle, défaut Arbre* (la recherche transverse plate reste utile).
3. **Niveau racine multi-sources** : afficher les sources même s'il n'y en a qu'une (cohérence avec
   Paramètres) ou déplier directement l'unique source ? → *reco : déplier si une seule source*.

## 6. Garde-fous / non-régressions

- La sélection reste dans `documentStore.selectedIds` → **aucun** changement du flux de génération
  (rapport/template/classement/comparatif) ni de l'onglet **Assistant IA**.
- 100 % local, lecture seule : l'arbre **dérive des `documents` déjà indexés** (aucun accès NAS,
  aucune écriture) — comme `IndexedFolders`.
- Lazy-load par dossier → pas de régression de perf à l'ouverture de l'étape ② sur gros corpus.
