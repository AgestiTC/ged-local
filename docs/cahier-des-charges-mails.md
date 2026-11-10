# Cahier des charges — Gestion des mails

> **Ce document borne le projet.** Il dit ce que l'application doit faire, pour qui, et
> surtout **ce qu'elle ne fera pas**. Tout ajout postérieur au cadrage va dans le § 9, daté.
>
> **Statut** : brouillon de cadrage · **Cadré le** : 28/10/2026 · **Dernière évolution** : 10/11/2026
>
> Sources : `idées.txt` (6 idées) + capture de l'écran *Administration › Mail & Impression*
> (modèle d'interface pour les réglages mail).

---

## 1. Le problème

**Aujourd'hui** : les mails arrivent dans des boîtes séparées ; les pièces jointes sont
enregistrées et classées à la main ; les réponses récurrentes sont réécrites à chaque fois ;
rien ne signale qu'un mail important attend.

**Ça coûte** : *à chiffrer* — temps de tri et de classement des PJ, réponses en retard,
documents qui n'arrivent jamais dans la GED.

**Si on ne fait rien** : *à préciser.*

---

## 2. Qui s'en sert

| Rôle | Qui, concrètement | Ce qu'il vient y faire |
|---|---|---|
| Utilisateur | *à préciser* (techniciens, accueil ?) | Lire, répondre, valider les brouillons proposés par l'IA |
| Administrateur | Thomas | Comptes mail, règles de tri, modèles, connexion GED |

**Combien d'utilisateurs, à terme ?** *à préciser* — décide si les boîtes sont
partagées ou personnelles.

---

## 3. Ce que l'application doit faire

| # | Capacité | Indispensable au premier jour ? |
|---|---|---|
| 1 | **Client mail complet** : boîte de réception, lecture, rédaction, réponse/transfert, dossiers IMAP, recherche | oui |
| 2 | **Comptes mail paramétrables** (ajout dynamique : IMAP + SMTP, plusieurs boîtes) — écran inspiré de *Mail & Impression* | oui |
| 3 | **Modèles de mails** avec marqueurs (`[[MAIL_LOGO_ENTETE]]`…), bouton ↺ « revenir au défaut » | à trancher |
| 4 | **Pièces jointes** : téléchargement dans un dossier + **tri automatique** par règles | à trancher |
| 5 | **Dépôt des PJ dans la GED (Matothèque)** — OCR, classement et rangement y existent déjà | non (v2) |
| 6 | **Réponse automatique avec validation humaine** : l'IA locale rédige un brouillon, un humain valide avant envoi | non (v2) |
| 7 | **Notifications** : cloche 🔔 (même principe que Matothèque) | à trancher |

---

## 4. 🚧 Ce que l'application NE fera PAS

| Hors périmètre | Pourquoi | Reconsidéré si… |
|---|---|---|
| Dépôt d'APK Android / serveur de mises à jour | Sans lien avec les mails ; utile à d'autres applis (GecoGo) → **projet séparé** | — |
| Envoi automatique sans validation humaine | Risque d'une réponse erronée envoyée à un client | Des règles très encadrées (accusé de réception seul) seraient jugées sûres |
| IA en ligne (OpenAI, etc.) | Les mails contiennent des données clients → **IA locale obligatoire** | — |
| Héberger un serveur de messagerie (MX, antispam) | On se connecte aux boîtes existantes en IMAP/SMTP | — |
| Tri/OCR des documents refait dans ce projet | Matothèque le fait déjà | La GED n'est pas joignable / pas d'API |

---

## 5. Contraintes

| Sujet | Réponse | Conséquence technique |
|---|---|---|
| **Où ça tourne** | LXC « docker » de Matothèque (Proxmox), déployé comme Matothèque | Même chaîne de déploiement (`scripts/deployer.ps1`), cf. `CLAUDE.md` |
| **Exposition** | Comme Matothèque : accès LAN direct et proxy TLS `ged.tclement.fr` | Tout déploiement en production passe par **NPMplus** |
| **Données manipulées** | Mails clients, pièces jointes | **IA locale obligatoire** (Ollama via AIGUILLEUR) ; secrets IMAP/SMTP **chiffrés en base** ; **images distantes bloquées par défaut** (chargement = sortie Internet, et pistage) |
| **Volumétrie** | *à préciser* (nb de boîtes, Go de mails) | Cache local des en-têtes (décidé) ; relève 5 min si pas de réponse (D6, § 10) |
| **Systèmes à interroger** | Serveurs IMAP/SMTP (un fournisseur SMTP externe sur la capture), Matothèque, AIGUILLEUR | Chaque intégration = un connecteur isolé |
| **Disponibilité attendue** | *à préciser* (repoussé à l'étape 19) | |
| **Sauvegarde / perte acceptable** | Les mails restent sur le serveur IMAP ; on sauvegarde la base (réglages, règles, brouillons) | |
| **Contraintes réglementaires** | RGPD : données personnelles dans les mails | Durées proposées (D7, § 10) : corps 30 j, en-têtes 365 j, journal d'envoi 1 an, tous réglables |

**Paramétrage** (convention GecoGo/Matothèque) : tout réglage en base (`app_setting`),
éditable dans la page Paramètres, valeur par défaut au code avec ↺ pour y revenir ; les
mots de passe IMAP/SMTP dans une table de secrets chiffrés, jamais renvoyés par l'API.

---

## 6. Ce qui existe déjà

- **Remplace** : *à préciser* (Outlook ? Thunderbird ? webmail de l'hébergeur ?)
- **Cohabite avec** : Matothèque (GED), AIGUILLEUR (passerelle IA), l'écran *Mail & Impression* de l'appli existante (SMTP + modèles)
- **Reprise de l'existant** : rien à importer — les mails restent sur le serveur IMAP

---

## 7. Comment on saura que c'est réussi

| # | Critère | Comment on le constate |
|---|---|---|
| 1 | On lit et on répond à ses mails sans ouvrir d'autre client | Une semaine d'usage sans repasser par l'ancien outil |
| 2 | Une PJ de facture arrive dans le bon dossier sans action manuelle | Test sur 20 mails réels |
| 3 | Un brouillon IA n'est jamais envoyé sans clic de validation | Test + journal d'envoi |

---

## 8. Décisions et arbitrages

| Date | Décision | Motif | Écarté |
|---|---|---|---|
| 28/10/2026 | **Client mail maison complet** | Choix de l'utilisateur : une seule interface, intégrée à la GED et à l'IA | Webmail existant (Roundcube/SnappyMail) + couche assistant — plus rapide, mais deux interfaces |
| 28/10/2026 | Forge : **Gitea AgestiTC** — *caduque au 10/11/2026 : le code du module Mails est dans le dépôt de Matothèque* | Registre réel déjà utilisé (Matothèque) | GitHub AgestiTC, GitLab Geco |
| 28/10/2026 | Dépôt d'APK = **projet séparé** | Sans lien avec les mails | Module dans cette appli |
| 28/10/2026 | Documentation **mixte** | Aide courte dans l'appli + doc détaillée dans BookStack | Tout dans l'appli / tout dans BookStack |
| 10/11/2026 | **Intégré à Matothèque** (module Mails, même pile) ; prérequis : authentification active | Une seule interface, une seule authentification, une seule sauvegarde. Plan commun : `docs/plan-integration-rangement-mails.md` | Socle SEVE séparé |

---

## 9. Ajouts après le cadrage initial

| Date | Ajout | Demandé par | Impact sur l'existant | Ce qu'on repousse en échange |
|---|---|---|---|---|
| — | *(aucun ajout pour l'instant)* | — | — | — |

---

## 10. Questions ouvertes

| Question | Bloque | Défaut proposé | Statut |
|---|---|---|---|
| Combien d'utilisateurs, à terme ? (§ 2) | Étapes 2 et 13 (modèle de droits) | D1 : foyer seulement en v1 | Défaut proposé ; à trancher par Thomas **avant l'étape 2** |
| Boîtes personnelles ou partagées (support@, contact@) ? | Étape 13 | D3 : les deux (propriétaire + accès lecture ou envoi) | Défaut proposé ; à trancher avant l'étape 13 |
| Fournisseur des boîtes (hébergeur IMAP/SMTP) ? Microsoft 365 et outlook.com imposent OAuth2 ; Gmail accepte un mot de passe d'application (§ 3.2) | Étape 13 | D2 : `mode_auth` `mot_de_passe` ou `oauth2` ; OAuth2 seulement pour Microsoft 365 et outlook.com | À confirmer par Thomas **avant l'étape 13** |
| Volumétrie (nb de boîtes, Go de mails) | Étape 14 | D6 : relève 5 min réglable, pas d'IDLE, en-têtes seuls | Défaut appliqué si pas de réponse |
| Règles de tri des PJ : expéditeur, objet, type de fichier, ou IA ? (§ 3.4) | Étape 17 | D8 : règles explicites ; l'IA propose, l'humain valide | Repoussé à l'étape 17 |
| Modèles de mails avec marqueurs et ↺ (§ 3.3) | Étape 16 | Oui, modèles simples | Répondu |
| Cloche (§ 3.7) | Étapes 11 et 18 | Oui, via `notifier.py` | Répondu |
| Durées de conservation (RGPD, § 5) | Étape 14 | D7 : corps 30 j, en-têtes 365 j, journal d'envoi 1 an, tous réglables | Proposé ; à valider par Thomas |
| Quoi peut être envoyé ? (session ROADMAP du 13/09) | Étape 16 | Uniquement les pièces jointes choisies une à une par l'utilisateur ; jamais d'envoi automatique | Repoussé à l'étape 16 |
| À qui ? Carnet d'adresses fermé ou saisie libre (13/09) | Étape 16 | Non tranché : à étudier | Repoussé à l'étape 16 |
| Données chiffrées (n° de sécurité sociale, IBAN) exclues de tout envoi ? (13/09) | Étape 16 | Oui, exclues d'office | Repoussé à l'étape 16 |
| Confirmation de chaque envoi (13/09) | Étape 16 | Modale : destinataire, objet, pièces jointes ; trace dans le journal d'envoi, sans le contenu | Repoussé à l'étape 16 |
| Ce que ça remplace ; disponibilité attendue (§ 5 et § 6) | Étape 19 | — | Repoussé à l'étape 19 |
| Socle : seve (Python/FastAPI, dockerisé) ou même pile que Matothèque ? | Démarrage du code | Pile Matothèque, en module | **Répondu (10/11/2026)** |
| API Matothèque sans authentification (point ouvert de sa ROADMAP) | § 3.5 | Authentification active avant le module ; 409 si elle est éteinte | **Répondu (étape 2)** |
| Où ça tourne et exposition (LAN / Internet) ? | Déploiement (§ 5) | LXC de Matothèque ; LAN et proxy TLS, comme Matothèque | **Répondu (10/11/2026)** : vérifier à l'étape 13 que le LXC sort vers 993, 465 et 587 |
