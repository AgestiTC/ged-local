# Plan — Projets de la page Créer (brouillon, reprise, archive, profils)

> Demande de Thomas, 09/10/2026 : « dans Créer, quelle que soit la tuile choisie, propose de
> commencer un projet pour le mettre en brouillon et le reprendre. Prévois qu'il pourrait y avoir
> des profils utilisateur. Prévois la gestion des projets (archive, suppression…). »
>
> Décisions de Thomas (même jour) :
> - un projet garde **le travail ET ses résultats** (rapports, tableaux, morceaux produits) ;
> - **sauvegarde automatique** dès que le projet est nommé ;
> - profils : **prévus dans les données seulement** — chaque projet a un propriétaire, pas d'écran
>   de connexion pour l'instant.
>
> Mot d'ordre permanent : optimisation et réactivité (sauvegarde légère, pas de traitement lourd).

## Ce qui existe déjà

- `rapports` (historique des rapports générés), `presentations`, tâches durables (`jobs`) dont le
  résultat reste en base (comparatif, rapport, musique, remplissage de modèle).
- L'état de la page Créer vit dans le magasin `reportStore` (Zustand) et dans `ReportsPage`
  (groupes, critères, modèle Word…), plus `MusiquePanel` pour la musique. Rien n'est persisté.

## Modèle de données

Table `projets` (créée par `create_all` : table neuve, aucune migration de colonne) :

| Colonne | Rôle |
|---|---|
| `id` UUID | |
| `titre` | nom donné par l'utilisateur |
| `mode` | tuile : rapport_libre, remplir_template, classement, comparatif, wiki, musique, (video) |
| `etat` JSONB | tout le travail en cours, versionné par `etat.version` (format libre par tuile) |
| `statut` | `brouillon` · `archive` (la corbeille = `supprime_le` non nul) |
| `proprietaire` | texte, défaut `"thomas"` — **prévision des profils**, filtre de toutes les requêtes |
| `supprime_le` | suppression douce : corbeille, purge définitive après 30 jours ou à la main |
| `created_at`, `updated_at` | |

Table `projet_resultats` (lien projet ↔ ce qu'il a produit) : `projet_id`, `type` (rapport, job,
presentation, morceau), `ref` (identifiant de l'objet), `libelle`, `created_at`. On ne recopie pas
les résultats : on les référence. Supprimer un projet ne supprime PAS ses résultats sauf demande
explicite (case « supprimer aussi les résultats »).

## API (`/api/projets`)

- `GET /projets?statut=brouillon|archive|corbeille&q=` — liste légère (sans `etat`).
- `POST /projets` {titre, mode, etat} — création.
- `GET /projets/{id}` — détail avec `etat` et résultats.
- `PATCH /projets/{id}` {titre?, etat?, statut?} — sauvegarde automatique (corps partiel) ;
  `updated_at` sert de verrou optimiste (409 si le projet a changé ailleurs).
- `POST /projets/{id}/dupliquer`, `POST /projets/{id}/archiver`, `POST /projets/{id}/restaurer`.
- `DELETE /projets/{id}` → corbeille ; `DELETE /projets/{id}?definitif=true` → purge.
- `POST /projets/{id}/resultats` {type, ref, libelle} — appelé quand une génération aboutit.
- Toutes les requêtes filtrent sur `proprietaire` (aujourd'hui constant, demain le profil actif).

## Interface

1. **Bandeau « Projet » en tête de Créer**, quelle que soit la tuile : « Sans projet — Commencer
   un projet » ou « Projet : <titre> · enregistré il y a 3 s » + menu (renommer, dupliquer,
   archiver, supprimer, fermer).
2. **« Mes projets »** : panneau latéral (ou page) listant brouillons / archivés / corbeille, avec
   recherche, tuile, date de dernière modification, nombre de résultats ; ouvrir = restaurer tout
   l'état et la tuile.
3. **Sauvegarde automatique** : à chaque modification, envoi groupé après 2 s d'inactivité
   (debounce), indicateur « enregistrement… / enregistré ». Pas de sauvegarde sans projet ouvert.
4. **Résultats** : chaque génération aboutie dans un projet ouvert s'y rattache (onglet
   « Résultats du projet »).
5. Confirmations de suppression dans la page (jamais de `window.confirm`).

## Étapes

1. Modèle + API + tests (création, sauvegarde partielle, verrou optimiste, archive, corbeille,
   purge, filtre propriétaire).
2. Sérialisation de l'état par tuile : extraire de `ReportsPage` / `reportStore` / `MusiquePanel`
   une fonction `etatCourant()` et `restaurer(etat)` — c'est l'étape délicate (état dispersé).
3. Bandeau projet + sauvegarde automatique.
4. « Mes projets » (liste, ouvrir, archiver, supprimer, corbeille).
5. Rattachement des résultats (rapport, comparatif, modèle rempli, musique, wiki).
6. Vérification sur pile jetable (créer, modifier, recharger la page, reprendre ; archive ;
   corbeille), puis livraison.

## Hors périmètre

- Écran de connexion, mots de passe, droits : seul le champ `proprietaire` est posé.
- Partage de projet entre personnes.
