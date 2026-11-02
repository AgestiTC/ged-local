# File IA lisible et pilotable — « Créer » passe d'abord

> **Origine** : 02/11/2026. Un comparatif lancé depuis *Créer* affichait « En file d'attente —
> d'autres tâches IA passent avant… » **alors qu'aucune tâche ne tournait** : la **pause IA**
> (`ia_pause = 1`) bloquait tout le GPU, y compris l'interactif. Le message mentait sur la cause,
> et l'utilisateur n'avait aucun moyen d'agir.
>
> **Source de vérité de l'ordonnancement** : `AIGUILLEUR/docs/conception.md` § « Ordonnancement GPU » —
> interactif > batch, **préemption coopérative** (on n'interrompt jamais un appel Ollama en cours, on
> cesse d'envoyer du batch tant qu'un interactif attend), et **la pause IA = cas particulier : priorité
> batch mise à zéro**. Matothèque garde sa file locale (le worker) tant que la passerelle n'ordonnance
> pas elle-même (« rien de codé côté passerelle », plan-arbitrage-gpu) ; elle lui transmet dès
> maintenant la priorité par en-tête, pour être prête.

## Décisions

1. **« Créer » est prioritaire.** Toute tâche lancée depuis *Créer* (rapport, comparatif, réparation de
   comparatif, présentation, remplissage de modèle, analyse de regroupement, musique, vidéo) est
   `interactif` ; le reste (analyse, enrichissement, indexation, vision en lot, idées) est `batch`.
2. **La pause IA retient les lots, pas « Créer »** — aligné sur AIGUILLEUR. Elle reste un frein total
   pour le batch ; une tâche *Créer* passe quand même, avec la mention « IA en pause — passée en priorité ».
   *(Recommandé. Alternative refusée : pause totale + bouton « Continuer » obligatoire à chaque fois —
   c'est précisément le blocage constaté.)*
   **✅ Validée par l'utilisateur le 02/11/2026 — livrée en v1.151.0** (étape 1 : `_claim(...,
   interactifs_seulement=True)` pendant la pause ; « Arrêter » n'annule plus que les lots ; musique et
   vidéo comptées dans « Créer »).
3. **Trois actions sur une tâche qui attend** :
   - **Continuer** → force la priorité : la tâche part au **prochain créneau GPU libre**, devant tout
     le reste, y compris les autres interactifs. Ne coupe **jamais** une tâche déjà en cours
     (préemption coopérative) ; aucune nouvelle tâche de lot ne démarre tant qu'elle n'a pas démarré.
   - **Lancer en file d'attente** → elle reste à sa place ; on affiche un **repère temporel** :
     position, « démarrage estimé vers HH:MM (≈ N min) », calculé sur les durées réelles récentes.
   - **Annuler** → arrête la tâche (immédiat si elle attend, au mieux si elle tourne).
4. **Liste des tâches IA** visible depuis l'attente : celles **en cours** et celles **devant** (type,
   libellé générique, depuis quand, avancement) — **jamais** de nom de document d'un autre usage
   (confidentialité : le rôle utilisateur voit la file, pas le contenu des tâches d'autrui).

## Étape 1 — Classer et ordonner (backend, worker)

> ✅ **Fait** — v1.151.0 (pause = lots) et v1.152.0 (`priorite_forcee`, ordre forcée > interactif > FIFO).

`services/job_worker.py` : `INTERACTIF_TYPES` = les types de *Créer* (décision 1). Nouvelle colonne
`jobs.priorite_forcee` (bool, migration à chaud dans `database.py`). `_claim` : ordre = forcée, puis
interactif, puis FIFO. **Pause** : on ne réclame plus que les interactifs (au lieu de sauter toute la
classe GPU). Tant qu'un job forcé attend, on ne réclame aucun job de lot.

**Acceptation** : tests purs de l'ordre (forcée > interactif > lot > FIFO) ; en pause, un comparatif est
réclamé et une analyse ne l'est pas ; un job forcé en attente empêche le démarrage d'un lot ; aucun job
`running` n'est interrompu.

## Étape 2 — Dire la vérité sur l'attente (backend, API)

> ✅ **Fait** — v1.152.0 : `services/file_ia.py`, `GET /api/jobs/{id}/file`. Le flux SSE garde son texte (le panneau dit la vraie raison).

`GET /api/jobs/{id}/file` : `raison` (`pause_ia` | `gpu_occupe` | `interactifs_devant` | `aucune`),
`position`, `devant[]` et `en_cours[]` (type, libellé générique, statut, depuis, avancement — sans nom
de document), `estimation` (début estimé ISO + minutes) depuis la **médiane** des durées des 7 derniers
jours par type (repli : valeur par défaut par type), divisée par le budget GPU. Classée **utilisateur**
(lecture) dans `services/acces.py` ; mise à jour de `tests/data/routes_utilisateur.txt` **volontaire**.
Le flux SSE du comparatif (`routers/compare.py`) émet la vraie raison au lieu du texte fixe.

**Acceptation** : la raison `pause_ia` est rendue quand la pause bloque ; l'estimation est bornée et
jamais négative ; aucun nom de document d'une autre tâche dans la réponse.

## Étape 3 — Agir sur la tâche (backend, API + droits)

> ✅ **Fait** — v1.152.0 : `POST /api/jobs/{id}/prioriser` ; `cancel` ouvert au rôle utilisateur pour « Créer » (la route refuse un lot) ; journal `job_prioriser` / `job_annuler`.

`POST /api/jobs/{id}/prioriser` (« Continuer ») : seulement sur un job `pending` interactif, idempotent,
journalisé (`audit.emit`). « Annuler » : ouvrir `POST /api/jobs/{id}/cancel` au rôle utilisateur **pour
les jobs interactifs en attente ou en cours** (les lots restent admin). Les tâches n'ont pas encore de
propriétaire (étape 5 de l'authentification) : la règle sera resserrée « à ses propres tâches » quand
`jobs.cree_par` existera.

**Acceptation** : prioriser un lot ou un job terminé = 409 ; un utilisateur annule un comparatif mais
reçoit 403 sur une analyse en lot ; les deux actions apparaissent au journal d'activité.

## Étape 4 — Transmettre la priorité à AIGUILLEUR (backend, client Ollama)

> ✅ **Fait** — v1.152.0 : `X-AI-Priority` par ContextVar (worker selon le type, requête HTTP = interactif). AIGUILLEUR le journalise déjà (`app/logs.py`), sans l'appliquer.

`services/ollama_service.py` : un `ContextVar` posé par `job_worker._run` (et par les appels
interactifs hors worker) porte la priorité ; `_headers()` ajoute `X-AI-Priority: interactif|batch` à
côté de `X-AI-Project`. Aucune logique d'ordonnancement côté client : c'est le rôle de la passerelle.
Vérifier dans AIGUILLEUR que l'en-tête est accepté (passthrough) et journalisé.

**Acceptation** : un appel émis par un job `comparatif` porte `X-AI-Priority: interactif`, un `enrich`
porte `batch` ; sans contexte = `batch` ; test de non-régression du branchement direct Ollama (secours).

## Étape 5 — Le panneau d'attente (frontend)

> ✅ **Fait** — v1.152.0 : `components/common/FileIA.tsx` dans le comparatif ; 02/11/2026 : monté aussi dans le rapport (`ReportPreview`), la présentation (`GEDPage`) et l'analyse de regroupement (`RegroupementsPage`). Non couverts : remplissage de modèle, musique, vidéo.

Composant `FileIA` réutilisable, monté dans `CompareProgress` puis les autres attentes de *Créer*
(rapport, présentation, regroupement) : raison en clair, liste des tâches en cours / devant, repère
temporel, boutons **Continuer** / **Laisser en file** / **Annuler** (confirmation pour Annuler). Rafraîchi
toutes les 5 s tant que la tâche attend ; disparaît au démarrage. Bouton « Reprendre l'IA » proposé aux
admins quand la raison est `pause_ia`.

**Acceptation** : `tsc` + vitest ; en pile jetable (`/verify`), pause IA active : le comparatif démarre
seul (décision 2) ; avec un lot en cours : la liste, l'estimation et les trois boutons fonctionnent.

## Étape 6 — Vérifier, documenter, livrer

Pile jetable de bout en bout, CHANGELOG (étapes applicatives : aucune), ROADMAP, aide utilisateur
(« Pourquoi ma tâche attend »), note dans AIGUILLEUR (`docs/plan-migration.md`) : Matothèque envoie
`X-AI-Priority`. Livraison par `scripts/deployer.ps1`.

**Acceptation** : verdict vert de `verifier-deploiement.ps1` ; en prod, un comparatif lancé pendant la
pause IA démarre.

## Hors périmètre

- Interrompre une génération Ollama en cours (impossible côté Ollama ; contraire à la préemption coopérative).
- Ordonnancement inter-projets (JARVIS > FOULEE > Matothèque) : il appartient à AIGUILLEUR.
