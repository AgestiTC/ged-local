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

## 🔌 Contrat d'API (mince, OpenAI-compatible + 1 champ)

```
POST /v1/ai/generate      { usage, prompt, system?, format?, images?, project, priority? }
POST /v1/ai/embeddings    { usage:"embeddings", input[], project }
POST /v1/chat/completions { … , usage, project }        # compat OpenAI (tout SDK marche)
GET  /v1/ai/models        → modèles installés + capacités (vision/texte/embed) + version/MAJ
GET  /v1/ai/policy        → table usage→modèle en vigueur (transparence du « pourquoi »)
```

- `usage` : `enrichissement | rapport | vision | embeddings | transcription | chat | resume` …
- `project` : identifie l'appelant (quotas / priorité / logs). **Ne donne aucun pouvoir sur la config
  d'un autre projet** (autonomie : chaque projet garde ses réglages/permissions).
- `priority` : optionnel ; sinon déduite de `usage`/`project` (cf. ordonnancement).

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
