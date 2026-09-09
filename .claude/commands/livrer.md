---
description: Livrer le travail en cours — commit, merge, bump, tag, push, et déploiement vérifié
---

Livre le travail en cours de bout en bout. **Une modification n'est pas terminée quand elle
est poussée : elle l'est quand la prod la sert.**

Argument optionnel : `$ARGUMENTS` = la version à publier (`1.95.0`). Sans argument, propose-la
d'après la nature des changements (correctif → patch, fonctionnalité → mineure) et annonce-la
avant de l'appliquer.

## Le rail, dans l'ordre

1. **Vérifier avant de livrer.** Suite backend et frontend, plus `tsc`. Si quoi que ce soit
   est rouge, **arrête-toi et dis-le** — ne livre pas en espérant que ça passe.
2. **Commiter** ce qui reste dans l'arbre de travail, en messages conventionnels
   (`feat:`, `fix:`, `docs:`, `refus:`) qui disent *pourquoi*, pas seulement *quoi*.
3. **CHANGELOG** : une entrée pour la version, dans le style des précédentes — ce que ça
   change pour l'utilisateur, les refus assumés, et les **étapes applicatives** s'il y en a.
4. **ROADMAP** : cocher ce qui est fait, laisser ouvert ce qui ne l'est pas.
5. **Merger** la branche dans `main` en `--no-ff`, avec un message qui résume la décision
   structurante — pas la liste des fichiers.
6. **Release** : `.\scripts\release.ps1 -Version X.Y.Z -Message "…"` (bump `VERSION` +
   `package.json`, commit, tag annoté, push sur `origin`).
7. **Pousser aussi sur Gitea** : `git push gitea main --follow-tags`. Le script ne pousse que
   sur le remote suivi ; l'oublier laisse le registre réel en retard.
8. **Déployer** : `.\scripts\deployer.ps1`, puis **rapporter le verdict du script**.

## Pièges à ne pas répéter

- **N'appelle jamais ces scripts avec `2>&1`.** PowerShell 5.1 transforme la sortie standard
  d'erreur des exécutables natifs en erreur bloquante : `docker login` et `git push` font
  échouer le script alors qu'ils ont réussi. Lance-les **sans redirection**.
- **Le tag ne construit aucune image.** Le registre réel est Gitea, alimenté depuis Windows
  par `deployer.ps1`. Pousser un tag et annoncer la livraison serait faux.
- **Le seul verdict qui compte est celui de `verifier-deploiement.ps1`** (appelé par
  `deployer.ps1`) : tag présent au registre, `latest` pointant sur CE build, et **prod servant
  cette version**. Tant qu'il n'est pas vert, **n'annonce pas la livraison** — dis que la prod
  est en retard, et pourquoi.
- **Les étapes applicatives ne se devinent pas.** Migration à jouer, pré-rempli à
  réinstaller, réglage à saisir : liste-les explicitement dans le compte rendu. Livrer sans
  elles donne une fonctionnalité déployée mais vide.
- **Les colonnes de base s'ajoutent seules** au démarrage du backend (`database.py`) : ne
  demande pas d'action manuelle en base pour un simple ajout de colonne ou de table.

## Ce que tu rends à la fin

Le verdict, puis ce qui est visible pour l'utilisateur, puis ce qui reste ouvert. Si le
déploiement a échoué, **diagnostique** (logs du backend sur le LXC) plutôt que de proposer de
relancer à l'aveugle.
