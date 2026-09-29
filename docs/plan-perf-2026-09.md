# Plan d'optimisation des performances — Matothèque v1.123.0 (29/09/2026)

Établi à partir de **mesures** (relevés du 29/09/2026, en lecture seule sur la prod), pas
d'intuitions. Chaque étape donne : le fait mesuré, l'objectif, la vérification, les agents.

> ⚠️ `/ecc:orchestrate custom` n'existe plus dans ECC 2.2.2. Les chaînes d'agents ci-dessous
> sont donc lancées par Claude (comme pour l'audit du 28/09), pas collées en commandes.

## Ce que les mesures disent

| Relevé | Valeur | Lecture |
|---|---|---|
| API mesurée **dans** le conteneur backend | 3–34 ms | l'application est rapide |
| même route depuis le LXC (`127.0.0.1:8008` et `192.168.42.83:8008`) | ~3 ms | ni l'appli ni le proxy en cause |
| `GET /api/version` depuis PC-GAME | ~50 ms **ou** ~540 ms, en alternance | temps ajouté entre le PC et le LXC |
| requêtes lentes depuis PC-GAME | connexion TCP 0,27 s, 1ᵉʳ octet 0,54 s | le temps se perd **avant** l'appli |
| `ping` PC-GAME → 192.168.42.83 | 195–274 ms, intermittent | anormal sur un LAN (< 1 ms attendu) |
| charge du LXC (2 cœurs) | 3 à 5 | processeur souvent saturé |
| swap du LXC | 1,8 Go / 2 Go | pression mémoire |
| `embeddings` | 81 040 lignes, 2,5 Go | taille normale pour du 4096d |
| stats Postgres `embeddings` | n_live_tup = 2 719, **aucun autovacuum/analyze** | le planificateur se trompe d'un facteur 30 |
| `audit_events` | 92 749 lignes | à surveiller (rétention ?) |
| `/api/system/services` | 1,5–2 s | sondes de services lentes |
| build frontend | avertissement Vite « chunk > 500 Ko » | chargement initial alourdi |

## Résultats (29/09/2026)

- **Étape 1 — cause trouvée, côté PC-GAME.** Depuis le LXC, tout le LAN répond en < 0,4 ms
  (passerelle 0,24 ms, AIGUILLEUR 0,04 ms). Depuis PC-GAME, même la passerelle `.1` est à
  ~160–200 ms, et la boucle locale ou l'IP du PC restent à 0 ms. Le test décisif : **7 ms en
  moyenne en rafale, 199 ms avec une seconde d'écart**, donc la carte (Intel I226-V, pilote
  1.1.4.43 du 15/02/2024) s'endort entre deux paquets. Réglages en cause : ASPM PCIe
  « Économie d'énergie modérée » sur secteur, et « Suspension sélective » de la carte activée.
  Correctif = réglage du poste (non appliqué : il réinitialise la carte, qui sert aussi
  Ollama/Voxtral à l'AIGUILLEUR).
- **Étape 2 — faite, et constat corrigé.** Seul le compteur `n_live_tup` était faux (2 719) :
  l'estimation réellement utilisée par le planificateur (`reltuples`) était déjà à 73 220 pour
  81 040 lignes. Le « facteur 30 » était donc une mauvaise lecture de ma part. `ANALYZE` global
  joué (24 s) : estimations exactes (embeddings 81 040, documents 66 124). Gain réel : faible.
  Autovacuum actif, réglages par défaut.
- **Étape 4 — faite (v1.124.0).** Sondes mesurées une à une en prod : Tika 36 ms, Ollama
  441, n8n 738, ClamAV 111, BookStack 805, transcription 482 → ~2,6 s enchaînées. Passées en
  parallèle (`asyncio.gather`) : la réponse attend la plus lente (~0,8 s). Au passage, les
  sondes Ollama portent `X-AI-Project` (518 appels anonymes/nuit relevés par l'AIGUILLEUR).
- **Étape 5 — faite (v1.124.0).** Le bloc principal (568 Ko, 173 Ko gzip) contenait routeur,
  React, axios, rendu Markdown. Découpé en `vendor-react` / `vendor-markdown` / `vendor` :
  code propre à l'appli = 136 Ko (38 Ko gzip), seul à changer d'une version à l'autre
  (nginx sert `/assets/` en `immutable` 1 an). Plus d'avertissement Vite.
- **Étape 6 — faite (v1.125.0).** `Server-Timing: app;dur=…` sur chaque réponse (middleware
  `chronometre`, englobe `reglages_frais`) : Réseau › Timing montre la part serveur.
- **Étape 7 — faite (v1.125.0), durée à choisir.** 32 Mo en deux mois (~1 400 événements/jour,
  `enrich` et `analyze` à 90 %) : pas un problème de performance. Réglage
  `audit_retention_jours` (Journaux › Traçabilité › Conserver), défaut 0 = tout garder.
- **Étape 8 — FAITE en prod le 29/09 (v1.126.0).** Sauvegarde `matotheque-20260929-084141.dump`,
  `scripts/migrer-halfvec.sql` (DROP INDEX 45 s d'attente de verrou + ALTER 2 min 01), index
  HNSW `halfvec_cosine_ops` en CONCURRENTLY (1 min 23), redémarrage backend/worker/frontend.
  Table `embeddings` **2 508 → 1 256 Mo** (index 561 → 187 Mo), base 2,96 → ~1,7 Go. Recherche
  sémantique vérifiée : 70 résultats, index utilisé, aucune erreur au journal.
  Détail de l'évaluation préalable : pgvector 0.8.5 (halfvec disponible). Recherche
  exacte, top-10 pleine précision vs `halfvec` : **10/10 identiques** sur 20 requêtes 1024d et
  5 requêtes 4096d. Gain possible : `embedding` 1 267 → ~634 Mo, `embedding_small` 317 → ~158 Mo,
  index HNSW 561 → ~280 Mo, soit **~1 Go sur 2,5**. Coût : réécriture de la table (`ALTER
  COLUMN … TYPE halfvec`), reconstruction de l'index en `halfvec_cosine_ops`, requêtes à
  passer de `CAST(… AS vector)` à `halfvec`. Constat annexe : la colonne 4096d ne sert plus
  qu'au **repli** (index 1024d pas prêt) et un scan exact y coûte ~15 s par recherche.
- **Hors plan — modèle des rapports.** La prod envoyait les rapports à
  `qwen3.6-uncensored:35b-a3b-q4` (20,55 Gio pour 16 Gio de VRAM : 131 évictions de modèles par
  nuit selon l'AIGUILLEUR). Basculé sur `ministral-3:14b` (8,5 Gio) le 29/09 avec l'accord de
  l'utilisateur, via `PUT /api/system/config`.
- **Étape 3 — requalifiée.** 4,9 Go restent disponibles sur 6 : le swap plein contient des
  pages anciennes, pas une pression mémoire actuelle. Reste la charge (3,4–3,8 sur 2 cœurs).

## Étapes (dans l'ordre du gain attendu)

| # | Étape | Nature | Objectif | Agents |
|---|---|---|---|---|
| 1 | Réseau PC-GAME ↔ LXC | infra, lecture seule | ping < 2 ms, `/api/version` < 20 ms, plus d'alternance | `network-troubleshooter` |
| 2 | Statistiques Postgres | base | `n_live_tup` ≈ `count(*)` ; autovacuum actif | `database-reviewer` |
| 3 | Mémoire / processeur du LXC | infra (décision utilisateur) | swap < 25 %, charge < 2 | `homelab-architect` |
| 4 | `/api/system/services` | code | < 300 ms (sondes en parallèle, délais courts, cache bref) | `fastapi-reviewer` → `python-reviewer` |
| 5 | Bundle frontend | code | plus aucun chunk > 500 Ko (pages en `lazy()`, découpage des grosses dépendances) | `react-reviewer` → `performance-optimizer` |
| 6 | Chronométrage serveur (`Server-Timing`) | code | le navigateur distingue réseau et serveur, sans SSH | `fastapi-reviewer` |
| 7 | Rétention `audit_events` | base | politique de purge décidée et appliquée | `database-reviewer` |
| 8 | Stockage des vecteurs (`halfvec`) | évaluation | chiffrer le gain (~−50 % d'espace) **et** la qualité de recherche avant toute bascule | `database-reviewer` → `rag-pipeline-reviewer` |

### 1 — Réseau PC-GAME ↔ LXC (le plus rentable, à faire en premier)
Depuis le LXC tout répond en ~3 ms ; depuis PC-GAME, un appel sur deux coûte ~500 ms, dont
0,27 s rien que pour ouvrir la connexion. Pistes : économie d'énergie de la carte réseau de
PC-GAME, VPN ou filtre réseau actif sur le PC, pont réseau Proxmox, saturation de la carte
quand Ollama/Voxtral travaillent. **Aucune version à livrer** : c'est un diagnostic.
Tant que ce point n'est pas réglé, toute mesure de perf faite depuis PC-GAME est faussée.

### 2 — Statistiques Postgres
`ANALYZE` ponctuel, puis vérifier pourquoi l'autovacuum n'est jamais passé (paramètres du
conteneur `pgvector/pgvector:pg16`) ; ajouter un `ANALYZE embeddings` après les gros
remplissages (backfill Matryoshka). Vérification : `EXPLAIN` de la recherche sémantique
avant/après.

### 3 — Mémoire / processeur du LXC
Plusieurs applications partagent ce LXC (Matothèque, Foulée…). Choix à faire par
l'utilisateur : plus de RAM/cœurs au LXC, `swappiness`, ou répartition des services.

### 4 à 8
Rail habituel pour chacune : mesure avant, correctif, mesure après sur pile jetable
(`/verify`), tests, livraison (`/livrer`) et verdict de `verifier-deploiement.ps1`.

## Ce qu'on ne fera pas
- Optimiser le serveur à l'aveugle alors que le temps se perd sur le réseau.
- Changer le modèle d'embedding ou la dimension 4096 sans évaluer la qualité de recherche
  (l'étape 8 est une évaluation, pas une bascule).
