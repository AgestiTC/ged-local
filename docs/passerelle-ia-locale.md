# Passerelle IA locale (partagée) — conception

> **Statut : conception (rien codé).** Document de décision. Origine : discussion 04/09/2026
> (Matothèque ↔ FOULEE). Portée : **tous les projets** qui ont besoin d'IA locale, pas seulement
> Matothèque et FOULEE.

## 🎯 Problème

Chaque projet qui utilise l'IA locale réimplémente **la même plomberie** : choix du modèle, fallback,
vérification de capacité (vision/texte/embed), keep-alive/prewarm, file d'attente GPU, retries, logs.
Résultat : du code dupliqué, des incohérences (ex. un projet pointe `IA_MODELE_VISION` vers un modèle
non installé, ou vers un modèle texte), et une **contention GPU aveugle** quand deux projets tapent
Ollama en même temps (VRAM RTX 4080 16 Go).

## 💡 Principe fondateur

Un projet appelle la passerelle avec une **intention** (`usage`), **pas un nom de modèle**. La
passerelle décide *quel modèle, pourquoi*, ordonnance la file GPU, journalise. Le projet ne connaît
plus ni les noms de modèles, ni Ollama.

**Bénéfices** :
- **Apps plus légères** : elles n'embarquent plus routage/fallback/keep-alive/file/retries.
- **Plus rapides en pratique** : le modèle reste **chaud pour tous** (un modèle déjà chargé pour un
  projet sert le suivant instantanément — plus de rechargement à froid). Coût : un saut réseau local
  négligeable (< quelques ms).
- **100 % local garanti et centralisé** (voir ci-dessous).
- **Cohérence** : une seule logique de routage/capacité pour tout le monde.

## ✅ Vérification de cohérence — Matothèque + FOULEE (le contrat de génération)

Reprise du **fonctionnement réel** des deux premiers clients, pour valider que la passerelle ne casse
rien :

**Matothèque** utilise, via `OllamaService` : plusieurs **usages** (rapport, enrichissement, embeddings,
vision, chat) ; du **streaming SSE** (rapports & chat) ; le champ **`format`** (sortie JSON contrainte :
Import IA, enrichissement) ; des **`options`** (`num_predict`, `think`) et **`keep_alive`** ; des
**timeouts longs** (chargement à froid d'un modèle de 43 Go) ; le **prewarm** ; la **concurrence par
classe** (gpu/io) ; et le **provisioning** (`check_update`, `pull`, token HF).

**FOULEE** (vérifié par FOULEE sur son **code de prod**, pas son banc d'essai — correction 04/09/2026) a
**deux appelants** qui utilisent tous deux **`POST /api/chat`** (pas `/api/generate`) :
- *prod* (`imports.py`) : `messages` avec **images DANS le message** (`messages[i].images`), `stream:false`,
  `options:{temperature:0}`, **aucun `format`** (le JSON est demandé en prose puis « raclé »).
- *socle* (`ia.py`) : `options:{num_predict:…}` **sans** temperature, + `GET /api/tags` (test de dispo).
- Hôte Ollama par défaut = **`http://192.168.42.130:11434` (PC-GAME)**, réglable en base — **pas localhost**.
- (Le `/api/generate` + `format` schéma + `num_ctx` que j'avais décrits = son **banc d'essai jetable**, pas un client.)

**Conclusions — le design tient, mais 4 exigences précises se dégagent** :
1. **Exposer les surfaces Ollama NATIVES et fidèles** : `/api/chat`, `/api/generate` **et** `/api/tags` —
   sans normaliser l'une vers l'autre (les images ne se placent pas au même endroit : `messages[i].images`
   en chat, racine en generate). Matothèque fait du chat ET du generate ET du streaming SSE ; FOULEE fait
   du chat.
2. **`options` passé VERBATIM, aucun défaut injecté.** Les deux appelants de FOULEE divergent déjà
   (`temperature` seul vs `num_predict` seul) : imposer un défaut casserait silencieusement l'un des deux.
   Idem `format` : laissé passer s'il est là, **jamais ajouté**.
3. **Multi-hôte — ❓ QUESTION OUVERTE (à clarifier avant tout code).** La passerelle **ne suppose PAS un
   hôte Ollama unique**. Indices connus : Matothèque = `host.docker.internal` ; FOULEE = PC-GAME
   `192.168.42.130` (réglable en base) ; proxy 8012 qui front déjà Voxtral+Ollama sur PC-GAME.
   **Hypothèse à VÉRIFIER** (mentionnée par l'utilisateur, non confirmée) : un **failover** existant
   « **PC-GAME si Ollama en ligne, sinon HomeAssistant (HA)** ». Si c'est le cas, le routage a **deux
   dimensions** — `usage → modèle` **et** `→ backend/hôte` **avec bascule** — et centraliser ce failover
   dans la passerelle (au lieu de le réimplémenter par projet) est un gain net. **Rien n'est verrouillé :
   topologie réelle à établir (qui héberge quoi, qui teste/bascule aujourd'hui, rôle exact du proxy 8012).**
4. **Métadonnée passerelle via EN-TÊTES** (`X-AI-Usage`, `X-AI-Project`, `X-AI-Priority`), **pas dans le
   body** → le corps reste un payload Ollama **strictement verbatim**. Streaming **gardé possible, jamais
   imposé**.

**Risque n°1 confirmé par FOULEE : la sur-abstraction.** Ses deux appelants, dans le même dépôt, divergent
déjà sur `options` — une passerelle qui avalerait `format`/`options`/le streaming casserait l'un ou l'autre
**sans qu'on s'en aperçoive** (extraction devenue silencieusement moins bonne, vue six mois plus tard).
Passthrough fidèle + politique mince = validé par les deux clients.

> Réserve : cette description est le **code** de FOULEE, elle **n'engage pas** FOULEE à consommer la
> passerelle — c'est la décision de son utilisateur.

## 🔗 n8n (orchestrateur) — PAS une 4ᵉ posture

n8n est un **orchestrateur** (surveillance de dossiers, cron de réindexation, webhooks), **pas un
composant d'inférence**. Aujourd'hui dans Matothèque il **déclenche le backend**, qui appelle Ollama ;
n8n n'appelle pas Ollama lui-même.

- **Vis-à-vis de la passerelle** : n8n est au plus un **client** (`project=n8n`) — s'il a besoin d'IA
  dans un workflow, il appelle **la passerelle** (mêmes 3 postures), **jamais Ollama en direct** (sinon
  il contourne routage + audit). Ses appels IA se rangent donc dans les postures existantes.
- **Vis-à-vis du 100 % local** : n8n est de l'infra locale, MAIS c'est un outil **généraliste** qui
  **peut** sortir (nœuds HTTP / webhook vers l'extérieur). Son **egress non-IA** est une **gouvernance
  séparée** (allowlist réseau si l'on veut le garantir local), **pas une posture de la passerelle IA**.

Donc **pas de 4ᵉ posture** : le trafic IA de n8n retombe dans les 3 postures via la passerelle ; son
automation egress est un autre domaine, à traiter côté n8n (allowlist), comme l'updater pour les registres.

## 🔒 Garantie 100 % local (exigence non négociable)

La passerelle est **LE point unique** où l'on garantit et audite « aucune sortie Internet pour
l'inférence ». Elle ne parle qu'à **Ollama / Voxtral en local**. Elle n'a **aucune** raison de sortir
sur Internet pour servir une requête.

Les **mises à jour de modèles** (qui, elles, nécessitent Internet — `ollama pull`) restent une **action
séparée, explicite et confirmée** (repris du modèle « Demandes Mise à jour internet » de Matothèque),
**jamais sur le chemin d'inférence**. Idéalement : le composant d'inférence n'a même pas de route
réseau sortante ; seul un sous-composant « mise à jour modèles », déclenché manuellement, en a une.

## 🔐 Local vs Internet : DEUX passerelles séparées (garantie structurelle)

Pour **garantir** (et pas seulement promettre) le 100 % local aux apps qui l'exigent, la séparation
est **structurelle**, pas un drapeau `allow_internet` dans une passerelle unique (un drapeau est une
convention qu'un bug peut contourner).

- **Passerelle IA LOCALE** — ne parle qu'à **Ollama/Voxtral**, **aucune route réseau sortante**,
  **aucun secret**. Une app « 100 % local » n'appelle **que** celle-ci → elle **ne peut pas** fuiter,
  même buguée : il n'y a pas de route vers Internet (barrière réseau, comme pour la veille RSS).
- **Passerelle IA INTERNET** (dédiée, **opt-in**) — parle aux IA **cloud** (Claude, OpenAI, Perplexity…),
  détient les tokens (chiffrés), a une sortie Internet. Un projet qui **veut** l'IA cloud la cible
  **explicitement**.

> Même logiciel possible en **deux déploiements/rôles** (réseau + capacités distincts) → réutilisation
> du code sans sacrifier la garantie. Un projet marqué **`local-only`** dans sa politique ne reçoit
> jamais l'URL cloud (ceinture + bretelles, au-dessus de la barrière réseau).

## 🔑 Secrets — chiffrés en base, JAMAIS en clair dans un fichier

Exigence non négociable, valable pour **les deux** passerelles :

- **Tous les tokens API en base, chiffrés (Fernet)** — on réutilise le pattern déjà en place dans
  Matothèque (`services/crypto.py` ; secrets `enc::…` dans la table `config` ; `SECRET_KEYS`).
- **La clé de chiffrement** vient d'une **variable d'environnement / Bitwarden** au déploiement,
  **jamais** d'un fichier du dépôt.
- **Déchiffrement en mémoire uniquement**, au moment de l'appel au fournisseur. Au repos : que du chiffré.
- La passerelle **LOCALE ne détient AUCUN secret** ; seule la passerelle **INTERNET** porte les tokens.
- **Paramétrable via l'UI d'admin** : saisie → chiffrée à l'écriture, masquée à la lecture (comme
  HuggingFace / BookStack aujourd'hui dans Matothèque).

## 👁️ Traçabilité de l'egress cloud

Chaque appel de la passerelle **Internet** est **journalisé et audité** (projet · fournisseur · usage ·
durée), dans l'esprit « Demandes Mise à jour internet » : on sait exactement ce qui est sorti, quand,
pour qui. La passerelle **locale** n'a rien à auditer côté réseau — elle ne sort pas.

## 🔄 Mise à jour des modèles & HuggingFace ≠ IA internet (3ᵉ posture)

Les **MAJ de modèles** (`ollama pull`) et **HuggingFace** (modèles gated, recherche HF) touchent Internet,
mais **au service de l'IA locale** — ce n'est **pas** l'onglet « IA internet » (qui, lui, fait sortir tes
données vers un LLM cloud). Trois postures réseau à ne pas confondre :

| Posture | Ce qui se passe | Internet | Secrets |
|---|---|---|---|
| 🟢 Inférence locale | prompts → Ollama local | **0** (garantie) | aucun |
| 🔄 Provisioning modèles (pull/MAJ/HF) | un **modèle descend** | **entrant**, confirmé, minimal (nom de modèle) | token HF (chiffré) |
| 🌐 Inférence cloud (opt-in) | prompts **partent** vers Claude/OpenAI | **sortant** | tokens cloud (chiffrés) |

**Où ça vit** : dans l'onglet **🟢 IA locale**, sous-section **« Maintenance / Mises à jour des
modèles »** — pattern « Demandes Mise à jour internet » déjà en place dans Matothèque : chaque action
**confirmée**, **entrante**, n'envoyant **qu'un nom de modèle** (jamais un document).

**Préservation de la garantie (séparer inférence et provisioning, même côté local)** :
- **Passerelle d'inférence locale** → **aucune** route Internet, jamais.
- **Composant « updater » dédié** (pull Ollama + HF) → route Internet **restreinte par allowlist** aux
  **registres seuls** (`registry.ollama.ai`, `huggingface.co`), **inbound**, déclenché **à la main**. Il
  écrit les modèles dans le store Ollama ; l'inférence les consomme ensuite en local.
- Le **token HuggingFace** (secret) est **chiffré en base**, porté par **l'updater** — jamais par la
  passerelle d'inférence locale.

Résultat : l'inférence locale ne peut pas fuiter (pas de route) ; les MAJ/HF restent possibles mais
**cantonnées** à un composant maintenance allowlisté, inbound, confirmé.

## 🔌 Contrat d'API — passthrough Ollama fidèle + politique par en-têtes

**Surface primaire = les endpoints Ollama NATIFS, corps VERBATIM.** La politique passe par des **en-têtes**
(le body n'est jamais réécrit) :

```
POST /api/chat        body Ollama verbatim (messages[].images, options, format?, stream?)
POST /api/generate    body Ollama verbatim (prompt, images racine, options, format?, stream?)
POST /api/embeddings  body Ollama verbatim
GET  /api/tags        liste des modèles (test de dispo)         # utilisé par le socle FOULEE
En-têtes de politique : X-AI-Usage, X-AI-Project, X-AI-Priority   # métadonnée, hors body
```

Endpoints d'**admin/observabilité** (plan de contrôle, pas le chemin d'inférence) :
```
GET  /admin/models    modèles par hôte + capacités (vision/texte/embed) + version/MAJ
GET  /admin/policy    table usage→(modèle, backend) en vigueur — le « quel modèle, pourquoi »
GET  /admin/usage     journal : project · usage · modèle · backend · durée · attente
```

- **`X-AI-Usage`** : `enrichissement | rapport | vision | embeddings | transcription | chat | resume` … →
  la passerelle **choisit le modèle** (si le body ne fixe pas déjà `model`) **et le backend/hôte**.
- **`X-AI-Project`** : identifie l'appelant (quotas / priorité / logs). **Aucun pouvoir sur la config d'un
  autre projet** (autonomie préservée).
- **`X-AI-Priority`** : optionnel ; sinon déduite de l'usage/projet (cf. ordonnancement).
- **`options`, `format`, `stream`, `keep_alive` passés VERBATIM** — jamais complétés ni normalisés (leçon
  des deux appelants FOULEE aux options disjointes).
- **OpenAI-compat** (`/v1/chat/completions`) = **couche de confort optionnelle** par-dessus, pour les SDK ;
  jamais au prix de la fidélité du passthrough natif.
- **Routage à deux dimensions** : `usage → modèle` **et** `usage/projet → backend/hôte` (multi-hôte :
  host.docker.internal, PC-GAME, proxy 8012…).

## 🧠 Politique de routage (blueprint = Matothèque)

1. **Table `usage → modèle`** centralisée, éditable à chaud (le « quel modèle, pourquoi » matérialisé).
2. **Fallback « même famille »** (repris de `runtime_config.model_candidates`) : modèle configuré →
   sinon autres modèles **réellement installés** de la même famille (petit d'abord). **Jamais d'appel
   à un modèle absent.**
3. **Capacités vérifiées** (`ollama show` → `completion/vision/tools/embedding`) : refuser une image
   vers un modèle non-vision, etc. (évite la mésaventure `IA_MODELE_VISION` de FOULEE).

## 🚦 Ordonnancement GPU (priorité)

- **Priorité par requête**, déduite de l'usage/projet : **`interactif`** (clic humain : chat, vision,
  recherche) **>** **`batch`** (enrichissement de fond, embeddings).
- **File unique** devant Ollama : l'interactif passe devant ; le **batch cède** (on cesse d'envoyer du
  batch tant qu'un interactif attend → il prend le prochain créneau). C'est la **préemption
  coopérative** ; Ollama ne préempte pas un appel en cours, mais on ne lui en envoie plus.
- **Équité par projet** (poids/quota) pour éviter la famine d'un projet par un autre.
- **Concurrence GPU bornée** (1-2 en parallèle sur la 4080) — reprise de la concurrence par classe de
  Matothèque.
- La **pause IA** de Matothèque (drapeau `ia_pause`, 1.72.0) devient un **cas particulier** de cet
  ordonnancement (priorité batch mise à zéro).

## 🖥️ UI d'admin — UNE page « Gestion des IA », DEUX sections séparées

**Décision : une seule UI, pas deux applications.** La séparation qui garantit le 100 % local est
côté **runtime** (deux passerelles : réseau + secrets), **pas côté console**. L'admin est un **plan de
contrôle** qui pilote les deux sans donner la moindre route Internet aux apps d'inférence. Une seule UI
= un seul modèle mental ; et la **frontière visuelle renforce** la garantie (elle la rend lisible).

**🟢 Onglet IA LOCALE** (blueprint = Paramètres actuels de Matothèque) :
- modèles Ollama installés + **version à jour / MAJ dispo / injoignable** (reprend `check_update`) ;
- capacités par modèle (vision/texte/embed) ;
- table `usage → modèle` **locale** ; concurrence & priorité GPU ;
- logs locaux. **Aucun secret ici.**

**🌐 Onglet IA INTERNET** (opt-in) :
- fournisseurs (Claude, OpenAI…) ; **tokens chiffrés** (saisie masquée, chiffrée à l'écriture) ;
- modèles cloud par fournisseur ; table `usage → modèle` **cloud** ; quotas/coûts ;
- **journal d'egress** (audit : projet · fournisseur · quand). Bandeau « sortie Internet ».

**Garde-fous UX (sécurité)** :
1. L'UI vit dans un **plan de contrôle hors de la passerelle locale** (qui reste sans secret). Les tokens
   saisis ne sont écrits QUE dans le magasin chiffré de la passerelle **Internet**. **L'UI ne stocke aucun
   secret.**
2. **Jamais de mélange** : un sélecteur de modèle ne présente pas local et cloud sans marqueur **🌐**
   explicite ; un projet marqué **`local-only`** ne peut pas voir/choisir un modèle cloud (grisé).

Les apps clientes, elles, n'ont **plus rien** à afficher sur les versions/écarts de modèles.

> Alternative écartée : **2 UIs distinctes** (plus « paranoïaque ») — dégrade l'ergonomie sans rien
> ajouter, la vraie barrière étant le backend séparé, pas la console.

## 🏠 Où ça vit (et où ça NE vit pas)

- **Dans la couche proxy partagée** — un **proxy `8012` agrège déjà Voxtral + Ollama** (*à revérifier*,
  cf. mémoire infra-transcription). C'est le foyer naturel, **pas la GED**.
- **Découplage** : une panne de la passerelle ne doit pas devenir une panne de Matothèque **plus** de
  FOULEE ; la GED ne doit pas être le point de défaillance des autres.
- **Autonomie** : la passerelle **propose** un routage, elle **n'impose** rien aux projets.

## 🛣️ Migration progressive (sans big-bang)

1. La passerelle expose l'API **par-dessus l'Ollama existant** (aucun changement Ollama).
2. **Matothèque = 1ᵉʳ client** (elle a déjà le vocabulaire d'usages → migration quasi triviale ; meilleur
   banc d'essai).
3. **FOULEE ensuite** (un seul usage `vision` → trivial).
4. Accès Ollama direct **gardé en secours** pendant toute la bascule.

## 🚫 Non-buts

- Ce n'est **pas** un 2ᵉ Ollama (même VRAM, aucun gain).
- Ce n'est **pas** Matothèque qui « avale » l'IA des autres (elle n'est qu'un client exemplaire +
  blueprint).
- La valeur ajoutée est la **politique** (routage / priorité / logs / garantie locale) — la sérialisation
  VRAM reste le fait d'Ollama.

## ♻️ Ce que ça évite de réinventer (par projet)

| Aujourd'hui, chaque projet code… | Demain, via la passerelle |
|---|---|
| Choix + fallback de modèle | ✅ centralisé |
| Ne pas appeler un modèle supprimé | ✅ |
| Vérif capacité (vision/texte/embed) | ✅ |
| Keep-alive / prewarm | ✅ |
| File + priorité GPU (VRAM) | ✅ |
| Retries transitoires | ✅ |
| Logs « qui/quoi/pourquoi » | ✅ |
| UI versions/MAJ des modèles | ✅ (une seule pour tous) |

Un nouveau projet = **une clé `project` + des `usage`**. Zéro plomberie IA.
