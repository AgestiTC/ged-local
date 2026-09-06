# Plan — rendre les Dossiers trouvables depuis la GED

> **État : plan, rien n'est codé.** Demandé le 06/09/2026.
> Objectif formulé par l'utilisateur : *« intègre dossier et les éléments présents pour indexer
> dans la GED et permettre la proposition de podcasts présents dans ces dossiers »*.

---

## 1. Le problème

Matothèque tient aujourd'hui **deux catalogues qui ne se parlent pas** :

| | GED (`documents`) | Dossiers (`ressources`) |
|---|---|---|
| Contenu | des **fichiers** (PDF, DOCX, XLSX…) | des **pointeurs** (podcast, livre, article, association…) |
| Texte | `texte_extrait` par Tika | `note`, `contenu`, `resume_ia` saisis ou proposés |
| Recherche | hybride (full-text + vectorielle) | filtre client sur le titre, dans la page du dossier |
| Trouvable depuis la barre de recherche ? | oui | **non** |

Conséquence concrète : on cherche « sommeil du nourrisson » dans la GED, on obtient les PDF
enregistrés — et **rien** du dossier « Devenir parent », alors qu'il contient 25 podcasts dont
plusieurs épisodes traitent exactement de ça. La connaissance est là, elle n'est pas atteignable
par le geste naturel.

**Le gain visé** : la même recherche rend les documents ET les ressources, et un épisode de
podcast pertinent arrive avec son bouton « Diffuser » — on passe de « trouver » à « écouter en
cuisinant » sans détour.

---

## 2. Ce qu'on ne fera PAS, et pourquoi

Écrire d'abord les refus évite de les redécouvrir à mi-parcours.

### ❌ Transformer les ressources en `documents`

Tentant — tout serait réutilisé d'un coup. Mais la table `documents` est bâtie **autour d'un
fichier** : `chemin`, `extension`, `hash_sha256`, `taille_octets`, `texte_extrait`. Un épisode de
podcast n'a rien de tout ça. Il faudrait inventer un chemin et un hash, et alors **tout ce qui
agit sur un document se casserait ou demanderait un cas particulier** : aperçu, téléchargement,
détection de doublons, scan antivirus, réindexation, corbeille. On paierait ce mensonge dans
six fonctions pour l'économiser dans une.

### ❌ Rafraîchir les flux automatiquement pour tenir l'index à jour

Un index d'épisodes « toujours frais » suppose de relire les flux périodiquement, donc **des
sorties réseau sans clic**. C'est exactement l'invariant que le projet s'interdit : *le prompt
n'est jamais envoyé seul, il y a relecture, modification au besoin et validation utilisateur*.
La même règle vaut ici. L'indexation des épisodes est une **action déclenchée**, par dossier,
annoncée avant — jamais un cron.

### ❌ Indexer la description complète des épisodes dès la première version

Beaucoup de flux collent dans `<description>` un pavé de sponsors et de liens réseaux sociaux,
identique d'un épisode à l'autre. L'indexer noierait le signal. On commence par **le titre**,
on mesure, on étend seulement si les résultats sont pauvres.

---

## 3. L'architecture retenue

**Deux catalogues distincts, réunis au moment de la recherche.** Les `documents` restent des
fichiers, les `ressources` restent des pointeurs, et c'est la couche recherche qui fait
l'assemblage.

```
        requête « sommeil du nourrisson »
                     │
         ┌───────────┴────────────┐
         ▼                        ▼
   documents                ressources + épisodes
   (full-text + vecteurs)   (full-text + vecteurs)
         └───────────┬────────────┘
                     ▼
        fusion + score + TYPE du résultat
                     ▼
     ┌───────────────┴────────────────┐
     │ 📄 Rapport CAF 2026.pdf        │
     │ 🎧 EP327 — Le sommeil 0-3 ans  │ ← bouton « Diffuser »
     │ 📚 Le Nid (podcast)            │ ← lien vers le dossier
     └────────────────────────────────┘
```

### Modèle de données

**Table `episodes_podcast`** (nouvelle) — les épisodes lus dans un flux, conservés pour être
cherchables sans relire le flux à chaque requête :

| colonne | rôle |
|---|---|
| `id` | PK |
| `ressource_id` | FK `ressources` `ON DELETE CASCADE` |
| `guid` | identité de l'épisode dans le flux — **dédup** à la relecture |
| `titre`, `date_pub`, `duree`, `audio_url`, `page_url` | ce que porte l'`<enclosure>` |
| `indexed_at` | quand l'embedding a été calculé (NULL = pas encore) |

Contrainte d'unicité `(ressource_id, guid)` : relire un flux **complète** sans dupliquer.

**Table `embeddings`** (existante) — ajout de deux colonnes nullables `ressource_id` et
`episode_id`, avec une contrainte « exactement une des trois références est renseignée »
(`document_id`, `ressource_id`, `episode_id`). C'est la modification la plus économe : on
réutilise l'index vectoriel, le modèle, le service d'embedding et la recherche sémantique
existants, sans dupliquer la mécanique.

> **Alternative écartée** : une table `indexables` polymorphe qui absorberait aussi les
> documents. Plus propre sur le papier, mais c'est une migration de toute la GED pour un besoin
> qui ne le demande pas encore. À reconsidérer si un **troisième** type de contenu apparaît.

### Ce qu'on indexe

- **Ressource** : `titre` + `auteur` + `note` + `resume_ia` + `contenu` + `tags`. Court — un seul
  chunk dans l'immense majorité des cas, pas de découpage à prévoir.
- **Épisode** : `titre` seulement, préfixé du nom de l'émission (« La Matrescence — EP327 : … »)
  pour que le contexte survive à l'affichage d'un résultat isolé.

---

## 4. Les lots

### Lot 1 — les ressources deviennent trouvables *(le socle, utile seul)*

- [ ] Migration : `embeddings.ressource_id` + contrainte d'exclusivité.
- [ ] `ged_service.indexer_ressource(r)` — texte composé, embedding, écriture.
- [ ] Recherche : brancher les ressources dans le full-text ET le sémantique ; le résultat porte
      un `type_resultat` (`document` | `ressource` | `episode`) pour que l'UI sache quoi afficher.
- [ ] UI : carte de résultat distincte (icône du type de ressource, dossier d'origine, lien).
- [ ] Bouton **« Indexer ce dossier »** sur la page d'un dossier. Aucune sortie réseau ici : tout
      le texte est déjà en base, seul Ollama (local) est sollicité.

**Vérifiable** : chercher « matrescence » dans la GED rend la ressource et mène au dossier.

### Lot 2 — les épisodes de podcast

- [ ] Migration : table `episodes_podcast`.
- [ ] `POST /dossiers/ressources/{id}/episodes` **persiste** ce qu'il lit (dédup par `guid`),
      au lieu de le rendre puis l'oublier. La sortie réseau reste celle du clic existant.
- [ ] Bouton **« Lire les flux et indexer les épisodes »** au niveau du dossier — action groupée,
      **annoncée** : « va contacter N éditeurs de podcasts ; seules les URL des flux sortent ».
- [ ] File d'attente (`jobs`) pour les embeddings : ~500 épisodes × 25 podcasts = ordre de
      12 000 vecteurs. Doit **respecter la Pause IA** (Ollama est partagé avec FOULÉE) et
      s'interrompre proprement.
- [ ] Résultat de recherche « épisode » : titre, émission, date, durée, **bouton Diffuser** —
      l'enceinte est déjà connue de Home Assistant, le geste est complet depuis la recherche.

**Vérifiable** : chercher « sommeil » rend un épisode et il part sur l'enceinte en un clic.

### Lot 3 — la proposition

C'est la partie que l'utilisateur appelle « proposition de podcasts ». Elle ne se conçoit
qu'après les deux premiers lots, parce qu'elle s'appuie sur leur index.

- [ ] Depuis la **fiche d'un document** GED : « des ressources de vos dossiers parlent de ça »
      (recherche sémantique du résumé du document dans l'index des ressources).
- [ ] Depuis un **jalon du planning** (« préparer la valise de maternité », mois 8) : proposer les
      épisodes qui traitent du sujet, au moment où il devient d'actualité.
- [ ] ⚠️ **Rester une proposition.** Aucune lecture automatique, aucune diffusion déclenchée par
      le système : on suggère, l'utilisateur clique. Même logique que le résumé IA, qui est une
      proposition à valider et jamais une écriture directe dans la note.

---

## 5. Coûts et points de vigilance

| Sujet | Estimation / risque |
|---|---|
| Volume | 25 podcasts × ~500 épisodes = ~12 500 lignes + vecteurs. Négligeable pour Postgres. |
| GPU | ~12 500 embeddings courts. À la file, en respectant la Pause IA. Compter des dizaines de minutes, **pas** interactif. |
| Fraîcheur | L'index vieillit dès qu'un épisode sort. Assumé : on affiche la date de dernière lecture du flux, comme le planning affiche l'âge de ses données. |
| Bruit | Un podcast à 500 épisodes peut écraser les documents dans les résultats. Prévoir un **plafond par type** dans la fusion, ou un filtre « documents seulement ». À mesurer avant de le coder. |
| Ressources sans flux | 24 podcasts sur 25 n'ont pas encore d'URL de flux. Le lot 2 n'a d'effet visible qu'une fois ce champ rempli — à dire dans l'UI plutôt que de rendre une liste vide sans explication. |

---

## 6. Ordre recommandé

Le lot 1 apporte déjà un gain réel et ne dépend de rien. Le lot 2 est le plus coûteux mais c'est
lui que l'utilisateur a demandé nommément. Le lot 3 n'a de sens qu'après.

**1 → 2 → 3**, avec une livraison et un déploiement entre chaque : chacun est vérifiable seul.
