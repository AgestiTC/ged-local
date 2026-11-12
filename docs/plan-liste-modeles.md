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

### Bouton « IA LOCAL / IA GECO » (demande de Thomas, 12/11/2026) — cadrage avec l'AIGUILLEUR

Mécanisme retenu avec la session AIGUILLEUR : **le bouton est un réglage de Matothèque**, pas une
écriture dans la configuration de l'AIGUILLEUR.

- Deux questions distinctes, deux lieux : l'AIGUILLEUR dit qui a le **droit** de sortir
  (autorisation du projet, que seul Thomas ouvre dans son administration) ; Matothèque dit où elle
  **veut** aller (le bouton). Bouton sur GECO sans droit ouvert → 403 de l'AIGUILLEUR, rien ne sort.
- Pas de route d'écriture de la configuration de l'AIGUILLEUR pour les applications :
  `X-AI-Project` n'est qu'une déclaration, n'importe quel client du réseau pourrait basculer un
  projet vers Internet.
- Pas de traduction `/api/*` → `/v1/*` côté AIGUILLEUR : en mode GECO, c'est Matothèque qui appelle
  `/v1/chat/completions` avec `model = "geco/<id>"`. Il faut donc un réglage « modèle GECO
  utilisé » (par usage interactif) à côté du bouton.
- **Périmètre : l'interactif seul** (chat, rapports, comparatifs). Jamais les tâches de fond ;
  embeddings et vision restent locaux (GECO ne fait que du texte, l'AIGUILLEUR rend 400 ailleurs).
- **Repli** : celui de l'AIGUILLEUR ne s'applique pas à Matothèque (il exige une intention, et
  Matothèque nomme ses modèles). Ici, le repli = proposer « PC-GAME ne répond pas : passer sur
  IA GECO ? », c'est-à-dire ce même bouton.
- **À trancher par Thomas** (révision de la décision n° 14 « jamais Auto ») : le bouton fait
  partir « Auto » vers GECO. Proposition commune des deux sessions : acceptable si la bascule est
  un geste humain confirmé, avec un bandeau visible tant qu'elle est active, et pour l'interactif
  seulement. Reste aussi à décider : qui peut basculer (administrateur ou tout utilisateur), et
  si la bascule est globale ou par utilisateur.
- État côté GECO au 12/11 : ses modèles ne se chargent pas encore (erreurs 500) ; un envoi
  partirait sans obtenir de réponse tant que ce n'est pas corrigé chez GECO.

### Décision rapportée le 12/11/2026 et conception retenue (branche `feat/ia-geco`)

La session AIGUILLEUR rapporte que Thomas a tranché chez elle (décision n° 14 révisée, commit
`fb52636` de son dépôt) : **oui au bouton global « IA LOCAL / IA GECO », « Auto » compris**, à
trois conditions — bascule = geste humain confirmé ; bandeau visible tant que le bouton est sur
GECO ; interactif seulement, jamais les traitements de fond.

Choix par défaut pris ici, **à confirmer par Thomas** : la bascule est **globale** (un réglage en
base, comme la « Pause IA ») et **réservée à l'administrateur**.

#### Étape 5a — Backend

- Réglages en base (défaut entre parenthèses) : `ia_destination` (`local`) ∈ `local | geco` ;
  `geco_modele` (vide) = le modèle GECO utilisé par « Auto » en mode GECO, obligatoirement
  présent dans la liste GECO. Passer `ia_destination` à `geco` exige `geco_modele` et une liste
  GECO disponible, sinon 422. Ces réglages, comme `default_model`, `usage_models` et
  `vision_model`, **refusent à l'écriture** un nom de l'autre origine.
- `GET /api/system/models` : les modèles GECO passent à `selectionnable: true` dès que la liste
  est disponible ; la réponse porte `ia_destination` et `geco_modele`. Une route lisible par
  **tout utilisateur connecté** rend `ia_destination` (pour le bandeau).
- **Résolution unique, côté serveur** (`resoudre_modele_interactif`) pour les routes
  interactives — chat, rapport, remplissage de modèle, comparatif (critères et lancement),
  regroupement, assistant, relecture de prompt, présentation :
  - modèle explicite installé sur Ollama → local ;
  - modèle explicite présent dans la liste GECO → GECO, **si** la requête porte
    `sortie_confirmee: true` (sinon 409 « confirmation requise ») ou si `ia_destination = geco` ;
  - « Auto » : `geco_modele` si `ia_destination = geco`, sinon le routage local habituel ;
  - **le doute refuse** : nom non résolu parce qu'Ollama ou la liste GECO ne répond pas → 503 dès
    qu'une sortie GECO est possible (nom en `geco/`, ou mode GECO). Plus de « on laisse passer ».
- **Envoi** : `OllamaService.generate / generate_stream / chat_stream` reconnaissent un modèle
  `geco/…` et parlent alors `/v1/chat/completions` sur `ollama_url` (l'AIGUILLEUR), en-têtes
  `X-AI-Project` et `X-AI-Usage`, sans option Ollama (`num_ctx`, `keep_alive`), flux SSE relayé.
  Les autres méthodes (embeddings, vision, préchauffage) **lèvent** sur un modèle `geco/…`. Un
  usage de fond (enrichissement, embeddings, vision, lots) avec un modèle `geco/…` **lève** aussi :
  seconde barrière, indépendante de la résolution.
- Le worker **recontrôle** l'origine du modèle figé dans un job avant de l'exécuter.
- Erreurs de l'AIGUILLEUR rendues telles quelles à l'utilisateur : 403 (projet non autorisé à
  sortir), 400, 5xx de GECO.
- **Journal** : une ligne d'activité par envoi vers GECO (utilisateur, heure, route, modèle,
  nombre de documents, taille en caractères, confirmé par requête ou par le mode) — jamais le
  contenu. La bascule du bouton est journalisée aussi.
- Plafond : refuser avant envoi une requête de plus de 32 Mio.

#### Étape 5b — Frontend

- **Bouton « IA LOCAL / IA GECO »** dans l'en-tête, visible de tous, actionnable par
  l'administrateur ; passer sur GECO ouvre `netConfirm` (ce qui partira : questions, extraits et
  documents des demandes interactives ; ce qui ne part jamais : traitements de fond).
- **Bandeau** permanent sur toutes les pages tant que `ia_destination = geco`.
- Sélecteurs : un modèle GECO choisi à la main en mode local déclenche `netConfirm` à chaque
  envoi, puis envoie `sortie_confirmee: true`. « Auto » affiche le modèle GECO en mode GECO.
- Le badge « 100 % local » du chat et de la barre latérale devient « IA GECO — internet » quand
  la demande part vers GECO.
- IA locale injoignable sur une demande interactive → proposer « passer sur IA GECO ? » (admin).
- Paramètres : choix de `geco_modele` ; l'action figure dans « Demandes Mise à jour internet ».

### Mise à jour du 12/11/2026 (soir) — liste en service, et condition de Thomas sur le bouton

Message de la session AIGUILLEUR :

- **La liste est en service** : `GET http://192.168.42.105:21450/modeles/externes` répond
  (AIGUILLEUR 0.10.0). Elle change dans la journée (6 modèles à midi, 2 à 16 h 14 UTC) : ne
  jamais la figer. Elle contient aussi des **modèles d'embeddings**
  (`geco/text-embedding-nomic-embed-text-v1.5`) : à ne proposer ni pour le chat ni comme
  `geco_modele` ; l'AIGUILLEUR refuse de toute façon `geco/` sur les embeddings.
- **`ged-local` est autorisé à sortir** (`projets_sortie_internet = "ged-local,ha"`), avec la
  condition de Thomas : « n'autorise les accès à GECO que pour HA et GED **si le bouton IA GECO
  est activé** ». L'AIGUILLEUR ne voit pas le bouton : c'est Matothèque qui garantit qu'aucun
  `geco/…` ne part bouton désactivé.
- La réponse d'un envoi porte `X-Aiguilleur-Backend: internet`. GECO ne chargeait pas ses
  modèles l'après-midi : un envoi peut échouer côté GECO.

**Ce que cela change dans la conception ci-dessus** (ces points la remplacent) :

- **Bouton sur IA LOCAL = aucun envoi vers GECO, même sur choix manuel.** Le chemin « modèle GECO
  choisi à la main en mode local + confirmation à chaque envoi » est **supprimé**, ainsi que le
  champ `sortie_confirmee` et le 409. Un modèle GECO explicite en mode local est refusé (400).
- Un modèle GECO n'est `selectionnable` que si le bouton est sur IA GECO **et** la liste disponible.
- Bouton sur IA GECO : « Auto » → `geco_modele` ; un autre modèle GECO peut être choisi à la
  main ; un modèle MATO choisi à la main reste local.
- Seconde barrière dans `OllamaService` et dans le worker : un envoi `geco/…` lève si le bouton
  n'est pas sur IA GECO **au moment de l'envoi** (un job mis en file puis exécuté après retour
  sur IA LOCAL échoue proprement).
- Les modèles GECO d'embeddings sont marqués (`embedding: true`), masqués des sélecteurs et
  refusés comme `geco_modele`.
- Interface : plus de `netConfirm` par envoi ; la seule confirmation est celle de la bascule.

### Ajout du 12/11/2026 — l'en-tête `X-AI-Sortie: geco` (AIGUILLEUR 0.10.1)

Exigence relayée par la session AIGUILLEUR (décision de Thomas chez elle : c'est Matothèque qui
communique à l'AIGUILLEUR l'autorisation de sortir ; bouton inactif = IA locale, strict).

- Bouton sur IA GECO : chaque `POST /v1/chat/completions` avec `model = "geco/<id>"` porte
  `X-AI-Sortie: geco`, en plus de `X-AI-Project: ged-local`.
- Sans cet en-tête (ou avec une autre valeur), l'AIGUILLEUR rend 403 et rien ne sort ; il ne
  redirige pas vers un modèle local.
- L'en-tête seul ne route rien : un modèle local reste sur PC-GAME.
- **Choix d'implémentation** : l'en-tête n'est posé **que** sur l'envoi GECO, et seulement après
  la relecture de `ia_destination` au moment de l'envoi — jamais dans `entetes_projet()`, pour
  qu'aucune autre requête ne le porte. C'est la troisième barrière, tenue par l'AIGUILLEUR.

### Décision de Thomas du 12/11/2026 — les utilisateurs restent en 100 % local

« Je ne souhaite pas que les utilisateurs puissent voir ce nouveau bouton » ; « les utilisateurs
restent en 100 % LOCAL ». **L'IA GECO est réservée aux sessions administrateur.**

- **Serveur** : seule une session administrateur, authentification active, peut sortir vers GECO.
  Tout autre acteur (rôle utilisateur, jeton d'automate, authentification inactive ou suspendue,
  rôle indéterminé) reste local : en mode GECO, « Auto » suit le routage local habituel, et un
  modèle `geco/…` explicite reçoit 403. Un job GECO dont l'auteur n'est pas administrateur est
  refusé par le worker. `GET /api/system/ia/destination` répond toujours `local` à un
  non-administrateur.
- **Interface** : pour le rôle Utilisateur, ni bouton, ni bandeau, ni proposition de bascule, ni
  modèle GECO dans les sélecteurs ; « 100 % local » reste affiché, et c'est vrai pour lui.
- Ceci remplace, dans les sections précédentes, « bouton visible de tous » et « bandeau sur
  toutes les pages pour tous ». La bascule reste un réglage global, mais elle n'a d'effet que sur
  les demandes interactives de l'administrateur.
- Autres choix pris par défaut le même jour, **à confirmer** : activer IA GECO exige
  l'authentification active ; les automates (jetons n8n) ne sortent jamais vers GECO.

### Relecture de sécurité indépendante et vérification dans l'appli (12/11/2026, avant livraison)

Relecture en lecture seule des huit invariants (bouton sur LOCAL, administrateur seul, jamais le
fond, décision côté serveur, tâche en file après retour en local, en-tête `X-AI-Sortie`, journal
sans contenu, redirections et plafond). **Aucun constat critique ni élevé** : la barrière d'envoi
(`OllamaService._preparer_geco`) refuse par défaut et ne dépend pas des routes.

**Corrigé avant livraison** — trois écarts avec les règles écrites plus haut :

- **Suspension de secours.** Le rôle de session restait « admin » pendant une suspension
  (`outils.auth --suspendre`), alors que la règle dit « authentification inactive ou suspendue →
  local ». Désormais : aucun rôle n'est posé pendant une suspension (`acces.py`) ; la barrière
  d'envoi et le recontrôle du worker relisent **en base** que l'authentification est active et non
  suspendue (`ollama_service.authentification_en_base`) ; activer le bouton est refusé pendant une
  suspension (`system._ecriture_geco_autorisee`). Revenir sur LOCAL reste toujours permis.
- **Tâche en file.** Le rôle de l'auteur est figé à la mise en file : une tâche GECO posée par un
  administrateur échoue proprement si l'authentification est éteinte ou suspendue à l'exécution.
- **Modèles enregistrés.** `Regroupement.modele` et le modèle préféré d'un prompt refusent un nom
  `geco/…` à l'écriture (422), comme `default_model` : sinon n'importe quel utilisateur bloquait un
  regroupement pour tous. Un modèle GECO se passe à l'analyse, il ne s'enregistre pas.

**Limites connues, non traitées** (aucune ne permet une sortie hors des règles) :

- `ollama_url` est l'adresse où part le contenu en mode GECO, et elle s'écrit comme n'importe quel
  réglage. Authentification active : administrateur seulement. Pendant une suspension de secours,
  ou authentification éteinte : toute personne du réseau peut la changer — c'est déjà vrai pour
  tout le trafic IA local, et c'est le sens documenté de la suspension (« LAN maîtrisé »). **À
  décider par Thomas** : protéger `ollama_url` et `modeles_externes_url` comme les réglages
  d'authentification (refus d'écriture pendant une suspension).
- Aucun filtre sur la confidentialité des documents : en mode GECO, ce que l'administrateur
  sélectionne part tel quel, offres de candidats comprises. La fenêtre de confirmation le dit.
- Après un plantage du worker, une tâche GECO en cours est rejouée, donc renvoyée, sans nouvelle
  confirmation (le bouton est toujours sur GECO ; chaque envoi reste journalisé).
- Antérieur à cette étape : le journal d'activité garde le résultat complet d'une tâche (texte d'un
  rapport), et les 80 premiers caractères d'une consigne apparaissent dans les logs. Ce n'est pas
  le journal d'envoi, et rien de cela ne sort du serveur.

**Vérifié dans l'appli** sur pile jetable (PostgreSQL éphémère, backend en deux process,
authentification active, sessions administrateur et utilisateur créées en base, fausse passerelle
jouant Ollama et GECO et notant chaque requête) : par l'API puis dans le navigateur. **Non vérifié** :
un envoi vers le vrai GECO, dont les modèles ne se chargeaient pas le 12/11.

