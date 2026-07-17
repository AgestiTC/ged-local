# Plan de correction — « Modèle IA (mixtral) » casse la génération par défaut

> **Origine** : retour user 17/07 (capture étapes ③/④ de la page « Créer »).
> **Gravité** : 🔴 **bloquant** — une fonction principale de l'appli échoue sur une page fraîche.
> **Statut** : plan (non appliqué). Trace : ROADMAP § « Session 2026-07-17 — Q&R : la page Créer ».

---

## 1. Le bug, en une chaîne

| # | Fichier | Ce qui se passe |
|---|---------|-----------------|
| 1 | `frontend/src/stores/reportStore.ts:55` | état initial **codé en dur** : `model: 'mixtral:latest'` |
| 2 | `frontend/src/pages/ReportsPage.tsx:158` | le libellé affiche cette valeur → **« Modèle IA (mixtral) »** |
| 3 | `frontend/src/pages/ReportsPage.tsx:161` | `{showModele && <ModelSelector/>}` — or **`ModelSelector` SAIT réparer** (l.29-31 : modèle absent → bascule sur le défaut)… mais il n'est **monté que si l'utilisateur déplie**, **replié par défaut** → **la réparation ne s'exécute jamais** |
| 4 | `backend/routers/generate.py:204` | `model = request.model or runtime_config.model_for("rapport")` → la valeur du front **écrase la config** |

**Vérifié en prod le 17/07** : `default_model = llama3.1:latest`, usage `rapport` = `Qwen3.6-35B:latest`,
et **mixtral absent** des modèles installés (Qwen3.6-35B · Qwythos-9B · llama3.1 · ministral-3 ·
nomic-embed-text · qwen2.5vl · qwen3-embedding).

→ **Page fraîche + « Générer » sans toucher au réglage = appel Ollama sur un modèle supprimé.**
Contournement actuel (indevinable) : **déplier « Modèle IA »**, ce qui répare le store au passage.

> **Leçon de conception** : un correctif d'auto-réparation placé dans un composant **monté
> conditionnellement** ne s'exécute pas dans le cas qu'il est censé couvrir. La résolution du défaut
> doit vivre **au niveau de la page**, pas d'un panneau repliable.

---

## 2. Phase 1 — Débloquer (minimal, sûr, 1 ligne)

**`reportStore.ts:55`** : `model: 'mixtral:latest'` → **`model: ''`**.

**Pourquoi ça suffit** : `''` est *falsy* → `generate.py:204` (`request.model or model_for("rapport")`)
applique alors **la config de l'utilisateur** = `Qwen3.6-35B:latest`. Le front cesse d'imposer un modèle
qu'il n'a aucune raison de connaître.

**Principe** : le front ne doit **jamais** figer un nom de modèle. La source de vérité est la config
backend (`usage_models` / `default_model`), déjà éditable dans Paramètres.

> **✅ La sémantique cible EXISTE DÉJÀ dans le produit** (capture user 17/07, Paramètres → Services &
> modèles IA) : *« MODÈLE PAR USAGE — routage dynamique (**« Auto » = défaut**) »*. Les sélecteurs par
> usage proposent **Auto** = « ne rien imposer, laisser le backend router ».
> **`model: ''` dans le store = exactement ce "Auto"** — on ne crée donc pas un concept nouveau, on
> **réaligne la page « Créer » sur une convention déjà établie dans Paramètres**.
>
> Config confirmée par la capture : `Rapports / raisonnement` → **`Qwen3.6-35B:latest`** ·
> `Enrichissement` → `llama3.1:latest` · `Embeddings` → `qwen3-embedding:8b` · `Vision` → `qwen2.5vl:7b` ·
> `Résumé de modèle` → `llama3.1:latest` · **Modèle par défaut** → `llama3.1:latest` (7 modèles installés).
> **Aucun de ces réglages ne mentionne mixtral** → l'écart vient bien du seul front.
>
> **Conséquence pour la Phase 2** : le libellé replié devrait afficher **« Modèle IA (Auto : Qwen3.6-35B) »**
> — même vocabulaire que Paramètres. Et le sélecteur de la page « Créer » gagnerait une **option « Auto »**
> explicite en tête de liste (valeur `''`), pour qu'on puisse **revenir** au routage par usage après avoir
> choisi un modèle à la main. Aujourd'hui c'est impossible : tout choix est définitif.

**⚠️ Effet de bord à traiter** : le libellé `model.split(':')[0]` afficherait `()` → Phase 2.

**Tests à mettre à jour** (ils figent l'ancienne valeur — ils **échoueront**, c'est normal et voulu) :
`__tests__/stores/reportStore.test.ts` (4 occurrences) · `__tests__/hooks/useReport.test.ts` (1).

## 3. Phase 2 — Que l'UI dise la vérité

Résoudre le modèle **au montage de la PAGE**, pas à l'ouverture du sélecteur.

- Extraire la logique de `ModelSelector.charger()` (l.22-37) dans un **hook partagé** `useModeles()`
  (ou une action de store `resoudreModeleDefaut()`), appelé par `ReportsPage` **inconditionnellement**.
- `ModelSelector` consomme le même hook → **une seule** source de vérité, plus de duplication.
- Libellé : tant que l'utilisateur n'a rien choisi → **« Modèle IA (défaut : Qwen3.6-35B) »**
  (et non `()`), pour que le réglage replié reste honnête.
- Conserver l'auto-correction : si le modèle **choisi** disparaît d'Ollama → rebascule + informe.

## 4. Phase 3 — Défense en profondeur côté backend

Aujourd'hui `/generate` fait confiance au modèle envoyé. Un client (ou un vieux `localStorage`
persistant !) peut encore demander un modèle supprimé.

- Brancher **`runtime_config.model_candidates("rapport")`** sur `/generate` — le fallback
  « même famille » **existe déjà**, est éprouvé (`extraction.py:275` vision, `:577` enrichissement)
  et **écarte les modèles non installés**. Il n'est simplement pas utilisé ici.
- **⚠️ Spécificité de `/generate` : c'est du STREAMING (SSE).** Le motif « try/except → modèle suivant »
  d'`extraction.py` **ne transpose pas** : une fois le flux commencé, on ne peut pas rejouer proprement.
  → **Valider AVANT d'ouvrir le flux** : si le modèle demandé n'est pas dans les candidats installés,
  prendre le 1er candidat **et le signaler** (log + info à l'utilisateur), plutôt que d'échouer.
- Si **aucun** modèle texte installé → erreur **explicite** (« Aucun modèle texte disponible dans
  Ollama »), pas un 502 opaque.
- Loguer systématiquement le **modèle réellement utilisé** (recoupe le chantier observabilité :
  aujourd'hui un échec Ollama sur modèle absent ne laisserait **aucune trace** en prod).

## 5. Phase 4 — Purger les `mixtral` résiduels

Le nom traîne encore et re-piégera le prochain lecteur :

| Fichier | Ligne | Quoi |
|---------|-------|------|
| `frontend/src/components/reports/GenerationEstimate.tsx` | 14 | `mixtral: 32000` (fenêtre de contexte) |
| `frontend/src/components/reports/GenerationEstimate.tsx` | 42 | `const lourd = model.startsWith('mixtral')` (heuristique de lenteur) |
| `frontend/src/pages/SettingsPage.tsx` | 923 | placeholder `« Ex: mixtral:latest »` |
| `backend/routers/generate.py` | 46 | docstring « défaut : mixtral » (**faux**) |
| `backend/services/report_generator.py` | 44 | idem |

→ Les fenêtres de contexte devraient venir des **modèles installés** (Ollama expose la taille), pas
d'une table figée. À défaut : basculer la table sur les modèles réellement présents et retirer
l'heuristique `startsWith('mixtral')`.

## 6. Vérification (ne pas se contenter du typecheck)

1. **Page fraîche** (vider le `localStorage` du store) → étape ③ affiche **« défaut : Qwen3.6-35B »**, pas `mixtral`.
2. **Générer sans jamais déplier « Modèle IA »** → doit produire un rapport. **C'est LE test du bug.**
3. Vérifier le **modèle réellement appelé** (log backend / `/api/jobs`) = `Qwen3.6-35B:latest`.
4. Choisir explicitement un autre modèle → il est bien respecté.
5. Simuler un modèle disparu (choisir puis le supprimer d'Ollama) → fallback propre + message.
6. `npm test` : les tests figeant `mixtral:latest` doivent être mis à jour (cf. Phase 1).

## 7. Ordre recommandé

**Phase 1** (débloque tout de suite, 1 ligne + tests) → **Phase 2** (l'UI cesse de mentir) →
**Phase 4** (purge, sans risque) → **Phase 3** (robustesse backend, la plus délicate à cause du SSE).
