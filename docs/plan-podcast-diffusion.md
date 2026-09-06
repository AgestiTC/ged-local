# Plan — Écouter un podcast depuis un dossier, sur une enceinte de la maison

> **Statut : plan validé sur le principe (Thomas, 06/09/2026), NON codé.**
> Décision préalable actée en ROADMAP : **pas de lecteur intégré dans Matothèque.** On n'écoute
> pas un podcast devant sa GED. Matothèque **catalogue** et **envoie** ; elle ne rejoue pas.

## Ce que ça donne, vu de l'utilisateur

Sur la fiche d'un podcast : un bouton **📡 Diffuser** (icône `Cast` de Lucide — le carré aux
ondes). Un clic ouvre la liste des derniers épisodes ; on en choisit un, on choisit une enceinte,
ça part. On continue à faire la vaisselle.

C'est le seul geste que ni Deezer ni une balise `<audio>` ne donnent : **le bon média dans la
bonne pièce, depuis l'écran où l'on classe.**

---

## Lot 1 — L'URL du flux (le socle, utile même seul)

Sans elle, rien du reste n'existe. Et elle a de la valeur **indépendamment de la diffusion** :
elle dit si l'émission publie encore, et elle alimente la veille.

- [ ] **Champ `flux_url`** sur `ressources` (TEXT nullable). Une colonne, pas une intégration.
  Migration `0006` + `ALTER … IF NOT EXISTS` au démarrage, comme `ressource.contenu`.
- [ ] **Saisie** dans le formulaire de ressource, visible seulement pour `type = podcast`.
- [ ] **Complétion assistée** : réutiliser le bouton « Compléter les liens manquants » (v1.81.0)
  avec une variante de prompt qui réclame l'**URL du flux RSS**, pas celle du site. L'import sait
  déjà compléter un champ vide sans écraser — il suffit d'étendre `RessourceIn`/`_nettoyer` à
  `flux_url`.
- [ ] ⚠️ **Ne pas confondre avec la veille.** `FluxRss` abonne un DOSSIER à un flux ; ici le flux
  décrit UNE ressource. Deux besoins distincts : ne pas réutiliser la table `flux_rss`, sinon
  chaque podcast catalogué déverserait ses épisodes dans la veille du dossier.

## Lot 2 — Lister les épisodes (sortie réseau confirmée)

- [ ] `GET /api/dossiers/ressources/{id}/episodes` — lit le flux, rend les 20 derniers :
  titre, date, durée, **URL de l'`<enclosure>`**, taille.
- [ ] **Confirmation avant appel**, exactement comme « Rafraîchir la veille » : encart disant ce
  qui sort (l'URL du flux) et ce qui ne sort pas (aucun document, aucun tag, aucun nom).
  Recensé dans Paramètres › « Demandes Mise à jour internet ».
- [ ] **Pas de cache persistant** dans un premier temps : on relit à la demande. Un cache
  supposerait de décider quand il périme, et personne n'a ce besoin aujourd'hui.
- [ ] `rss_service` sait déjà parser un flux : vérifier qu'il expose bien `<enclosure>`
  (url/type/length) — la veille ne s'en sert pas, il est possible qu'il les jette.

## Lot 3 — Diffuser sur une enceinte (Home Assistant)

**HA est joignable** : `http://homeassistant.local:8123` répond 200 (vérifié 06/09). Il est sur
le LAN, comme Ollama — on ne sort pas du périmètre local.

- [ ] **Réglages** (Paramètres › une nouvelle section « Maison / diffusion ») : URL de HA +
  **jeton de longue durée**, chiffré en base via `services/crypto` (comme BookStack et HF).
- [ ] `GET /api/maison/enceintes` → liste les entités `media_player` de HA (nom, état,
  disponibilité). Sert à peupler le sélecteur, et à ne proposer que ce qui existe vraiment.
- [ ] `POST /api/maison/diffuser` → appelle `media_player.play_media` avec l'URL de l'enclosure,
  `media_content_type: music`. **Un acte explicite, jamais automatique.**
- [ ] **Trois états dans l'UI**, pas deux (leçon du contrat `/status` d'AIGUILLEUR) : enceinte
  disponible / indisponible / **HA injoignable**. Le troisième n'est pas une panne d'enceinte —
  afficher « indisponible » enverrait chercher au mauvais endroit.
- [ ] **Icône `Cast`** (le carré aux ondes) — demandée explicitement.

## Ce qui reste hors périmètre, et pourquoi

- ❌ **Lecteur dans la page.** Voir ROADMAP : pas de reprise de lecture, pas de vitesse, pas
  d'arrière-plan sur mobile. On écrirait une mauvaise application de podcast.
- ❌ **API Deezer / Spotify.** Compte, identifiants à stocker, SDK propriétaire, abonnement pour
  la lecture — et l'historique d'écoute part chez eux. Un flux RSS ne demande rien de tout ça.
- ❌ **Téléchargement des épisodes.** Ce serait de l'archivage de médias, un autre métier, et le
  disque du LXC est déjà juste (incident du 21/07).

## Points à vérifier AVANT de promettre

1. **`<audio>` en contexte HTTP** — inutile pour le lot 3 (c'est l'enceinte qui lit), mais à
   trancher si l'on veut un jour une pré-écoute dans la page.
2. **L'enceinte doit joindre Internet** pour récupérer l'audio chez l'éditeur. Incompressible.
   À vérifier sur le VLAN où vivent les enceintes.
3. **Flux protégés / redirigés** : certains hébergeurs (Acast, Ausha) redirigent plusieurs fois
   avant l'audio. Vérifier que HA suit les redirections, sinon résoudre l'URL finale côté backend.
4. **Jeton HA** : portée minimale. Un jeton de longue durée HA donne accès à TOUTE l'API — c'est
   une limite de HA, pas de nous. À dire clairement dans l'écran de réglage plutôt que de le
   laisser croire restreint.

## Ordre et coût

| Lot | Valeur seule | Coût | Dépend de |
| --- | --- | --- | --- |
| 1 — `flux_url` | ✅ réelle (veille, émission vivante ou morte) | petit | — |
| 2 — épisodes | moyenne (voir sans quitter la fiche) | moyen | lot 1 |
| 3 — diffusion | ✅ c'est le but | moyen | lot 2 |

**Faire le lot 1 seul est déjà rentable.** Ne pas commencer par le 3 : sans URL d'épisode, il
n'aurait rien à envoyer.
