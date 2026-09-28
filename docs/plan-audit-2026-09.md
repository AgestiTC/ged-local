# Plan d'audit — Matothèque v1.113.0 (28/09/2026)

Audit **en lecture seule** : aucun agent ne modifie le code. Chaque constat donne un fichier et
une ligne, une gravité (CRITIQUE / HAUTE / MOYENNE / BASSE), et un **scénario d'échec concret**
(quelle entrée, quel état → quel mauvais résultat). Un constat sans scénario n'entre pas au
rapport. Les constats CRITIQUES et HAUTS sont re-vérifiés dans le code avant d'être retenus.

## Les règles du projet, contre lesquelles on juge

Ce ne sont pas des préférences : chacune a déjà coûté un incident.

1. **100 % local.** Aucune sortie Internet sans confirmation explicite de l'utilisateur, aucun
   appel réseau au chargement d'une page, et **zéro fuite** : une sortie n'envoie jamais de
   contenu, tag, résumé, nom ou chemin de document. Toutes les sorties sont recensées dans
   Paramètres › « Demandes Mise à jour internet ».
2. **État d'une tâche = en base, jamais en mémoire** : le backend tourne en
   `uvicorn --workers 2` ; un dict par process n'est vu que par la moitié des requêtes.
3. **Contexte non sécurisé** : l'appli est aussi servie en HTTP (`192.168.42.83:3003`).
   Jamais `navigator.clipboard` ni `crypto.randomUUID` directement — passer par
   `utils/clipboard.ts` et `utils/uuid.ts`.
4. **Secrets chiffrés en base** (Fernet, `services/crypto.py`) ; jamais en clair dans les logs
   ni dans les réponses d'API.
5. **Appels Tika / Ollama async** (httpx) ; rien de bloquant dans une route async.
6. **Rien de réglementaire produit par l'IA** (fiscalité, congés : modules datés et sourcés).

## Étapes

| # | Étape | Agent | Périmètre |
|---|---|---|---|
| 1 | Sécurité et fuites réseau | `ecc:security-reviewer` | `backend/` (routes, services, connecteurs) |
| 2 | Backend Python / FastAPI | `ecc:fastapi-reviewer` | `backend/` hors tests |
| 3 | Frontend React / TypeScript | `ecc:react-reviewer` | `frontend/src/` |
| 4 | Base de données | `ecc:database-reviewer` | `backend/models`, `database.py`, `scripts/init-db.sql`, requêtes |
| 5 | Erreurs silencieuses | `ecc:silent-failure-hunter` | backend + frontend |

### 1 — Sécurité et fuites réseau
Traversée de chemin (upload, dossiers surveillés, `folders/browse`, quarantaine des doublons,
extraction ZIP), SSRF (sources SMB/WebDAV, vérification des liens, veille RSS, vérification
des congés), injection SQL, secrets (Fernet, identifiants SMB, jeton BookStack), et surtout
**toute sortie réseau non confirmée ou qui transporte une donnée de document** (règle 1).

### 2 — Backend Python / FastAPI
Appels bloquants dans des routes async, état gardé en mémoire de process (règle 2), sessions
SQLAlchemy mal fermées, transactions partielles, exceptions trop larges, timeouts manquants.

### 3 — Frontend React / TypeScript
API de contexte sécurisé appelées en direct (règle 3), appels réseau externes au montage
(règle 1), hooks (dépendances, fuites d'abonnement, courses sur requêtes concurrentes).

### 4 — Base de données
Index manquants sur les requêtes chaudes (recherche hybride, planning, jobs), N+1, migrations
à chaud de `database.py` (idempotence, verrous sur grosses tables), usage de pgvector
(`embedding_small` HNSW et repli 4096d).

### 5 — Erreurs silencieuses
`except` qui avalent, replis qui masquent une panne (un échec lu comme « vide » ou « aucun
résultat »), erreurs d'API non affichées à l'utilisateur.

## Hors périmètre
Déploiement et infrastructure LXC, `ant-tool/` (prototype gitignoré), dépendances tierces
(couvertes par `security-audit` en CI), performance fine hors requêtes base.
