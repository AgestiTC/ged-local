# Plan — Observabilité : une vraie page Logs (debug réel et rapide)

> **Origine** : retours user 17/07.
> **(3)** « Au clic sur *Ré-analyser* j'ai un message d'erreur, mais **rien n'est mis dans les logs** ».
> **(4)** « Revoir la page Log pour qu'il y ait un **maximum d'information** pour pouvoir debugger :
> ce qui se passe · qui fait quoi · action réalisée avec statut et message d'information/erreur…
> En bref une **vraie page LOG complète** pour que le debug soit réel et rapide. »
>
> Statut : **plan**. Constats ci-dessous **mesurés le 17/07 sur la prod (LXC 102)**.

---

## 0. Diagnostic — pourquoi « rien dans les logs »

### Constat n°1 — la prod ne produit AUCUN log applicatif

```
GET http://192.168.42.83:8008/api/logs/tail?lines=5
→ {"lines":[],"count":0,"source":"/app/logs/docflow-backend.log"}
```

**Zéro ligne.** Le problème n'est donc pas « ton erreur n'a pas été loguée » : **rien** ne l'est jamais.

### Constat n°2 — le logger bascule en silence sur stdout

`backend/logger.py` (l.47-61) est « tolérant aux pannes » : si le fichier de log n'est pas accessible
en écriture, il **n'échoue pas** — il ajoute juste un `print(...)` sur stderr et continue **avec stdout
seul**. Le commentaire du code anticipe même le cas : *« ex : conteneur non-root sur un bind-mount non
chown'é »* — et le LXC tourne bien en `appuser` (UID 10001).

> Conséquence : les logs existent (visibles via `docker compose logs backend`), mais **le fichier que lit
> la page Logs reste vide**. L'appli est aveugle à elle-même.

### Constat n°3 — la page Logs est incapable de signaler qu'elle est cassée

`routers/system.py::_tail()` : `if not path.exists(): return []`.
→ L'API renvoie **exactement la même réponse** (`lines: []`) que le fichier soit **absent**, **illisible**
ou **légitimement vide**. Impossible de distinguer « tout va bien, aucun log » de « le mécanisme de log
est mort ». **Même anti-pattern que le bug `crypto.decrypt()`** (retour vide silencieux) — à proscrire.

### Constat n°4 — les erreurs 4xx ne sont jamais loguées

`main.py` a bien `@app.exception_handler(Exception)` qui logue les **500** (avec `exc_info`). Mais :

- une **`HTTPException` volontaire** (400/404/422…) est traitée par FastAPI **sans passer par ce handler**
  → **jamais loguée**. Or ce sont précisément les erreurs « métier » qu'on veut tracer (ex. la garde
  `_secret_clair` → « mot de passe illisible »).
- une erreur **côté client** (timeout axios 30 s, réseau, CORS) ne touche jamais le backend → rien à loguer,
  alors que l'utilisateur, lui, voit bien une erreur. **C'est peut-être le cas du point (3)**.

### Point (3) — ce qui est établi, et ce qui manque

- L'endpoint `POST /documents/analyze-batch` **ne logue qu'en cas de succès** (`log.info` en fin de fonction).
  En cas d'échec : aucune trace propre.
- Le front (`SettingsPage.analyserLot`) affiche pourtant le vrai message (`extractApiError`).
- **Mesuré** : la requête de sélection (scope `all` + garde anti-empilement) s'exécute en **72 ms** sur le
  corpus réel → **l'hypothèse « timeout de la requête SQL » est écartée**.
- ⚠️ **Il manque le texte exact de l'erreur** pour conclure. Tant que la page Logs est aveugle (constats
  1-3), on ne peut pas trancher — **ce qui est exactement la raison d'être du point (4)**.

---

## 1. Correctifs immédiats (prod aveugle → prod qui parle)

| # | Correctif | Détail |
|---|-----------|--------|
| 1.1 | **Rendre le fichier de log écrivable en prod** | Le service `init` du compose fait déjà `chown -R 10001:10001 /m/logs` → **vérifier qu'il a tourné** (`docker compose logs init`) et que `./logs` est bien chown'é côté LXC. Diagnostic : `docker compose logs backend 2>&1 \| grep '\[logger\]'` → si « Fichier de log inaccessible » apparaît, c'est ça. |
| 1.2 | **`_tail` doit distinguer les cas** | Renvoyer `{lines, count, source, existe, taille_octets, erreur}`. **Ne plus jamais** confondre « absent/illisible » et « vide ». |
| 1.3 | **La page Logs doit crier quand elle est aveugle** | Bandeau rouge explicite : « Fichier de log inaccessible (`<chemin>`) — les logs partent sur la sortie standard uniquement. Vérifie les droits du montage `./logs`. » |
| 1.4 | **Loguer les `HTTPException`** | Middleware ou `@app.exception_handler(HTTPException)` → `log.warning(path, status, detail)`. Les erreurs métier deviennent traçables. |
| 1.5 | **Loguer les échecs de `analyze-batch`** | `try/except` + `log.error(scope, erreur, exc_info=True)` — et loguer aussi le **début** de l'action (pas seulement la fin). |

## 2. Une vraie page Logs — cible

### 2.1 Le socle : journal d'ACTIONS en base (pas seulement un fichier texte)

Le fichier texte répond à « ce qui se passe » mais mal à « **qui fait quoi**, avec quel **statut** ».
→ Nouvelle table **`audit_events`** (le nom `logs` est trop vague) :

| Colonne | Rôle |
|---------|------|
| `id`, `horodatage` | — |
| `acteur` | `ui` · `worker` · `n8n` · `system` (préfigure l'auth : deviendra l'utilisateur) |
| `action` | verbe stable : `analyze_batch`, `source_index`, `search`, `config_update`… |
| `cible_type` / `cible_id` | `document` / `source` / `config` + id |
| `statut` | `demarre` · `succes` · `echec` · `annule` |
| `duree_ms` | perf (repère les lenteurs : recherche ~20 s, walk SMB…) |
| `message` | texte lisible **destiné à l'utilisateur** |
| `detail` | JSONB : payload, `erreur`, `exc_type`, compteurs (`enqueued`, `nb_docs`…) |
| `correlation_id` | **relie UI → API → job worker** — le chaînon manquant aujourd'hui |

> **`correlation_id`** = la clé du « debug réel et rapide » : un id généré à l'action UI, propagé en
> en-tête HTTP puis dans le `Job` → **une action = une timeline**, même si le travail réel se fait dans
> le worker 10 min plus tard. `structlog.contextvars` est déjà en place pour le porter.

### 2.2 L'UI (page `/logs`, 3 onglets — la structure existe déjà)

- **Activité** (par défaut) — le journal d'actions, lisible par un humain :
  - ligne = `horodatage · acteur · action · cible · statut (badge) · durée · message` ;
  - **filtres** : statut (échec seul !), acteur, action, cible, plage de temps, texte libre ;
  - clic → **détail** : payload, erreur complète, **timeline du `correlation_id`** (UI → API → job(s)) ;
  - **« Copier le rapport »** (markdown : action + contexte + erreur) → collable directement ici.
- **Journal** — le log applicatif brut (fichier), avec filtre par niveau + recherche.
- **Debug** — état système : version, fichier de log (**existe ? taille ? écrivable ?**), services,
  worker (jobs en cours / échoués récents), compteurs.
- **Purge** — déjà là (`POST /jobs/purge`) ; l'étendre à `audit_events` (rétention configurable).

### 2.3 Ce qu'on trace (couverture minimale)

Toute action qui **écrit** ou **coûte cher** : indexation / sync · analyze & enrich (lot **et** unitaire) ·
purge doublons · réorg (apply/undo) · corbeille · normalisation · backup · changement de config
(**sans jamais la valeur des secrets**) · appels IA (modèle, durée, succès) · recherche (durée, nb
résultats) · vérif liens Admin. Chaque `Job` du worker écrit `demarre` → `succes`/`echec`.

### 2.4 Garde-fous

- **Jamais de secret** dans `detail` (réutiliser la logique de masquage `SECRET_KEYS`).
- **Volume** : ne pas tracer les GET de lecture (sinon le journal devient illisible) ; rétention +
  purge ; index sur `(horodatage)`, `(statut)`, `(correlation_id)`.
- **Le journal ne doit jamais casser l'action** : écriture best-effort, en `try/except`.
- **100 % local** : aucune sortie réseau.

## 3. Phasage

| Phase | Contenu | Valeur |
|-------|---------|--------|
| **1** | Correctifs 1.1→1.5 (log écrivable · `_tail` honnête · bandeau · 4xx loguées · analyze-batch tracé) | **la prod cesse d'être aveugle** — débloque le diagnostic du point (3) |
| **2** | Table `audit_events` + écriture depuis l'API et le worker + `correlation_id` | « qui fait quoi », traçable |
| **3** | Onglet **Activité** (filtres + détail + timeline + « copier le rapport ») | debug réel et rapide |
| **4** | Onglet **Debug** (santé système) + purge/rétention `audit_events` | autonomie de diagnostic |

> **Dépendance** : le champ `acteur` préfigure l'authentification (ROADMAP « log/audit qui a fait quoi »).
> Tant qu'il n'y a pas d'auth, `acteur` = origine technique (`ui`/`worker`/`n8n`).
