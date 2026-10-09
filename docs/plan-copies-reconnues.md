# Plan — Les copies de fichiers ne sont plus recomptées à chaque synchro

> Décidé le 09/10/2026. Mot d'ordre donné par l'utilisateur : **optimisation et réactivité**,
> traitements courts. Entre deux options, on prend la plus légère.

## Le défaut

Quand un fichier a le même contenu qu'un document déjà indexé ailleurs, le pipeline le reconnaît
(même empreinte) et le saute — mais **n'enregistre jamais son emplacement**. À la synchro suivante
il est redécouvert, retéléchargé du NAS, reconnu, sauté. Constat en prod : 6 692 fichiers
recomptés « nouveaux » à chaque passage (toutes les heures), et 58 échecs par passage.

Faits vérifiés en base :

- rien n'interdit plusieurs fiches pour une même empreinte : 5 361 fiches sur 1 778 contenus existent déjà ;
- la page Doublons s'appuie sur ces fiches multiples ;
- 53 des 58 échecs : le code attend au plus UNE fiche par empreinte (`scalar_one_or_none`) ;
- les autres échecs (« transaction annulée ») : un texte trop gros fait déborder la colonne de
  recherche plein texte (`tsvector`, limite 1 Mo) ; l'enregistrement échoue, puis le traitement
  de l'erreur échoue à son tour sur la transaction déjà annulée. Vu sur `sgt-map.txt` (1,8 Mo).

## Step 1 — Corriger le plantage sur les contenus en plusieurs exemplaires

Dans `backend/services/extraction.py`, les deux recherches par empreinte (fichier, et sous-fichier
de ZIP) acceptent plusieurs fiches au lieu d'en exiger une seule.

Acceptance : un fichier dont le contenu existe déjà en 2 exemplaires est traité sans erreur ; un
test reproduit le cas et passe.

## Step 2 — Colonne `doublon_de` et migration à chaud

Ajouter `documents.doublon_de` (identifiant de l'original, effacé si l'original est supprimé) au
modèle et aux migrations de démarrage de `backend/database.py`, avec un index partiel. La
migration prend un verrou exclusif bref sur `documents` : elle doit rester reportable sans casser
le démarrage.

Acceptance : la colonne apparaît seule au démarrage sur une base existante ; le contrôle des
colonnes au démarrage ne signale rien ; aucune action manuelle en base.

## Step 3 — Enregistrer chaque copie comme une fiche liée à l'original

Pour les fichiers venant d'une source surveillée (pas les dépôts manuels, qui gardent leur
dédoublonnage), créer une fiche au nouvel emplacement : texte, catégorie, tags et résumé repris de
l'original, lien `doublon_de`. Ni Tika, ni IA, ni embeddings. Une fois enregistrée, la synchro la
voit « inchangée » et ne la retélécharge plus.

Acceptance : la 2ᵉ synchro d'un dossier contenant des copies ne télécharge plus rien ; aucun
appel à Tika ni à l'IA pour une copie ; les vecteurs de recherche ne sont pas dupliqués.

## Step 4 — La recherche et la relance IA ignorent les copies

La recherche plein texte et la recherche par le sens renvoient l'original une seule fois. Le lot
« Relancer l'IA » ne remet pas les copies en analyse.

Acceptance : une recherche sur un texte présent dans un original et 3 copies renvoie 1 résultat ;
« Relancer l'IA » ne compte aucune copie.

## Step 5 — Dire « copies reconnues » dans le récapitulatif de synchro

Le récapitulatif distingue les vraies nouveautés des copies : « +12 nouveaux · 6 692 copies
reconnues », dans le résultat de la tâche et sur la ligne de la source.

Acceptance : après synchro d'un dossier de copies, « nouveaux » vaut 0 et « copies » vaut leur
nombre ; la ligne rouge d'échec n'apparaît plus pour ces fichiers.

## Step 6 — Plafonner les textes géants

Un texte au-delà de 800 000 caractères est tronqué avant enregistrement, avec une trace dans les
métadonnées du document. Cela supprime les échecs « transaction annulée » et évite des heures
d'embeddings sur des fichiers de codes ou de journaux.

Acceptance : un fichier texte de 2 Mo est indexé sans erreur, marqué tronqué ; un document de
400 000 caractères n'est pas touché.

## Step 7 — Montrer qu'une fiche est une copie

Dans la fiche document et dans l'arbre « Parcourir », une mention « copie de … » avec le chemin de
l'original.

Acceptance : une copie affiche la mention et le chemin de son original ; un original n'affiche rien.

## Step 8 — Vérifier sur une pile jetable

Tests unitaires de chaque étape, puis parcours réel sur PostgreSQL jetable : migration sur base
existante, deux synchros successives d'un dossier contenant des copies, recherche.

Acceptance : suites backend et frontend vertes ; 2ᵉ synchro sans téléchargement ; recherche sans doublon.

## Step 9 — Livrer et documenter

CHANGELOG, ROADMAP, CLAUDE.md (piège des copies et du texte géant), puis livraison par le rail
habituel avec les étapes applicatives.

Acceptance : la prod sert la version, vérifiée par `verifier-deploiement.ps1` ; le compte rendu
liste l'étape applicative (la première synchro retélécharge une dernière fois les copies).

## Hors périmètre

- Dédoublonner les fichiers sur le NAS (rôle de la page Doublons, action de l'utilisateur).
- Reconnaître une copie sans la télécharger : il faut son contenu pour calculer son empreinte.
