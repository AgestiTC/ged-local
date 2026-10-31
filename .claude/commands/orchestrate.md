---
description: Enchaîner des agents ECC sur une étape de plan — remplace /ecc:orchestrate custom (absent d'ECC 2.2.2)
---

Exécute une **chaîne d'agents** sur une tâche, dans l'ordre, chacun recevant le compte rendu du
précédent. Remplace `/ecc:orchestrate custom`, que `/ecc:plan-orchestrate` produit mais qui
n'existe pas dans ECC 2.2.2 (constaté le 31/10/2026).

Arguments reçus : `$ARGUMENTS`

## 1. Lire les arguments

Forme attendue (celle produite par `/ecc:plan-orchestrate`) :

```
custom "<agent1>,<agent2>,…" "<description de la tâche>"
```

- Le mot `custom` est facultatif. Les noms d'agents peuvent avoir le préfixe `ecc:` ou non :
  normalise vers `ecc:<nom>` (ex. `tdd-guide` → `ecc:tdd-guide`).
- Vérifie que **chaque agent existe** dans la liste des types d'agents disponibles de la session.
  Un nom inconnu : **arrête-toi** et dis lequel, avec les noms proches. Ne remplace jamais un agent
  en silence.
- Si la description commence par `[Plan: <chemin>#step-<n>]`, lis la section correspondante du plan
  (étape n, en comptant à partir de 1) : elle complète la description, elle ne la remplace pas.

Annonce avant de commencer : la chaîne, la tâche, la branche git courante.

## 2. Garde-fous avant le premier agent

- **Branche** : si un agent de la chaîne écrit du code (`tdd-guide`, `refactor-cleaner`,
  `build-error-resolver`, `doc-updater`, `e2e-runner`…) et que la branche courante est `main`,
  crée d'abord une branche `feat/<sujet-court>` (règle du dépôt : on ne code pas sur `main`).
- **Arbre de travail** : s'il contient des modifications non commitées qui ne viennent pas de cette
  tâche, arrête-toi et demande (plusieurs sessions peuvent travailler dans ce dépôt).
- Règles du projet à transmettre à **chaque** agent (dans son brief) :
  - `CLAUDE.md` du dépôt fait foi (FastAPI async, paramètres en base, état en base et jamais en
    mémoire — `uvicorn --workers 2`, commentaires en français, helpers `utils/uuid` et
    `utils/clipboard` côté frontend) ;
  - **confidentialité** : ne jamais lire `storage/`, la base, ni aucun document ou offre de
    candidat ; les tests utilisent des données fictives générées dans les tests ;
  - **100 % local** : aucune nouvelle dépendance réseau à l'exécution, aucun appel externe ;
  - ne pas commiter, ne pas pousser, ne pas déployer (c'est `/livrer`).

## 3. Exécuter la chaîne

Pour chaque agent, dans l'ordre, un appel à l'outil Agent (`subagent_type` = `ecc:<nom>`), au
premier plan (on attend son résultat avant le suivant). Brief de chaque agent :

```
Tâche : <description complète + section du plan si fournie>
Position : agent <i>/<N> de la chaîne <liste>.
Règles du projet : <les règles de la section 2>.
Compte rendu de l'agent précédent (HANDOFF) : <texte, ou « aucun » pour le premier>.
Ton rôle : <rôle propre à l'agent, ci-dessous>.
Termine par un bloc HANDOFF : ce que tu as fait (fichiers touchés), ce qui reste,
les problèmes BLOQUANTS (s'il y en a), et ce que l'agent suivant doit vérifier.
```

Rôle selon l'agent :
- `tdd-guide` : écrire les tests d'abord, puis le code, jusqu'au vert ; lancer les tests concernés.
- `database-reviewer` : relire tables, index, migrations à chaud (`database.py`), requêtes.
- `code-reviewer` / `python-reviewer` / `typescript-reviewer` : relire les changements ; classer
  les constats CRITIQUE / IMPORTANT / MINEUR ; ne corriger que si on le lui demande.
- `security-reviewer` : relire sous l'angle sécurité (authentification, secrets, injection,
  contrôle d'accès, journaux sans données sensibles) ; mêmes niveaux de gravité.
- `e2e-runner` : vérifier le parcours dans l'appli qui tourne, via la recette `/verify` (pile
  jetable préfixée, jamais la base de dev ni la prod).
- `doc-updater` : mettre à jour la documentation et le CHANGELOG concernés.
- `architect` / `planner` : proposer, sans écrire de code.

**Arrêt** : si un relecteur signale un constat **CRITIQUE**, ou si un agent signale un problème
bloquant, n'appelle pas l'agent suivant. Fais corriger (relance `tdd-guide`, ou corrige toi-même si
c'est trivial), puis relance le relecteur concerné. Deux allers-retours au plus, ensuite arrête-toi
et rends la main à l'utilisateur avec le constat.

Entre deux agents, donne à l'utilisateur une ligne d'avancement (« agent 2/4 — relecture base : 1
constat important, corrigé »).

## 4. Vérifier puis rendre compte

Après le dernier agent, vérifie toi-même plutôt que de croire les comptes rendus :
- suite backend et frontend + `tsc` (tests backend dans le conteneur :
  `-e DATABASE_URL=sqlite+aiosqlite:///:memory:` et `--tmpfs /app/storage:uid=10001`) ;
- `git diff --stat` : les fichiers touchés correspondent à la tâche.

Compte rendu final, en français :
1. le **verdict** (critères d'acceptation de l'étape : tenus ou non, un par un) ;
2. ce que chaque agent a fait, en une ligne ;
3. les constats restants (importants, mineurs) non traités ;
4. la suite : `/livrer` si tout est vert, sinon ce qui bloque.

Ne commite pas et ne déploie pas : c'est l'utilisateur qui lance `/livrer`.
