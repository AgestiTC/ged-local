# Plan — Liste des modèles groupée par origine et triée (GECO / MATO)

> Branche : `feat/liste-modeles` · ouvert le 12/11/2026

## Besoin

Partout où Matothèque affiche des modèles, la liste est aujourd'hui à plat, dans l'ordre
renvoyé par Ollama (sauf un sélecteur, trié à la main). On veut la même présentation dans
tous les écrans, groupée par **origine** :

```text
GECO   (internet, par LONG-COURRIER — envoi confirmé)
  modèle a
  modèle b
MATO   (Ollama de PC-GAME — local)
  modèle c
  modèle d
```

## Décisions (validées le 12/11/2026)

- **Le groupe se déduit de l'origine, sans étiquette à poser** : `MATO` = modèle renvoyé par
  l'Ollama de PC-GAME (`/api/tags`, en direct ou par l'AIGUILLEUR) ; `GECO` = modèle servi par
  LONG-COURRIER (IA externe de GECO).
- **Les modèles GECO sont sélectionnables partout, comme ceux de PC-GAME** (décision de Thomas,
  12/11/2026, qui remplace « affichés, non sélectionnables » prise plus tôt le même jour).
  Règle permanente conservée : **toute sortie internet est confirmée** (`netConfirm`) — choisir
  un modèle GECO envoie le prompt, et les documents joints, chez GECO.
- **En deux temps.** Tant que Matothèque ne sait pas joindre LONG-COURRIER (étape 5), un modèle
  GECO est affiché avec `selectionnable: false` et le serveur le refuse : sans route, l'envoyer à
  Ollama ne ferait qu'une erreur. L'interface se fie à `selectionnable`, jamais à l'origine :
  l'étape 5 n'aura qu'à le passer à `true`.
- **Tri alphabétique** dans chaque groupe (insensible à la casse, locale `fr`).
- Ordre des groupes : `GECO`, puis `MATO`.
- Le groupe est un **classement d'affichage** : il ne change ni le routage par usage
  (`runtime_config.model_for`), ni le choix « Auto ».

## Constat du 12/11/2026 — ce qui manque hors de ce dépôt

- La liste que Matothèque reçoit vient de `/api/tags`, que l'AIGUILLEUR relaie tel quel depuis
  PC-GAME : **elle ne contient que des modèles MATO et aucun champ d'origine**.
- **Aucune route ne donne aujourd'hui la liste des modèles GECO** à Matothèque : LONG-COURRIER
  (LXC 108, `:21451`) n'accepte que l'AIGUILLEUR (`.105`) en liste blanche, n'expose que `/v1/*`
  en relais et des routes `/admin/*`, et rien n'est encore sorti avec la clé (HTTPS côté GECO
  pas en place).
- **Prérequis, à demander aux sessions AIGUILLEUR / LONG-COURRIER** (dépôts séparés, hors de ce
  plan) : une route en lecture seule, joignable depuis `.83`, qui rend la liste des modèles
  externes (forme OpenAI `/v1/models` : `{"data":[{"id": …}]}`).
- Tant que cette route n'existe pas, Matothèque affiche le groupe MATO seul, et les Paramètres
  disent « liste GECO : non configurée ». Les étapes ci-dessous sont livrables sans attendre.

## Contrat annoncé par l'AIGUILLEUR (12/11/2026) — pas encore construit

Réponse de la session AIGUILLEUR (son plan : branche `feat/repli-geco`,
`docs/plan-repli-geco.md`, étape R2-bis ; décisions n° 14 et 15 de son `ROADMAP.md`).
**Laisser `modeles_externes_url` vide tant qu'elle n'a pas annoncé la mise en production.**

- **Tout passe par l'AIGUILLEUR**, liste comme génération. Matothèque ne parle jamais à
  LONG-COURRIER (dont la liste blanche reste `.105` seul). L'interdiction du 04/11 est levée pour
  Matothèque, **sur choix explicite seulement** ; NetSight reste exclu.
- **Liste** : `GET http://192.168.42.105:21450/modeles/externes` →
  `{"object":"list","data":[{"id":"geco/<id>","origine":"GECO"}],"lu_le":"<ISO 8601>"}`. Servie
  depuis un cache (immédiate) ; jamais lue = `data` vide, en 200. Compatible avec `lire_externes`.
- **Nom d'un modèle GECO** : `geco/<id>`. Le préfixe signale la sortie ; l'AIGUILLEUR le retire
  avant de relayer. Les modèles locaux restent sur `/api/tags`, inchangé.
- **Génération** : dialecte OpenAI seulement — `POST /v1/chat/completions` (ou `/v1/completions`)
  sur `.105:21450`, `model = "geco/<id>"`. Un `geco/…` sur `/api/chat` ou `/api/generate` reçoit
  400. Streaming au choix. Les options propres à Ollama (`num_ctx`…) n'existent pas côté GECO.
- **En-têtes** : `X-AI-Project: ged-local` obligatoire, `X-AI-Usage` facultatif (journal des
  sorties, sans contenu).
- **Autorisation** : réglage par projet dans l'AIGUILLEUR, « peut sortir vers GECO », fermé par
  défaut (sinon 403, rien ne sort). À ouvrir par Thomas pour `ged-local`.
- **Plafond** : 32 Mio par requête ; modèles de texte seulement (pas d'images).
- **HTTPS côté GECO** : en place depuis le 12/11.
- **« Passer HA sur GECO » et le repli automatique** : réglages de l'AIGUILLEUR (« GECO par
  défaut » par projet, puis repli), les applications n'ont rien à savoir.
- Ordre de construction annoncé : AIGUILLEUR connaît LONG-COURRIER → autorisation par projet →
  `/modeles/externes` → routage de `geco/…` → « GECO par défaut » → repli.

## Emplacements recensés (12/11/2026)

| # | Fichier | Ce qui s'affiche | Aujourd'hui |
| --- | --- | --- | --- |
| 1 | `frontend/src/components/reports/ChatPanel.tsx:96` | sélecteur du chat (capture d'écran) | à plat, embeddings compris |
| 2 | `frontend/src/components/reports/ModelSelector.tsx:85` | sélecteur de Créer | à plat, sans embeddings |
| 3 | `frontend/src/pages/RegroupementsPage.tsx:167` | sélecteur d'analyse | à plat |
| 4 | `frontend/src/pages/SettingsPage.tsx:1285` | modèle préféré d'un prompt | trié alpha, sans groupe |
| 5 | `frontend/src/pages/SettingsPage.tsx:2405` | modèle par défaut | à plat |
| 6 | `frontend/src/pages/SettingsPage.tsx:2478` | modèle par usage | à plat |
| 7 | `frontend/src/pages/SettingsPage.tsx:2510` | liste des modèles installés | à plat |
| 8 | `frontend/src/pages/SettingsPage.tsx:2605` | tableau comparatif | à plat |
| 9 | `frontend/src/pages/HuggingFacePage.tsx:248` | vue « installés » | à plat |
| 10 | `frontend/src/components/settings/DiagnosticIA.tsx:209` | tableau du diagnostic IA | à plat |
| 11 | `frontend/src/components/logs/IAEchecs.tsx:65` | échecs IA par modèle | ordre du serveur |

Côté serveur : `GET /api/system/models` (`backend/routers/system.py:737`) alimente 1 à 9 ;
`GET /api/generate/models` (`backend/routers/generate.py:467`) est un second point d'entrée à
vérifier (encore appelé ? sinon à supprimer). 10 et 11 viennent d'autres routes.

## Étape 1 — Backend : origine de chaque modèle, liste GECO en lecture seule, refus côté serveur

- `GET /api/system/models` : chaque modèle d'Ollama porte `origine: "MATO"` et
  `selectionnable: true`.
- Nouveau réglage en base `modeles_externes_url` (vide par défaut, surcharge à chaud par
  `runtime_config`). Renseigné, le backend y lit la liste GECO (GET, forme OpenAI, délai court
  de 3 s, async httpx) et l'ajoute à la réponse dans un champ **séparé** `externes`, chaque
  entrée portant `origine: "GECO"` et `selectionnable: false`. Séparé, pour que le code existant
  qui lit `models` (auto-réparation, recommandations, tableau) ne prenne jamais un modèle GECO
  pour un modèle installé.
- Champ `externes_etat` rendu par un **mot** : `"non_configure" | "disponible" | "injoignable"`.
  Une liste GECO injoignable ne fait jamais échouer la route : les modèles MATO restent servis.
- L'appel ne transmet **aucune donnée de Matothèque** (ni document, ni prompt, ni en-tête de
  projet au-delà de `X-AI-Project`).
- **Garde-fou serveur** : toute génération (rapport, chat, comparatif, regroupement, modèle par
  usage, modèle par défaut, modèle préféré d'un prompt) dont le modèle demandé n'est pas dans la
  liste installée d'Ollama est refusée en 400 avec un message clair. Griser une option dans
  l'interface ne suffit pas à garantir qu'aucun document ne sort.
- Tests pytest : origine MATO, liste GECO lue / vide / injoignable / malformée, refus d'un
  modèle GECO sur chaque route de génération.

Critères : les tests passent ; URL vide → aucun appel sortant ; un modèle GECO envoyé à une route
de génération rend 400 et n'atteint ni Ollama ni LONG-COURRIER.

## Étape 2 — Frontend : un seul utilitaire de groupement et un seul composant

- `frontend/src/utils/modeles.ts` : `grouperModeles(modeles, externes)` → `[{ groupe, modeles }]`,
  ordre `GECO` puis `MATO`, tri alphabétique dans chaque groupe. Fonction pure. Un groupe vide
  n'est pas rendu.
- `frontend/src/components/common/OptionsModeles.tsx` : rend les `<optgroup>` d'un `<select>` ;
  une option est `disabled` quand `selectionnable` est faux (mention « internet — pas encore
  utilisable ») ; un modèle GECO utilisable porte la mention « internet ». Props pour
  le libellé d'une option (nom court, taille, 😈) et pour un filtre (ex. sans embeddings).
- `frontend/src/api/index.ts` : `OllamaModel` reçoit `origine` et `selectionnable` ; la réponse
  de `systemApi.models()` reçoit `externes` et `externes_etat`. `useModeles` les expose.
- Tests vitest : ordre des groupes, tri, option GECO désactivée, groupe vide masqué, filtre.

Critères : tests vitest verts ; `tsc` sans erreur.

## Étape 3 — Appliquer le groupement aux onze emplacements

- Emplacements 1 à 6 : remplacer chaque `models.map(<option>)` par `OptionsModeles`. Conserver
  les comportements existants : option « Auto », modèle enregistré mais désinstallé encore
  affiché (4 et 5), embeddings masqués dans Créer (2), nom court et taille (2).
- Emplacements 7 à 9 : listes et tableaux avec un intertitre par groupe ; les lignes GECO sans
  bouton d'action (ni mise à jour, ni suppression, ni choix par défaut).
- Chat : un refus 400 du serveur (modèle désinstallé ou GECO) doit afficher son message — aujourd'hui
  `fetch` dans `frontend/src/api/index.ts` lève « chat HTTP 400 » et perd le `detail`.
- Emplacements 10 et 11 : même ordre et même intertitre ; ces deux écrans ne concernent que
  des modèles MATO, les trier par ordre alphabétique.
- Paramètres : un champ pour `modeles_externes_url` et l'état de la liste GECO (`externes_etat`).
- `GET /api/generate/models` : le supprimer s'il n'a plus d'appelant, sinon l'aligner.

Critères : plus aucun `models.map(m => <option` hors de `OptionsModeles` ; les onze emplacements
présentent le même ordre ; aucun modèle GECO ne peut être choisi nulle part ; un rôle non-admin
voit toujours « Auto » seul, sans erreur.

## Étape 4 — Vérification dans l'appli et documentation

- `/verify` (pile jetable, PostgreSQL), avec un faux fournisseur de liste GECO : parcourir les
  onze emplacements, URL vide puis renseignée puis injoignable.
- Contrôle par la route HTTP (`http://192.168.42.83:3003` après déploiement) comme par HTTPS.
- `CHANGELOG.md`, `ROADMAP.md`, `README-UTILISATEUR.md`, et la section « Passerelle IA locale »
  de `CLAUDE.md` (ce que GECO veut dire dans une liste de modèles).
- **Étape applicative après déploiement** : saisir `modeles_externes_url` dans les Paramètres,
  une fois la route livrée côté AIGUILLEUR / LONG-COURRIER — sans cela le groupe GECO reste vide.

## Étape 5 — Utiliser un modèle GECO, avec confirmation de sortie internet

Dépend de décisions et de livraisons **hors de ce dépôt** : lever le principe n° 3 de
LONG-COURRIER (« Matothèque ne passe jamais par ici »), HTTPS côté GECO, liste blanche, et le
contrat d'appel (adresse, dialecte, en-têtes) fixé par les sessions AIGUILLEUR / LONG-COURRIER.

- Pas de nouvelle adresse : l'envoi part vers `ollama_url` quand c'est l'AIGUILLEUR (contrat
  ci-dessus), en **dialecte OpenAI** `/v1/chat/completions` — exception voulue à la règle
  « jamais `/v1/*` », qui vaut pour Ollama (`num_ctx` et `keep_alive` y sont ignorés ; côté GECO
  ils n'existent pas). Un réglage en base « sorties vers GECO » (fermé par défaut) fait passer
  les modèles GECO à `selectionnable: true`. Un 403 de l'AIGUILLEUR (projet non autorisé) est
  rendu tel quel à l'utilisateur.
- Limites à dire dans l'interface : texte seulement (pas de vision), 32 Mio par requête, pas de
  réglage de taille de contexte.
- `exiger_modele_installe` accepte alors un modèle GECO ; la génération part vers la passerelle
  et non vers Ollama. Le routage « Auto » (`runtime_config.model_for`) ne choisit **jamais** un
  modèle GECO : il n'y a de sortie que sur un choix explicite.
- **Besoin de Thomas (12/11/2026)** : accéder à GECO « si le local ne répond pas, ou pour un
  besoin spécifique ». Deux cas dans Matothèque : le **choix manuel** d'un modèle GECO, et, quand
  PC-GAME ne répond pas, une **proposition** « envoyer à GECO ? » — jamais une bascule
  silencieuse, puisque des documents sortiraient. Son exemple « passer HA sur GECO » relève de
  l'AIGUILLEUR (routage par client), pas de ce dépôt : besoin transmis à sa session.
- Interface : choisir un modèle GECO déclenche `netConfirm` avant chaque envoi (ce qui part :
  prompt, nombre de documents), et l'action figure dans « Demandes Mise à jour internet ».
- Journal : chaque sortie laisse une ligne (qui, quand, modèle, nombre de documents, taille) —
  jamais le contenu.
- Les tâches de fond (enrichissement, embeddings, vision, lots) restent sur PC-GAME.
- **Exigences issues de la relecture sécurité de l'étape 1 (12/11/2026)** :
  - la destination se décide côté serveur d'après l'**origine résolue**, jamais d'après le seul
    nom envoyé par le client ; un nom non résolu (Ollama et liste GECO muets) est **refusé** (503)
    — aujourd'hui il passe, sans conséquence puisque tout part vers Ollama
    (`test_tout_en_panne_laisse_passer_meme_un_nom_geco` devra changer de sens) ;
  - vérifier avec l'AIGUILLEUR qu'il ne mêle jamais de modèle externe à `/api/tags` ;
  - le worker recontrôle le modèle figé dans un job en file ; les réglages `default_model`,
    `usage_models`, `vision_model`, `modele_prefere` et `Regroupement.modele` sont validés à
    l'écriture ;
  - en-têtes et jeton propres à la destination GECO, jeton en réglage chiffré (`SECRET_KEYS`),
    jamais dans l'adresse ; `follow_redirects=False`.
- Mettre à jour `CLAUDE.md` : la phrase « 100 % local, sans cloud » devient fausse dès cette étape.

Critères : sans confirmation, rien ne sort ; « Auto » ne sort jamais ; une sortie refusée ou en
échec est dite à l'utilisateur ; chaque sortie est journalisée sans contenu.
