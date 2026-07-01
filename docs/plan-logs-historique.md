# Plan — Historique des tâches, purge & page « Logs »

> Consigné le 01/07/2026, à la demande de l'utilisateur : « comment purger les tâches ? mais
> consigne un historique (purgeable 365 jours sur demande par une fenêtre contextuelle) » +
> « une section Logs dans Paramètres qui ouvre une page avec des sections pliables : qui fait
> quoi / que s'est-il passé / debug ».

## Objectifs

1. **Purger les tâches** (table `jobs`) — mais **conserver un historique** consultable.
2. **Historique purgeable** : sur demande, via une **fenêtre de confirmation**, purger les entrées
   (ex. **> 365 jours**, ou tout).
3. **Page « Logs »** (accessible depuis Paramètres) avec **sections pliables** :
   - **Qui fait quoi** (activité) — tâches récentes : type, statut, document, durée, progression.
   - **Que s'est-il passé** (journal métier) — indexations, analyses, publications, purges…
   - **Debug** (technique) — tail des logs backend.

## Existant réutilisable

- Table **`jobs`** (type, statut, progress, message, document_id, timestamps) → base de l'historique.
- **`GET /api/logs/tail`** (déjà présent, system router) → section Debug.
- Widget **« Tâches »** (JobsIndicator) + `GET /api/jobs` → section Activité.

## Conception

### Backend
- **Rétention** : les jobs terminés (`completed|failed|cancelled`) **restent** en base = l'historique.
  (Aujourd'hui rien ne les supprime → ils s'accumulent : c'est justement l'historique.)
- **Purge** : `DELETE /api/jobs?scope=all|older_than_days&days=365` (ou `POST /api/jobs/purge`).
  - `older_than`: supprime les jobs **terminés** dont `completed_at < now - N jours` (défaut 365).
  - `all`: purge tout l'historique terminé (garde les pending/running).
  - Retourne le nombre supprimé. **Trace** la purge (journal métier).
- **Journal métier** (« que s'est-il passé ») : option A — dériver des `jobs` (déjà typés) ;
  option B — une petite table `events` (type, message, ref, created_at) alimentée aux moments clés
  (indexation lancée/finie, analyse, publication wiki, purge…). *Recommandé : A pour commencer
  (zéro nouvelle table), B plus tard si besoin de finesse.*
- **Debug** : réutiliser `GET /api/logs/tail?lines=` (déjà là).

### Frontend
- **Paramètres → « Logs & historique »** : une entrée/section avec un bouton **« Ouvrir les logs »**
  (→ page `/logs`) + le bouton **« Purger l'historique »** (fenêtre de confirmation : *tout* ou
  *> 365 jours*).
- **Page `/logs`** (route + sidebar) avec **CollapsibleSection** :
  1. **Activité (qui fait quoi)** — liste des jobs (filtre par type/statut), durée, résultat.
  2. **Journal (que s'est-il passé)** — événements lisibles (dérivés des jobs / table events).
  3. **Debug** — tail des logs backend (rafraîchir), lecture seule.
- **Fenêtre de confirmation de purge** (garde-fou destructif) : « Supprimer l'historique des tâches
  terminées (> 365 j / tout) ? Action irréversible. » → Annuler / Confirmer.

## Phasage

- **Phase 1** : endpoint de purge (`older_than_days` défaut 365 + `all`) + section Paramètres
  (bouton purge + confirmation) + page `/logs` avec **Activité** (jobs) et **Debug** (tail).
- **Phase 2** : section **Journal métier** lisible (dérivé jobs, puis table `events` si besoin) +
  filtres/recherche + pagination.

## Points d'attention

- **Purge = destructif** → toujours **confirmation** (fenêtre contextuelle), et ne jamais toucher
  aux jobs **pending/running**.
- **Perf** : index sur `jobs(completed_at)` pour la purge par date ; pagination de l'historique.
- **Rétention par défaut** : garder l'historique (pas de purge auto) ; purge **sur demande** (365 j
  proposé par défaut dans la fenêtre).
