# Plan — suite de la ROADMAP (établi 23/07, après le sprint génération/observabilité)

> Consolidation et **priorisation** de ce qui reste ouvert dans `ROADMAP.md`, regroupé par thème,
> avec effort estimé, dépendances et valeur. Objectif : décider les prochains sprints sans relire
> toute la ROADMAP. Rien ici n'est codé sans validation.

Repères d'effort : **S** ≈ ½–1 j · **M** ≈ 1–2 j · **L** ≈ 3 j+ · **XL** = épic multi-sprints.

---

## 🎯 Sprint recommandé (N+1) — « Finir ce qui est commencé + irritants »

Objectif : boucler les chantiers ouverts et éliminer les bugs vécus. Fort ratio valeur/effort,
zéro dépendance externe. **~1 sprint.**

| # | Item | Effort | Pourquoi maintenant |
|---|------|--------|---------------------|
| 1 | **🔴 « Annuler » inopérant sur un job en cours** (②bis) | M | Bug de prod réel : `_cancel_requested` est un `set` en mémoire de l'API, mais le job tourne dans le **worker** séparé → l'annulation ne traverse pas. Fix : drapeau **en base** (`annulation_demandee` sur `jobs`, lu par `ctx.cancelled`). |
| 2 | **🐞 % de progression faux (widget Tâches)** (⑥) | S | Affiche `100 %` avec `40047/34290`. Fix : borne `min(fait,total)` + progression **par job** (pas par source) + recompter le total en fin d'énumération. |
| 3 | **File FIFO — jobs fantômes** (②ter) | S | On a purgé à la main aujourd'hui ; le garde-fou manque. Fix : **âge max** d'un `pending` + **compteur de reprises** (3 échecs → `failed`). |
| 4 | **Navigation persistante en vue détail Paramètres** (⑥) | S | Le fil d'ariane + la recherche disparaissent quand on ouvre une section. Fix : sortir l'en-tête du tableau de bord, le rendre aussi en vue détail. |
| 5 | **Fiabilité enrichissement** : ne pas marquer `enriched` si la méta a échoué | S | Reliquat connu (~51 docs `enriched` sans `metadonnees_ia`). |
| 6 | **③ « Ré-analyser » : tracer l'erreur** | S | Débloqué par les logs (1.22.0) : ajouter le log d'échec manquant sur `analyze-batch` et vérifier le vrai message. |

---

## 🔭 Chantier — Observabilité Phase 2 — ✅ LIVRÉ 23/07 (v1.27.0)

**Effort M–L.** La Phase 1 (prod plus aveugle) est faite. Phase 2 = **traçabilité de bout en bout**.

- Table **`audit_events`** (acteur, action, cible, statut, `duree_ms`, message, `detail` JSONB,
  **`correlation_id`**) reliant **UI → API → worker** pour une même opération.
- Onglets **Activité** (métier, lisible) et **Debug** (technique) dans la page Logs.
- Valeur : diagnostiquer un incident en suivant un `correlation_id`, mesurer les durées réelles.

---

## 🔄 Chantier — Indexation continue Phase 4 — ✅ LIVRÉ 23/07 (v1.28.0)

**Effort M.** Phases 1–3 livrées (synchro manuelle + auto). Reste :

- **Purge assistée des `absent`** : écran listant les documents passés `statut='absent'` (disparus du
  NAS) → l'utilisateur confirme la suppression de l'index (jamais d'office). Réconciliation propre.
- Rendre le **walk SMB annulable/borné** (recoupe le bug « Annuler » ci-dessus) : l'énumération
  initiale reste non interruptible.

---

## 🧠 Chantier — Génération : « meilleure approche » cold-load (suite du sprint)

**Effort S–M.** Le prewarm (44→9 Go via ministral) règle 90 % du problème. Pistes d'amélioration
consignées ([[cold-load-modele-rapport]]) :

- **Warm à la demande** depuis l'UI (bouton « préparer le modèle » avant de rédiger) au lieu d'un
  prewarm permanent qui occupe la VRAM.
- **Relever `proxy_read_timeout`** NPMplus pour que même un cold-load ponctuel n'échoue jamais.
- Optionnel : **emojis couleur** dans l'export PDF (ajouter une police emoji au conteneur).

---

## 🚀 Épics (features majeures — à cadencer selon besoin réel)

### E1 — Connecteurs cloud (lecture)
- **✅ Google Drive LIVRÉ 23/07 (v1.31.x)** : OAuth2 `drive.readonly`, un compte = une Source,
  export des docs Google natifs, indexation durable. Testé de bout en bout (1660 fichiers indexés).
  Pièges rencontrés : cache config multi-process (reload OAuth), secret à déchiffrer avant envoi.
- Reste (à la demande) : **WebDAV générique** (large couverture NAS/kDrive/Nextcloud), puis
  OneDrive/Dropbox/Box. Digiposte = à part (API partenaire La Poste).

### E2 — Indexation dynamique automatique — **L**
Détecter automatiquement les ajouts/modifs sans clic. Décision déjà prise : **PAS n8n pour le SMB**
(ne watch pas nativement). Notre synchro auto (déjà livrée) couvre le périodique ; reste éventuellement
un `FolderWatcher` backend pour les **sources locales** (temps réel). Largement adressé par le sprint 23/07.

### E3 — Lier des documents entre eux (BC ↔ facture) — **L**
Hybride : détection de référence (n° de commande) + suggestions à valider. Demande utilisateur 01/07.

### E4 — Doublons avancés — **M–L**
Dédup **3 passes** (taille → hash 4 Ko → hash complet) · **quasi-doublons** sémantiques (seuil réglable) ·
**miniatures** de comparaison · **photos floues** (variance du Laplacien). Base déjà présente.

### E5 — Connecteurs « appareils » — **M chacun, à la demande**
**reMarkable** · **openplaud** (transcription audio via Voxtral) · **scanner Epson** (dossier de scan → GED).

### E6 — 📱 Responsive / smartphone — **L**
Menu burger sous un seuil de largeur, marges auto, audit page par page. **Demande utilisateur 23/07.**
Plan déjà cadré dans la ROADMAP (section « Réflexion pour plus tard »).

### E7 — Perf recherche sémantique (~20 s sur 65 k docs) — **L, technique**
Dominé par le scan pgvector (4096 d = pas d'index ANN sans ré-embed ≤2000 d Matryoshka). Chantier
d'optimisation à part entière ; à sortir seulement si la lenteur devient bloquante à l'usage.

---

## 📌 Séquencement recommandé

1. **Sprint N+1** (finitions + irritants ci-dessus) — rapide, zéro dépendance, remet tout au propre.
2. **Observabilité Phase 2** OU **Indexation continue Phase 4** — selon l'appétit (diag vs propreté de l'index).
3. **Une grande direction produit** au choix : **E6 responsive** (confort quotidien) · **E1 Google Drive**
   (si l'app OAuth est prête) · **E3 liens BC↔facture** (valeur métier).
4. Le reste (E4/E5/E7) à la demande, selon l'usage réel.

**À décider par l'utilisateur** : (a) valide-t-on le Sprint N+1 tel quel ? (b) quelle grande direction
produit vise-t-on ensuite (responsive / Google Drive / liens documents) ?
