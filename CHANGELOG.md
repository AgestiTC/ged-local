# Changelog — Matothèque (ex-DocFlow AI)

Toutes les modifications notables de ce projet sont documentées ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [Semantic Versioning](https://semver.org/lang/fr/)

---

## [v1.104.4] — 2026-09-11 — Une page de scan n'est plus perdue au transport

### Corrigé
- **« Connexion perdue pendant la numérisation : malformed chunk footer »** — la panne de
  scan signalée. Le scanner envoie sa réponse en fragments (`Transfer-Encoding: chunked`) et
  **annonce une taille plus petite que ce qu'il écrit** : là où la norme attend un retour à
  la ligne, l'appareil a déjà mis la suite du JPEG. Les deux octets cités dans le message
  étaient de l'image.
  **La page avait bien été numérisée** — elle était perdue au transport, pas à la capture.
  Elle est maintenant récupérée : la requête est rejouée en **HTTP/1.0**, qui ne connaît pas
  le découpage, ce qui fait disparaître le problème à la racine plutôt que de le rattraper.

### Ce qui n'a pas été fait, et pourquoi
- **Le client HTTP n'a pas été assoupli.** Un parseur permissif accepterait aussi les trames
  douteuses de la GED, des connecteurs et d'Ollama. On n'affaiblit pas un mécanisme partagé
  pour un appareil : la tolérance est une **porte de secours locale**, empruntée uniquement
  quand la porte principale a claqué. Une vraie perte de connexion continue de se dire telle
  quelle.
- **Aucune page n'est acceptée sans contrôle.** Les octets récupérés sont vérifiés contre le
  format annoncé — début et fin. Un décodage indulgent peut rendre des octets plausibles mais
  faux, et ranger un fichier illisible dans la GED **en croyant avoir réussi** serait pire que
  l'échec d'origine : personne n'irait vérifier. Une page perdue qui se dit perdue vaut mieux
  qu'une page corrompue qui se tait.

### Notes
- Aucune étape applicative. Relancez simplement la numérisation.
- Si une page reste illisible, le message le dit désormais **avec son numéro** et invite à
  relancer cette page-là — au lieu d'abandonner tout le travail.
- Les tests montent un vrai serveur TCP qui rejoue le défaut : un faux transport HTTP ne
  reproduirait rien, puisque le défaut est *dans* le décodage HTTP.

---

## [v1.104.3] — 2026-09-11 — Un scan qui échoue le dit

### Corrigé
- **La fenêtre « Scanner » restait sur l'écran de départ après un échec**, le toast d'erreur
  disparu avant d'être lu. L'échec s'affiche maintenant dans la fenêtre, et la ligne de la
  boîte porte la cause réelle (ici : pages reçues du Canon mais refusées par le disque).

### Étapes applicatives
- Sur le LXC, `storage/uploads` appartenait à root depuis juillet : le worker (uid 10001) ne
  pouvait rien y écrire — ni les scans, ni un dépôt par glisser-déposer. Corrigé à la main
  (`chown -R 10001:10001 /opt/docflow/storage/uploads`) ; à refaire si le volume est recréé.

## [v1.104.2] — 2026-09-11 — Le contrôle des colonnes tourne vraiment

### Corrigé
- **Le contrôle des colonnes au démarrage échouait encore** (« name 'Base' is not defined ») :
  la 1.104.1 n'avait rétabli qu'un import sur deux. Vérifié cette fois dans les logs de prod.

## [v1.104.1] — 2026-09-11 — La boîte à scans ne dépend plus de la casse

### Corrigé
- **Boîte à scans : « scan » et « Scan » sont le même partage.** SMB ignore la casse, mais le
  chemin enregistré reprend le nom du partage tel qu'il a été indexé (`Scan`) ; une boîte
  configurée en `scan` restait silencieusement vide. La comparaison ignore désormais la casse.
- **Le contrôle des colonnes au démarrage tournait à vide** depuis la v1.98 (import manquant,
  « name 'text' is not defined » dans les logs) : il signale de nouveau les colonnes absentes.

## [v1.104.0] — 2026-09-11 — Le récapitulatif qu'on emporte

### Ajouté
- **Export du récapitulatif fiscal en PDF et en DOCX**, depuis *Administration → Aide à la
  déclaration*. On ne remplit pas sa déclaration devant Matothèque : on la remplit sur
  impots.gouv.fr, souvent sur un autre écran, parfois avec un papier à côté. Le document
  reprend **exactement** ce que l'écran affiche, dans le même ordre.
- **Un rappel de campagne** en tête de l'onglet : en mars « elle ouvre bientôt », d'avril à
  juin « elle est habituellement ouverte », en été « elle est probablement close, une
  rectificative reste possible ». Avec un raccourci vers l'année à déclarer quand ce n'est pas
  celle affichée.

### Ce que le document porte, et pourquoi
Sur un écran, une omission se rattrape en rechargeant ; sur un papier posé à côté du clavier,
elle est définitive. Figurent donc obligatoirement dans l'export :
- l'**avertissement** et la **date de vérification des cases** — un papier non daté se relit
  l'année suivante comme s'il valait encore ;
- la **confiance en toutes lettres** (« à saisir — Matothèque sait où, pas combien ») :
  l'infobulle de l'écran n'existe plus sur papier ;
- les **cases non tranchées**, avec leur question — c'est là qu'il reste à décider ;
- les **modules qui n'ont rien trouvé**. Un module silencieux se lit « je suis à jour ».

### Refus assumés
- **Aucune date limite n'est affirmée.** Elles varient selon le département et changent chaque
  année ; les écrire en dur produirait exactement l'erreur que cet onglet existe pour éviter —
  une information fausse *qui a l'air sûre*. On dit la saison, on renvoie au portail.
- **Pas de jalon de printemps**, contrairement à la formulation du plan. Un jalon s'ancre sur
  la date de terme d'un *dossier thématique* ; une déclaration de revenus n'appartient à aucun
  dossier, et l'y forcer aurait demandé d'inventer un dossier et une ancre. Le rappel est
  calculé à l'affichage : rien à stocker, rien à semer, rien qui puisse se désynchroniser.
- **Le récapitulatif n'est pas recalculé** pour l'export : il est construit depuis la synthèse
  déjà servie à l'écran. Deux chemins de calcul finiraient par diverger, et c'est le papier
  qu'on croirait.

### Notes
- Aucune étape applicative. L'export réutilise la chaîne PDF/DOCX existante : aucune
  dépendance nouvelle, aucun gabarit à maintenir.
- **Le plan fiscal est complet** : lots 1 à 4 livrés.

---
## [v1.103.0] — 2026-09-11 — Scanner directement dans la GED

### Ajouté
- **Page « Scans » : la boîte à scans.** Tout ce qui vient d'être numérisé y passe — capturé
  depuis Matothèque ou déposé dans un dossier de dépôt par le bouton de l'appareil — avec son
  état (numérisation, OCR, indexé, rangé), le profil que l'application **propose** d'après ce
  que l'IA a déjà lu, et un bouton pour ranger ou corriger avant que le fichier parte.
- **Profils de scan** (*Paramètres → Scanners & profils de scan*) : la réponse à « bon
  répertoire, bons tags ». Une destination (`smb://hote/partage/Factures/{annee}`), des tags
  qui **s'ajoutent** à ceux de l'IA sans les écraser, un modèle de nom (`{date}_{profil}` →
  `2026-09-11_facture.pdf`), des réglages scanner, et qui décide : rangé aussitôt indexé, ou
  sur confirmation. Le rangement passe par le déplacement journalisé de la réorganisation
  (annulable), et le document garde son identité : pas de nouvel OCR.
- **Scanner depuis Matothèque, sans pilote.** Un scanner réseau (Canon G3570 en Wi-Fi, ou un
  scanner USB partagé par NAPS2) se déclare par son adresse, se **teste** (l'application lit
  ce qu'il sait faire : vitre, chargeur, recto-verso, résolutions) et se pilote en eSCL — le
  protocole de scan d'AirPrint. Sur une vitre : « Ajouter une page » puis « Terminer » ; sur
  un chargeur, la liasse part d'un coup. La tâche est durable : on peut fermer la page.
- **Guide de mise en route** [docs/setup-scanners.md](docs/setup-scanners.md) : boîte à scans,
  profils types, Canon en eSCL, Brother ADS-1200 par le bouton Start (iPrint&Scan) ou via NAPS2.

### Refusé, et pourquoi
- **Pas de scan « depuis le navigateur »** : aucune API n'y donne accès aux scanners. C'est le
  backend qui parle à l'appareil, l'UI ne fait que choisir et suivre.
- **Pas de rangement silencieux** quand le profil n'est pas décidé à l'avance : l'IA propose,
  l'utilisateur confirme. Déplacer un fichier sur le NAS reste une action visible et annulable.
- **Pas de pilote Brother dans le conteneur.** Le Brother ADS-1200 est USB seulement ; il
  passe par le PC qui l'héberge. Le brancher sur le Proxmox (USB/IP → LXC → AirSane) est
  documenté dans le plan pour plus tard, pas construit.

### Étapes applicatives (rien ne se fait tout seul)
1. **Boîte à scans** : créer `Scans/` sur le NAS dans un partage indexé (synchronisation
   activée), puis saisir `smb://NAS-MATO/…/Scans` dans *Paramètres → Scanners & profils*.
2. **Profils** : en créer au moins un (Facture, Administratif…) avec sa destination SMB —
   l'hôte doit être une source SMB déclarée, c'est là que sont pris les identifiants.
3. **Canon** : réserver son IP, vérifier `curl http://<ip>/eSCL/ScannerCapabilities`, l'ajouter
   dans Scanners, **Tester**. Non vérifié sur l'appareil réel à cette livraison.
4. **Brother** : profil iPrint&Scan « scan vers dossier » sur le bouton Start, et/ou NAPS2
   « partager le scanner » sur le PC hôte, puis l'ajouter dans Scanners et Tester.

## [v1.102.0] — 2026-09-10 — Le journal alimente la déclaration

### Ajouté
- **Contributeur fiscal « emploi-domicile »** — l'onglet *Administration → Aide à la
  déclaration* lit désormais vos **contrats** et votre **journal mensuel**. C'était le dernier
  lot du plan fiscal, en attente depuis mai d'une réponse à une question précise : *d'où
  viennent les montants réellement versés ?* Le journal y répond.
- **La case est déduite du LIEU de travail, pas du métier.** Une garde chez l'assistante
  maternelle va en **7GA/7GB/7GC** ; la même garde chez vous va en **7DB**, avec les aides en
  **7DR**. C'est la confusion la plus fréquente du dispositif, et Matothèque connaissait déjà
  la réponse — le profil de chaque contrat porte son lieu depuis le premier jour.
- **Le total annuel versé**, décomposé (salaire, entretien, repas, kilomètres) pour pouvoir
  être **confronté ligne à ligne** à votre attestation fiscale.
- **Les liens dans les deux sens** : depuis le journal, « ce journal alimente votre aide à la
  déclaration » ; depuis une ligne de la déclaration, un retour direct vers l'écran du contrat
  — sur la bonne personne, pas seulement le bon dossier.

### Corrigé
- **Les sources non documentaires renvoyaient vers la GED.** L'écran envoyait tout
  identifiant vers `/ged?doc=…` : un contrat cité en source aurait ouvert une fiche document
  inexistante. Le contributeur fournit maintenant le chemin, et le bouton « Dater » — qui agit
  sur un document — ne s'affiche plus que sur des documents.

### Refus assumés
- **Aucun montant tant que les douze mois ne sont pas saisis.** Onze mois ressemblent à une
  année : c'est ce total-là qu'on recopierait. La ligne donne alors la case, et compte les
  mois manquants.
- **Le total affiché n'est pas le montant à déclarer, et la ligne le dit.** Les aides perçues
  (CMG, avance immédiate du crédit d'impôt) s'en déduisent, et l'**attestation fiscale**
  annuelle de Pajemploi ou du CESU donne le chiffre qui fait foi. Ce total sert à la
  **contrôler**, pas à la remplacer.
- **Le passage des 6 ans de l'enfant n'est pas deviné.** Il change de case en cours d'année ;
  Matothèque ne connaît pas cet âge et le signale au lieu de trancher.
- **Un contrat en brouillon, ou sans journal pour l'année, n'apparaît pas.** Une simulation
  affichée parmi des montants réels serait indiscernable d'un versement.
- **Pas de dossier dédié à la fiscalité** — question posée le 10/09, tranchée : l'aide à la
  déclaration est *transverse* (garde, ménage, dons, travaux), sa place est dans
  Administration. C'est le lien inverse qui manquait, et il est livré.

### Notes
- Aucune étape applicative. La question « combien d'enfants gardés hors domicile ? » est
  **partagée** avec le contributeur « pièces de la GED » : y répondre une fois suffit.

---

## [v1.101.0] — 2026-09-10 — Le journal mensuel, et un dossier fantôme nommé

### Ajouté
- **Journal mensuel du contrat** — une grille de douze mois sous la rémunération : heures
  faites, jours d'accueil, repas, kilomètres, absences. Ce sont exactement les cases du
  formulaire **Pajemploi / CESU**, qu'on cherchait jusqu'ici dans un carnet ou de mémoire.
  Chaque mois se coche **« déclaré »** une fois reporté, ce qui répond à la seule question
  qu'on se pose en ouvrant l'écran : *qu'est-ce que je n'ai pas encore fait ?*
- **Le total annuel du réalisé**, celui que veut la déclaration de revenus — et non le
  prévisionnel du contrat, qui n'a jamais été versé tel quel.
- **L'écart au contrat** : heures mensualisées prévues (× 12) face aux heures faites, avec un
  montant indicatif au taux du contrat. C'est la matière de la **régularisation annuelle**,
  jusqu'ici décrite dans le contrat sans que rien n'aide à la calculer.

### Corrigé
- **Le dossier au nom d'UUID qui restait en tête de l'arborescence GED.** La traduction
  « identifiant de source → nom donné par l'utilisateur » (v1.99.0) ne couvrait pas le cas
  d'une source **supprimée** : ses documents restent indexés, plus aucun libellé ne les nomme,
  et l'arbre retombait sur `fca9af54-…`. Il affiche désormais « Google Drive (source
  supprimée) » — le service **et** la raison, ce qui permet enfin de trancher entre réindexer
  et purger. L'arborescence n'avait aucun test : elle en a sept.
- **Deux décimales à l'écriture** dans le journal. PostgreSQL applique l'échelle de
  `Numeric(7,2)`, SQLite ne l'applique pas : la même saisie serait ressortie « 48.6 » en
  développement et « 48.60 » en production, et la divergence ne se serait vue qu'une fois
  déployée.

### Refus assumés
- **Toujours aucun bulletin de salaire, aucun net à payer, aucune cotisation.** Le bulletin
  est édité par Pajemploi ou le CESU à partir de la déclaration, et c'est lui qui fait foi ;
  en fabriquer un ici donnerait à la salariée deux versions de sa paie. Le montant d'un écart
  d'heures est une **estimation** au taux du contrat, et l'écran le dit.
- **Un mois vide n'est pas un mois à zéro.** Le journal refuse de les confondre : une année à
  moitié saisie est annoncée **partielle**, avec le décompte « n/12 saisis ». Sans cela, un
  total incomplet aurait été recopié tel quel sur une déclaration.

### Notes
- Aucune étape applicative : la table du journal se crée seule au démarrage du backend.
- Reste ouvert : brancher ce journal sur **l'aide à la déclaration d'impôts**, pour que le
  total annuel alimente les cases plutôt que d'être recopié.

---

## [v1.100.0] — 2026-09-10 — Le contrat accessible directement

### Ajouté
- **Onglet « Contrat »** à côté de « Visites et entretiens », avec une **liste déroulante**
  pour choisir la personne concernée. Le contrat n'était atteignable qu'en passant par les
  visites puis par la fiche — trois clics pour un document qu'on reprend souvent.
- Le choix de la personne est **mémorisé** (on revient au même contrat), et s'il n'y a qu'une
  seule personne suivie, elle est ouverte d'emblée : demander de choisir dans une liste d'un
  seul élément n'apporte rien.

### Notes
- **Aucune aide à la saisie de fiche de paie ne sera ajoutée, et c'est délibéré** : en
  particulier employeur, le bulletin est édité par **Pajemploi** (assistante maternelle) ou
  par le **CESU** (aide à domicile), à partir de la déclaration mensuelle — et c'est lui qui
  fait foi. Un bulletin fabriqué à côté serait au mieux inutile, au pire divergent du document
  officiel. Ce qui manque réellement — un **journal mensuel** pour remplir la déclaration —
  est inscrit au plan.

---

## [v1.99.0] — 2026-09-10 — Des dossiers nommés, et une aide à la déclaration qui s'explique

### Corrigé
- **L'arborescence des dossiers indexés affichait des identifiants internes.**
  `a1618c1a-3e14-4953-b3e6-445e428f65c1` désignait en réalité votre **Google Drive**, et
  `192.168.42.200` votre **NAS-MATO**. Les libellés existaient en base depuis toujours :
  seule la traduction manquait. Les racines portent désormais le nom que vous leur avez donné.
- **L'année d'un document est d'abord lue dans son NOM.** Sur la GED réelle, **65 597
  documents sur 66 078** portaient la date de leur *copie sur le NAS*, et 56 556 n'avaient
  aucune date de fichier : `2024 05 12 Attestation fiscale.pdf` était rangée en 2026, et
  toutes les années utiles répondaient « rien à reporter ». Ordre retenu : année confirmée à
  la main → **année lue dans le nom** → date du fichier en dernier recours.

### Ajouté
- **Un « rien trouvé » dit maintenant ce qui a été examiné.** L'écran affiche une explication
  — combien de documents rattachés à l'année ont été passés en revue, et pourquoi aucun n'a
  été reconnu. Sans ce chiffre, on ne peut pas distinguer une année réellement vide d'un
  filtre inopérant ; c'est précisément ce qui rendait le message précédent intrigant.
- Ces explications sont **séparées des formulaires** : une alerte rangée parmi les cases
  passerait pour un montant à recopier.

### Notes
- La nature `alerte` existait dans le vocabulaire du registre fiscal depuis sa création,
  sans avoir jamais servi. C'est son usage prévu.

---

## [v1.98.1] — 2026-09-10 — La rotation ajoutée visait le mauvais mécanisme

### Corrigé
- **Retrait de la clause `logging: json-file` de `docker-compose.yml`.** Deux raisons, et
  aucune n'était visible avant de regarder la production :
  - le démon Docker du LXC est configuré avec **`"log-driver": "journald"`**. Une clause
    `json-file` dans le compose **écrase** ce choix et déplace les journaux de systemd vers
    des fichiers par conteneur — un changement de comportement que personne n'a demandé,
    introduit par une ligne censée n'ajouter qu'un plafond ;
  - **ce fichier ne pilote pas la production**, qui utilise son propre
    `/opt/docflow/docker-compose.yml`. La rotation annoncée en v1.98.0 n'était donc **pas
    appliquée** — vérification faite après coup sur les conteneurs, qui affichaient toujours
    `journald`.
- Le commentaire qui remplace la clause explique les deux pièges, pour que la ligne ne soit
  pas réintroduite de bonne foi.

### Notes
- **La croissance est déjà bornée** : journald plafonne par défaut à 10 % du système de
  fichiers. Il occupe aujourd'hui 3,2 Go pour 493 Go de disque. Pour resserrer, c'est
  `SystemMaxUse=` dans `/etc/systemd/journald.conf` **sur l'hôte** — une décision
  d'exploitation, pas une clause applicative, donc hors de ce dépôt.
- Ce que la v1.98.0 apporte réellement et qui **fonctionne** : les traces allégées et le
  silence de `httpx`. Mesuré en production après déploiement : **zéro ligne
  `HTTP Request:`** sur trois minutes, contre plusieurs par seconde auparavant.

---

## [v1.98.0] — 2026-09-10 — Des journaux lisibles, et bornés

### Modifié
- **Une erreur ne produit plus 50 Ko de journal.** `dict_tracebacks` sérialisait, pour
  *chaque* frame de la pile, **toutes les variables locales** : la vraie ligne d'erreur se
  noyait au milieu d'objets SQLAlchemy tronqués, illisible à l'écran et impossible à
  copier-coller. On garde désormais ce qui sert au diagnostic — type, message, pile d'appel.
  C'est cette pile qui a permis de trouver les incidents de la veille ; les variables
  locales, elles, n'y ont jamais rien apporté.
- **`httpx` se tait quand tout va bien.** Il journalisait en INFO **chaque** requête
  sortante, or les contrôles de santé (Tika, Ollama, n8n, wiki, transcription) tournent en
  boucle : ces lignes représentaient l'essentiel du volume. En WARNING, un appel qui réussit
  ne dit rien — un appel qui échoue continue d'apparaître, ce qui est le seul cas utile.

### Notes
- Volume constaté : 5,5 Mo de journaux Docker, disque à 17 %. **Aucune purge n'a été faite** :
  elle aurait effacé l'historique pour traiter un symptôme.
- ⚠️ Une clause de rotation `json-file` avait aussi été ajoutée à `docker-compose.yml` —
  **retirée en v1.98.1**, voir ci-dessous : elle visait le mauvais mécanisme.

---

## [v1.97.3] — 2026-09-10 — La synthèse fiscale chargeait toute la GED

### Corrigé
- **« Aide à la déclaration » dépassait 30 secondes et le navigateur abandonnait.** Le
  contributeur `ged-pieces` faisait un `SELECT` **sans clause** et triait ensuite en Python :
  sur la GED réelle — **66 000 documents, 125 Mo de texte extrait** — il chargeait tout le
  corpus *et son texte* en mémoire à chaque ouverture de l'écran. Deux fois, même : une pour
  les pièces, une pour remplir la liste des années.
- **Le filtre par année passe désormais en SQL**, et seules les colonnes utiles sont
  chargées (`load_only`). Le texte extrait ne suit plus les lignes — il n'a jamais servi ici,
  et il représentait l'essentiel du volume.
- **Le sélecteur d'années ne parcourt plus rien** : il propose les années récemment
  déclarables, plus celles confirmées à la main sur une pièce (un `DISTINCT` sur une colonne).

### Notes
- Le défaut a été **trouvé grâce à l'écran d'erreur ajouté en v1.97.2** : « timeout of
  30000ms exceeded » affiché à l'utilisateur, au lieu d'une page blanche. Sans cette cause à
  l'écran, il aurait fallu remonter aux logs — c'est exactement ce que cette version-là
  visait.
- Deux tests verrouillent la régression : `texte_extrait` ne doit pas être chargé, et la
  liste des années ne doit pas dépendre du volume du corpus.

---

## [v1.97.2] — 2026-09-09 — Un écran qui échoue doit dire pourquoi

### Corrigé
- **Plus de page blanche quand un écran ne charge pas.** « Aide à la déclaration » et
  l'onglet Nounou faisaient `return null` en cas d'échec : l'utilisateur voyait un écran
  **vide** et une alerte rouge **sans cause**, sans savoir s'il devait attendre, recharger
  ou signaler. Les deux affichent désormais **la cause remontée par le serveur** (ou le code
  HTTP) et un bouton **Réessayer**.
- Le cas le plus fréquent est d'ailleurs bénin et se règle seul : un backend **qui redémarre
  encore** juste après un déploiement. L'écran le dit maintenant.

### Notes
- Diagnostic de l'incident : l'API répondait **200 sur les trois routes** (backend direct,
  proxy `:3003`, domaine HTTPS) au moment du signalement — c'est l'absence de cause affichée
  qui a rendu la panne indéchiffrable, pas l'API. Un message d'erreur sur lequel on ne peut
  pas agir est un défaut à part entière.

---

## [v1.97.1] — 2026-09-09 — Correctif : l'onglet « Visites » restait sur « Chargement… »

### Corrigé
- **Colonnes `photo` et `photo_accord` absentes en base.** La table
  `emploi_domicile_intervenants` existait depuis la v1.93.0, et **`create_all` ne fait que
  `CREATE TABLE`** : ajouter une colonne à un modèle dont la table existe déjà ne l'ajoute
  pas. Il manquait les `ALTER TABLE … ADD COLUMN IF NOT EXISTS` dans les migrations à chaud.
  Conséquence : le premier `SELECT` échouait, l'onglet restait sur « Chargement… » et
  affichait « Liste indisponible ».

### Ajouté
- **Contrôle du schéma au démarrage.** Le backend compare désormais les colonnes déclarées
  dans les modèles à celles réellement présentes en base, et **journalise bruyamment** les
  manquantes. Il ne corrige rien — volontairement : ajouter une colonne à la volée masquerait
  l'oubli de migration au lieu de le signaler.

  Ce contrôle existe parce qu'**aucun test ne pouvait attraper ce défaut** : la suite tourne
  sous SQLite, où toutes les tables sont recréées à neuf, donc le schéma y est toujours juste.
  L'écart n'apparaît qu'en production — et il n'apparaissait qu'au premier appel, des heures
  plus tard. Il se voit maintenant **dans les logs du déploiement**, là où on regarde.

---

## [v1.97.0] — 2026-09-09 — La photo d'une fiche, et l'Administration réorganisable

### Ajouté
- **Portrait sur la fiche d'une personne suivie.** Trois entrées, comme demandé :
  **glisser-déposer** sur la vignette, **import** classique, et **appareil photo** — ce
  dernier via `<input capture>`, qui ouvre l'application photo *du système* et fonctionne
  partout, y compris par la route HTTP.
- **Et une quatrième quand le navigateur le permet** : un **aperçu dans la page** (« Prendre
  ici »), disponible uniquement par la route **HTTPS**. Il est proposé après test de
  `window.isSecureContext` — jamais supposé, puisque le même utilisateur bascule entre
  `https://ged.tclement.fr` et l'accès LAN direct selon qu'il est chez lui ou en VPN.
- **Case « ajoutée avec son accord »** : le portrait d'une personne identifiée n'est pas
  notre donnée. Elle reste sur le serveur, n'est pas indexée, et **part avec la fiche**.
- **Administration : les sections se déplacent aussi**, sur **deux colonnes**. Les blocs
  (Médical, Gouv, Appli Inter, Enfants, Sécurité) se glissent l'un devant l'autre par leur
  titre. Leur ordre n'était modifiable nulle part : c'est celui de leur première apparition
  dans la configuration, et le déplacement regroupe le tableau — aucune colonne
  « position de section » à inventer, donc rien à tenir cohérent.

### Notes
- **La photo est redimensionnée dans le navigateur avant l'envoi** : 5 Mo deviennent
  ~150 Ko. La fiche se remplit debout, pendant la visite, au bout d'un VPN sur données
  mobiles — c'est la différence entre un envoi qui aboutit et un envoi qu'on abandonne.
- **L'orientation EXIF est préservée** via `createImageBitmap(..., 'from-image')` : un
  redimensionnement par canvas la perd, et donne un portrait couché systématiquement.
- **Le HEIC des iPhone est refusé avec un message utile**, pas accepté en silence : un
  fichier enregistré mais illisible par le navigateur ne se découvrirait qu'en rouvrant la
  fiche.
- **Le portrait est stocké hors GED** (`storage/intervenants/`). L'indexer ferait remonter
  un visage dans les résultats de recherche et l'enverrait en extraction, enrichissement IA
  et embeddings — pour rien. Un test vérifie qu'aucun document n'est créé.
- **Supprimer supprime le fichier**, y compris quand c'est la fiche entière qu'on supprime.
  Une donnée personnelle qu'on croit effacée et qui reste sur le disque est le pire des deux
  mondes.
- **L'envoi est séparé de la saisie** : une photo qui échoue n'emporte jamais les champs
  déjà remplis.
- Dans Administration, **une carte et un bloc ne se marchent pas dessus** : la carte étant
  elle-même déplaçable, c'est elle qui part quand on la saisit. Et les cartes repassent sur
  une colonne à l'intérieur d'un bloc — celui-ci ne fait plus que la moitié de la largeur.

---

## [v1.96.0] — 2026-09-09 — Contrat enrichi, Administration réorganisable

### Ajouté
- **Le contrat couvre enfin ce qu'il doit couvrir** : modification par **avenant écrit**,
  obligation de **discrétion**, **suivi médical du salarié** (régulièrement absent de ces
  contrats — pas facultatif pour autant), remise du **bulletin de salaire**, et
  **régularisation annuelle** en année incomplète. Le titre nomme aussi la nature du
  contrat : un CDI qui ne se dit pas laisse planer un doute que personne n'a de raison
  d'avoir.
- **Bouton « Remplir un exemple »** : des valeurs plausibles pour voir le contrat rendu d'un
  coup. Il ne remplit que les champs **encore vides** — c'est justement quand le formulaire
  est à moitié rempli qu'on veut voir à quoi ça ressemble, et un bouton qui effacerait le
  travail serait un piège.
- **Sources officielles** en pied de l'onglet (service-public.fr, Légifrance, Pajemploi),
  servies par l'API plutôt que codées dans l'écran.
- **Nombre de mineurs autorisés par l'agrément** dans la fiche et sur la carte. Le champ
  existait en base et le contrat l'imprimait déjà, mais aucun écran ne le proposait : il
  restait toujours vide.
- **Administration : quatre colonnes et des cartes déplaçables.** Chaque carte se glisse à
  la place voulue, **y compris vers une autre section**. Des flèches ◄ ► font le même
  travail — le glisser-déposer HTML5 ne fonctionne pas au doigt, et cette application se
  consulte aussi au téléphone.

### Notes
- **Le contrat dit lui-même ce qu'il est** : il reprend la structure attendue mais **ne
  reproduit aucun modèle officiel**. Un document qui *aurait l'air* officiel sans l'être
  serait plus dangereux que celui qui l'annonce — même raisonnement que pour les barèmes en
  dur et pour la carte écartée.
- Les **articles sont numérotés automatiquement** : le gabarit varie selon le profil et le
  régime, et un décalage manuel produisait un contrat renvoyant à « l'article 7 » quand ce
  n'était plus le bon.
- L'exemple ne contient **aucun montant réglementaire**, et les champs qui engagent
  (assurances, contacts d'urgence) portent « à compléter » : un exemple oublié doit produire
  un contrat visiblement inachevé, pas un contrat faux qui a l'air juste.
- **Le contexte sécurisé dépend désormais de la route d'accès** : `https://ged.tclement.fr`
  (proxy TLS) en offre un, `http://192.168.42.83:3003` — toujours actif — non. Les helpers
  `uuid()` et `copierTexte()` restent obligatoires : ils tentent l'API moderne d'abord et
  retombent sinon, donc ils profitent du HTTPS tout seuls. Les boutons « Copier » se testent
  **par la route HTTP**, où le défaut est visible.

### Corrigé
- **ROADMAP réconciliée avec la réalité.** Plusieurs items étaient cochés « à faire » alors
  qu'ils étaient en production (résolution de case par questions, millésime daté, correction
  de la barre latérale). Un plan qui annonce « à faire » pour du fait fait perdre confiance
  dans tout le reste du document. Les deux morceaux réellement manquants de la phase 2 — la
  **photo** et les **champs chiffrés** — sont désormais marqués comme tels.

---

## [v1.95.0] — 2026-09-09 — Nounou : le contrat, calculé et téléchargeable

### Ajouté
- **Onglet « Contrat »** dans la fiche d'un intervenant. C'est le geste que ni les fiches ni
  les entretiens ne rendaient : **produire un document opposable**.
- **Un formulaire qui calcule, pas qui fait saisir.** Le salaire d'une assistante maternelle
  est *mensualisé* — lissé sur douze mois, identique en février comme en juillet. Demander
  directement le montant reviendrait à faire faire le calcul par l'utilisateur, et c'est là
  que les contrats se trompent. Chaque montant s'affiche **avec sa formule** :
  `(4,20 € × 40 h × 52 semaines) ÷ 12 = 728,00 € par mois`.
- **Les deux régimes, jamais devinés** : année complète (52 semaines, congés compris) ou
  incomplète (semaines réelles, congés **en plus**). Mêmes entrées, **140 € d'écart par
  mois** — d'où le choix laissé à l'utilisateur, et expliqué.
- **Contrat éditable puis exporté en PDF ou DOCX.** Le texte se relit et se corrige avant
  export ; **régénérer refuse d'écraser** une version amendée sans confirmation, et un
  contrat **signé** est protégé. Les champs vides sortent en **`[À COMPLÉTER]`**.
- **Barème emploi à domicile** dans les Paramètres (SMIC horaire, minimum garanti, date de
  vérification), et **« Nom et prénom »** dans Vos coordonnées, pour l'en-tête du contrat.

### Notes
- **Aucun montant réglementaire n'est livré en dur.** Ces montants changent chaque année, et
  un chiffre périmé aurait l'air juste. Sans barème saisi, les calculs fonctionnent : seuls
  les **contrôles de plancher** sont désactivés — et l'écran affiche alors une alerte disant
  que le contrôle **n'a pas eu lieu**, plutôt que de se taire. Un écran muet se lirait
  « tout va bien ».
- *Exception assumée* : le ratio **0,281 du SMIC** est écrit en dur avec sa source
  (art. D. 423-9 du CASF). C'est un **ratio inscrit dans la loi**, pas un prix : il ne bouge
  pas avec l'inflation.
- **Les indemnités ne sont pas mensualisées** : dues par jour d'accueil réel, elles sortent
  en *estimation* et le disent — les présenter comme un montant fixe promettrait ce qui
  n'est pas promis.
- **Les heures au-delà de 45 h entrent dans le lissé à leur taux majoré**, sinon le salaire
  est sous-évalué toute l'année sans que rien ne le signale.
- Le contrat est **pré-rempli depuis la fiche** (agrément, adresse) : retaper ce que
  l'application sait déjà est le meilleur moyen d'y glisser une coquille.

### Modifié
- **Un seul rendu PDF, partagé** : le CSS et l'assemblage HTML passent dans
  `export_service.rendre_pdf()`. Deux rendus séparés auraient divergé au premier ajustement
  de style — et l'écart ne se serait vu que sur le papier signé.

### Pas encore fait
- **Dépôt du contrat dans la GED** (la colonne est prête, l'action reste à câbler) et
  **annexes** (autorisations, engagement réciproque, fiche de renseignements).

---

## [v1.94.0] — 2026-09-09 — Fiche contact : prénom, appeler, y aller

### Ajouté
- **Prénom** saisissable à la création d'une fiche comme à son édition. Il existait en base
  depuis le début, mais aucun écran ne le proposait.
- **Téléphone cliquable** : l'OS ouvre son composeur — application Téléphone sur mobile,
  Skype ou Teams sur PC. Plus rien à recopier au moment où l'on veut simplement appeler.
- **« Y aller »** : sur Android, l'adresse part vers **votre** application de navigation
  (Maps, OsmAnd, Organic Maps…), au choix. Ailleurs, un bouton **« Copier l'adresse »**.
- **Section « Vos coordonnées »** dans les Paramètres (adresse, code postal, ville,
  téléphone, email) : saisies **une fois**, pour **renseigner des documents** — en-tête d'un
  contrat de travail, courrier, formulaire administratif. Elles restent en base locale.

### ❌ Écarté — la carte des intervenants
Un onglet « Carte » avait été demandé puis **retiré le jour même** : *« trop de données perso
qui fuient »*. La raison est inscrite en ROADMAP pour ne pas la redécouvrir :

- **le géocodage** n'a pas d'équivalent local — chaque résolution enverrait **le domicile
  d'une personne identifiée** à un service tiers, une adresse confiée pour un entretien ;
- **les tuiles** ne sont pas une requête ponctuelle mais un **flux continu**, qui révèle la
  zone regardée, le zoom et le rythme de consultation.

Une confirmation d'accès Internet couvre une action, pas un flux ; et un cache de géocodage
réduit le nombre d'envois sans supprimer le premier — celui qui contient l'adresse.

### Corrigé
- **Le bouton « Y aller » ne renvoie plus vers openstreetmap.org** là où `geo:` n'est pas
  supporté : ce repli envoyait l'adresse à un site tiers, exactement ce qu'on refuse par
  ailleurs. Un test verrouille désormais ce point pour tous les navigateurs.
- **Un numéro annoté n'est plus mal composé.** « 06 12 34 56 78 (après 18 h) » — ce qu'on
  écrit vraiment pendant un appel — produisait le lien `tel:061234567818` : les chiffres de
  l'annotation collés au numéro. Un mauvais numéro appelé est pire qu'un lien absent.
  *(Défaut trouvé par un test, pas à l'usage.)*

---

## [v1.93.1] — 2026-09-09 — Correctif : le backend ne démarrait plus

### Corrigé
- **`server_default` d'une colonne JSONB écrit comme une chaîne** (`"'{}'::jsonb"`) :
  SQLAlchemy ré-échappe les apostrophes, PostgreSQL reçoit `'''{}''::jsonb'` et refuse le
  `CREATE TABLE`. Le backend s'arrêtait au démarrage et le frontend rendait **502** — la
  v1.93.0 n'a jamais été servie.
- **Et l'autre moitié du même piège**, découverte en corrigeant la première : `text()` émet
  du **SQL brut**, donc un cast `::jsonb` part tel quel — et SQLite, sur laquelle tourne
  toute la suite de tests, ne sait pas le lire. La forme qui marche des deux côtés est
  `server_default=text("'{}'")` : PostgreSQL coerce le littéral vers le type de la colonne.

### Ajouté
- **Deux tests de garde** (`tests/test_modeles_server_default.py`) qui relisent les modèles
  et refusent ces deux formes. Ils ne testent pas un comportement mais une **écriture** :
  aucun test fonctionnel ne pouvait attraper le bug, puisqu'il n'existe que sous PostgreSQL
  et que la suite tourne sous SQLite. C'est le seul moyen de le voir avant le déploiement.

---

## [v1.93.0] — 2026-09-09 — Nounou : les visites, et une checklist par entretien

### Ajouté
- **Section « Visites et entretiens »** dans l'onglet Nounou : les personnes qu'on envisage
  d'employer, et les rencontres qu'on a avec elles. La liste montre ce qu'on vient y
  chercher — qui reste à appeler, qui on voit jeudi, et **quel agrément est expiré**.
- **Une personne = N entretiens** (appel, visite, seconde visite, point de suivi), chacun
  avec son rendez-vous, son statut de suivi, son impression générale et **sa propre
  checklist**.
- **Un second entretien peut reprendre les réponses du précédent** : on ne repose pas
  quarante questions, on met à jour ce qui a changé. L'entretien d'origine n'étant jamais
  modifié, l'écran marque **« a changé »** sur les avis qui ont bougé.
- **Création par le nom seul** : une fiche à moitié remplie pendant un premier appel vaut
  mieux qu'un formulaire qu'on renonce à valider. Le reste s'ajoute au fil des rencontres.
- **Les liens rangés dans « Administration → liens » remontent automatiquement** dans les
  sources officielles du module, dédoublonnés par URL et marqués « à vous ». Rien à
  ressaisir : ajouter un lien pertinent dans Administration le fait apparaître ici.

### Notes
- **La checklist appartient à l'ENTRETIEN, pas à la personne.** Le plan initial la rangeait
  sur la candidate ; c'est faux, et ça se voit dès le deuxième rendez-vous : certaines
  réponses changent, et les écraser ferait disparaître l'information la plus utile —
  **ce qui a bougé entre les deux visites**.
- **L'intervenant est la même ligne du premier appel à la fin du contrat** ; seul son statut
  évolue. Deux tables « candidates » et « salariées » obligeraient à ressaisir une identité
  déjà connue **au moment où l'on signe**.
- **Aucun bouton « Enregistrer »** : chaque réponse part seule, au fil de la saisie. L'écran
  se remplit debout, pendant la visite, souvent au bout d'un VPN sur données mobiles — perdre
  vingt réponses sur une coupure serait le scénario le plus probable et le plus coûteux.
- **L'impression générale (1 à 5) est séparée de la grille** : une checklist parfaitement
  remplie ne fait pas une bonne rencontre.
- Les questions portent désormais une **clé stable**, qui indexe les réponses. Une clé
  dérivée du texte se perdrait à la première reformulation ; une clé dérivée du rang se
  décalerait à la première insertion. Les deux effaceraient des réponses sans bruit.

### Détails techniques
- Nouvelles tables `emploi_domicile_intervenants` et `emploi_domicile_entretiens`, créées au
  démarrage du backend — **aucune action manuelle en base**.
- La suppression des entretiens avec leur fiche est **explicite** et non confiée au
  `ON DELETE CASCADE` : un test a montré que la cascade dépend des clés étrangères,
  désactivées sous SQLite — le comportement aurait différé entre les tests et la production.

---

## [v1.92.0] — 2026-09-09 — Devenir parent : l'onglet « Nounou » (savoir)

### Ajouté
- **Onglet « Nounou » dans « Devenir parent »**, à côté de Planning. Troisième geste du
  dossier, après *lire* (Ressources) et *se situer* (Planning) : **devenir particulier
  employeur**. Cette version couvre le **savoir** — elle ne touche rien et n'écrit rien.
- **Fiche « Quel guichet ? »**, en premier délibérément : tableau **lieu × âge × service** →
  **Pajemploi** (assistante maternelle chez elle, garde d'un enfant de moins de 6 ans chez
  vous) ou **CESU** (ménage, jardinage, soutien scolaire). Se tromper de guichet ne bloque
  rien : ça fait juste **perdre une aide**, sans que rien ne le signale. Avec les confusions
  classiques — CESU déclaratif ≠ CESU préfinancé, et **emploi direct / mandataire /
  prestataire**, qui décide si vous êtes employeur ou simple client.
- **Fiche « Qui doit quoi »** : cinq vis-à-vis employeur / salarié — avant le premier jour,
  au quotidien, la paie, les absences, la fin du contrat — puis **ce qui se prépare au
  contrat** et non au moment où ça arrive (la fin, les absences, l'année complète ou
  incomplète, les autorisations).
- **Fiche « Comparer les modes de garde »** : assistante maternelle, crèche, micro-crèche,
  MAM, garde à domicile, garde partagée.
- **Checklist d'entretien**, 9 groupes, du premier appel jusqu'à *« est-ce que je me vois lui
  confier mon enfant, tous les jours, pendant deux ans ? »*. **Chaque question porte son
  pourquoi** : sans lui elle se récite, avec lui elle s'adapte.
- **Capacités déclarées sur un dossier** (`dossiers_thematiques.modules`) : c'est le dossier
  qui déclare porter un module, avec son profil. Déclarable sur **n'importe quel** dossier.

### Notes
- **L'onglet n'est pas conditionné au slug du dossier.** Un `if slug == "devenir-parent"`
  aurait été à refaire dès le deuxième dossier concerné (« Employer chez soi », profil aide
  ménagère) — une dette contractée en sachant déjà quand on la paierait.
- **Le module s'appelle `emploi-domicile`, pas `nounou`** : « Nounou » n'est que le libellé
  de son premier profil. Assistante maternelle et aide ménagère relèvent de la **même
  convention collective** — même contrat, mêmes obligations ; seuls changent le lieu, le
  guichet et l'aide. Un test le vérifie : s'il tombait, l'architecture serait à revoir.
- **Aucun montant n'est écrit dans les fiches, et un test le vérifie.** Les barèmes changent
  chaque année : « indemnité d'entretien : X € » serait faux en janvier sans que rien ne le
  signale, et un contrat bâti dessus aurait l'air juste. Les fiches décrivent les
  **mécanismes**, portent leur date de vérification et **vieillissent visiblement**.
- **La checklist n'a pas de cases à cocher** : elle s'imprime et se remplit au stylo. Des
  cases qui oublieraient tout au changement de page seraient pires que rien — la saisie par
  candidate arrive en phase 2, avec sa table.
- **Le rendu est générique** : le serveur envoie des blocs typés, l'écran les rend sans
  connaître leur sujet. Ajouter une fiche ne touchera aucune ligne de frontend.

### 🔧 Étape applicative après mise à jour
- **Ouvrir « Devenir parent » et réinstaller le pré-rempli** pour que le dossier existant
  gagne la capacité — donc l'onglet. Le seed n'écrase rien et n'ajoute que ce qui manque.
  Un dossier créé après la mise à jour l'a d'emblée.

---

## [v1.91.0] — 2026-09-09 — Aide à la déclaration d'impôts : dans quelle case reporter quoi

### Ajouté
- **Administration gagne un onglet « Aide à la déclaration »**, qui répond à une seule
  question : *« j'ai payé ça — dans quelle case je le mets ? »*. Personne ne bloque sur le
  montant versé à sa nounou, il est sur les relevés Pajemploi ; on bloque sur **7GA ou 7GB**,
  sur l'aide perçue qui se reporte en **7DR**, et sur le fait que ces cases ne sont pas sur la
  2042 mais sur une annexe (**2042-RICI**) dont beaucoup ignorent l'existence.
- **L'écran est rangé comme le formulaire, pas comme les modules** — on remplit une déclaration
  en la descendant. Le module d'origine reste sur la ligne comme une provenance.
- **Résolution de case par questions** : une ligne peut s'afficher **sans case**, avec la
  question qui tranche (rang de l'enfant, type d'organisme). La réponse est mémorisée **pour
  l'année**, s'efface, et les lignes à trancher **remontent en tête** — c'est là qu'il y a
  quelque chose à faire.
- **Les pièces déjà indexées sont rassemblées** (garde d'enfant, services à la personne, dons) :
  ces papiers existent, ils sont dans la GED, et on les cherchait un par un chaque printemps.
  La **ligne compagne 7DR** est ajoutée d'office : oublier les aides perçues fausse la
  déclaration au premier euro.
- **Bouton « Dater » sur chaque pièce** : l'année déduite de la date du fichier se corrige. Les
  années trouvées **dans le texte déjà extrait** sont proposées, **chacune avec l'extrait qui
  la justifie** — voir *pourquoi* on propose 2025 est ce qui sépare une aide d'une devinette.
  L'année confirmée (`documents.annee_fiscale`) prime définitivement, et se retire.

### Notes
- **Aucun montant n'est calculé ni lu dans un document**, ni par l'IA ni par une expression
  régulière : un total mal lu sur une attestation est une erreur *indétectable*, recopiée telle
  quelle. L'écran dit **où**, l'utilisateur saisit **combien**.
- **Aucune règle de case ne vient de l'IA** : cases, formulaires et arbres de décision sont
  écrits en dur et **datés** (`services/fiscalite/millesime`). L'écran affiche « cases vérifiées
  le … » et **vieillit visiblement** au-delà d'un an — une case juste l'an dernier et fausse
  cette année serait recopiée sans hésiter.
- **Aucune sortie réseau**, y compris pour la datation : la date d'une attestation est dans
  l'attestation. Poser une confirmation de sortie Internet devant une lecture locale
  apprendrait qu'elle ne veut rien dire.
- **Ajouter un module fiscal ne touche aucune ligne d'interface** : l'onglet affiche ce qu'un
  registre de contributeurs lui rend. Un onglet écrit en dur serait devenu faux par omission au
  premier oubli — le pire état pour un écran fiscal, puisque rien n'y signale ce qui manque.
- **`LigneFiscale` refuse à la construction un montant sans source** : un chiffre non traçable
  ne peut pas atteindre l'écran, donc pas une déclaration.

### Corrigé
- **La barre latérale n'affichait « Administration » que si des liens externes existaient.**
  L'onglet fiscal aurait été livré et **invisible** pour une raison sans rapport avec lui.
  Condition passée à `adminCount > 0 || fiscaliteDispo` — leçon v1.84.3, déjà payée une fois.

### Documentation
- Plans de conception : [docs/plan-nounou.md](docs/plan-nounou.md) (module **emploi à domicile** —
  onglet « Nounou », contrat, CESU vs Pajemploi) et
  [docs/plan-aide-declaration-impots.md](docs/plan-aide-declaration-impots.md).
- `CLAUDE.md` : `navigator.mediaDevices` rejoint les API absentes en contexte non sécurisé —
  **un VPN chiffre le tunnel, il ne rend pas le contexte sécurisé**. Pour photographier depuis un
  téléphone : `<input type="file" accept="image/*" capture="environment">`.

---

## [v1.90.0] — 2026-09-07 — Emporter un événement du planning dans son propre agenda

### Ajouté
- **L'export est proposé au moment de l'ajout.** La modale ne se ferme plus d'un coup :
  elle confirme l'enregistrement et propose de télécharger l'événement au format `.ics`,
  prêt à importer dans Google Agenda, Outlook ou Apple Calendrier. C'est le seul moment où
  le geste a du sens — le proposer plus tard revient à ne pas le proposer.
- **Export d'UN SEUL événement** (`GET /api/dossiers/jalons/{id}.ics`) : après avoir noté un
  rendez-vous, on veut le mettre dans son agenda, pas y déverser soixante-sept repères de
  grossesse. Le fichier porte le **même `UID`** que dans l'export complet — si le planning
  entier a déjà été importé, réimporter l'événement seul **met à jour sa copie** au lieu
  d'en créer une seconde.
- **Bandeau « changements non exportés »** : le planning compte les événements ajoutés ou
  modifiés depuis le dernier export et propose de le refaire. L'agenda de l'utilisateur est
  une copie : sans ce rappel, un planning modifié cinq fois se décale en silence de l'agenda
  qui lui sert vraiment. Cocher un jalon ou écrire une note personnelle ne déclenche rien —
  ni l'un ni l'autre ne figure dans le `.ics`.
- **Les suppressions sont comptées à part, et dites comme telles** : un réimport `.ics`
  ajoute et met à jour, il n'efface rien. Le bandeau annonce donc qu'un événement retiré du
  planning doit être retiré à la main de l'agenda extérieur.

### Notes
- **Aucune donnée ne part vers un service extérieur** : ni lien « Ajouter à Google Agenda »
  (qui ferait transiter titre et date par une URL Google), ni abonnement par URL (qui
  supposerait d'exposer Matothèque sur Internet). Un fichier, téléchargé, que l'utilisateur
  dépose lui-même où il veut.
- L'export passe par un **vrai lien `<a download>`**, jamais par un téléchargement piloté en
  JavaScript : c'est la seule voie fiable quand l'application est servie en HTTP.

### Corrigé
- **Les surcharges de configuration fuyaient d'un test à l'autre** (`runtime_config` garde
  ses valeurs dans un dictionnaire de module) : un test qui réglait la date du terme la
  laissait en place pour tous les suivants, et un test vérifiant le comportement « sans
  terme » passait ou échouait selon son rang d'exécution. Remise à zéro automatique.

## [v1.89.0] — 2026-09-07 — Inscrire un vrai rendez-vous dans le planning, en une phrase

### Ajouté
- **Bouton « Ajouter un événement »**, en tête du planning et visible dans les DEUX vues.
  L'ajout existait déjà, mais derrière un `+` gris de 14 px posé dans l'en-tête de chaque
  mois de la vue Cartes — invisible, absent de la vue Calendrier, et il ne demandait qu'un
  titre. La modale demande maintenant tout ce qui fait un événement : date, créneau,
  catégorie, détail, échéance, lien.
- **Bouton IA « Remplir avec l'IA »** : on écrit « entretien prénatal à la maternité le
  vendredi 25 septembre de 13h à 14h », l'**IA locale** (Ollama) en tire le titre, la
  catégorie, la date et le créneau, et **remplit le formulaire**. Elle n'enregistre rien —
  un rendez-vous faux dans un agenda est pire qu'un rendez-vous absent, donc la validation
  reste humaine. `POST /api/dossiers/{ref}/jalons/analyser` (aucune écriture en base).
- **Bouton « Dater depuis ma note »** dans la fiche d'un jalon : une note du genre
  « rendez-vous pris le 25 septembre à 13h » reste sinon enfermée dans du texte, invisible
  dans le calendrier. Le bouton en sort la date et l'heure, et ouvre la modification pour
  confirmation. Le titre du jalon, lui, n'est jamais remplacé.
- **Les jalons peuvent porter une vraie date et un créneau** (`date_reelle`, `heure_debut`,
  `heure_fin` — migration `0008_jalon_date_reelle`). C'est la distinction qui manquait :
  le **repère** (« vers le 4ᵉ mois », posé au début de sa fenêtre, estompé) n'est pas le
  **rendez-vous pris** (à son jour, avec son heure). Le mois se déduit de la date — le
  formulaire ne le demande plus dès qu'une date est saisie, et déplacer un rendez-vous le
  range tout seul dans le bon mois.
- **Export iCalendar horodaté** : un créneau saisi sort en `VEVENT` daté et `TRANSP:OPAQUE`
  (il occupe l'agenda) ; les repères de période restent en journée entière et transparents.
  Heures écrites en **temps local flottant** (RFC 5545 §3.3.5) : 13h à la maternité reste
  13h dans l'agenda qui importe, quel que soit son fuseau. Sans heure de fin, une heure est
  comptée (un événement de durée nulle est rejeté par plusieurs agendas).
- **La vue Calendrier et l'export ne réclament plus la date du terme** dès qu'un rendez-vous
  est daté : celui-ci ne se calcule pas, il est connu.

### Corrigé
- **Les tests d'intégration du planning ne s'exécutaient plus** : la fixture `dossier`
  ouvrait le client httpx que chaque test rouvrait ensuite (`Cannot open a client instance
  more than once`) — 12 tests en échec, dont tout l'export iCalendar. La fixture ouvre
  désormais son propre client.

## [v1.88.0] — 2026-09-07 — Comparer sans avoir d'abord fabriqué un tableau Excel

### Ajouté
- **Le template Excel du Tableau comparatif devient FACULTATIF.** Jusqu'ici il était exigé par
  le front (`Sélectionnez un template Excel`) *et* par l'API (`template_id` obligatoire, 400 si
  la ligne 1 était vide) : pour comparer trois contrats d'assurance, il fallait d'abord
  fabriquer un classeur à la main. Trois façons d'obtenir les colonnes désormais, dans une
  étape **« Critères de comparaison »** : **l'IA les propose** (et on les corrige avant de
  lancer), **on les saisit** un par ligne, ou **on fournit un template** — le seul mode qui
  exige encore un fichier, puisque ce sont ses en-têtes qui font les colonnes. Sans rien
  fournir du tout, les critères sont déduits des documents au début du traitement
  (`POST /generate/compare/criteres`, et déduction en tâche de fond avec repli générique).
- **Le format de sortie se choisit APRÈS la génération** : `Excel` · `PDF` · `Word` ·
  `Markdown`, plus « Copier ». Les valeurs extraites sont conservées côté serveur, donc
  changer de format **ne relance jamais l'IA** — c'était le vrai coût, pas la mise en forme.
  Fini le téléchargement automatique du .xlsx imposé.
- **Le tableau s'affiche à l'écran** dès la fin de l'analyse, au lieu d'atterrir dans un
  fichier qu'il fallait ouvrir pour savoir ce qu'il contenait.
- **Synthèse IA des écarts** (activée par défaut) : le tableau dit *ce que contient* chaque
  contrat, pas *où ils diffèrent*. Une passe finale liste les différences concrètes, reprise
  dans les quatre formats.
- **Reprise après redémarrage** : `GET /generate/compare/resultat/{id}` et le téléchargement
  relisent `jobs.resultat` en base quand le cache mémoire a été perdu.

### Corrigé
- **🔴 `openpyxl` n'était déclaré NULLE PART** — ni dans `requirements.txt`, ni dans l'image
  (vérifié : `pip list` ne le connaît pas). Or tout le mode comparatif repose dessus. L'import
  étant fait dans un `try/except` silencieux, l'absence se manifestait en « Le template ne
  contient aucune colonne en ligne 1 » — un message qui accuse le fichier de l'utilisateur.
  La détection des champs `.xlsx` à l'upload de template était muette de la même façon.
  Dépendance ajoutée (`openpyxl==3.1.5`) : **une reconstruction de l'image est nécessaire**,
  un simple `docker compose pull` ne suffira pas.
- **Export Word du comparatif** : un vrai tableau Word, là où l'export DOCX générique aurait
  recraché les `| pipes |` du Markdown en texte brut (il ne sait pas rendre les tableaux).
- **Le nom du candidat n'apparaissait dans aucune colonne** du .xlsx (seules les valeurs des
  critères étaient écrites). Le classeur généré sans template porte désormais une première
  colonne « Candidat / Société ».

### Détail
- Orientation volontairement différente selon le format : le `.xlsx` garde la convention
  tableur (1 ligne = 1 candidat, triable/filtrable), tandis que `md`/`pdf`/`docx` transposent
  (1 ligne = 1 critère, 1 colonne = 1 candidat) — c'est ce sens-là qui se lit en portrait
  quand les critères sont nombreux et les candidats peu.

---

## [v1.87.0] — 2026-09-06 — Chercher dans 500 épisodes, et cesser d'être invisible au doigt

### Ajouté
- **Champ de recherche sur la liste des épisodes.** Un catalogue de 500 titres ne se parcourt
  pas, il se cherche. Filtre **local** (la liste est déjà chargée, rien ne repart sur le
  réseau), insensible à la casse **et aux accents** — personne ne compose les accents dans un
  champ de filtre. Le compte affiche « N sur M » quand un filtre est actif : sans ça, filtrer
  laisse croire que l'émission ne compte que douze épisodes.

### Corrigé — audit smartphone / tablette
- **Cinq composants n'exposaient leurs actions qu'au survol.** Sur un écran tactile il n'y a
  pas de survol : ces boutons étaient **définitivement invisibles** (FileCard, FileExplorer,
  GroupBuilder, PromptEditor, TemplateUpload). C'est la même faute que le bouton « Diffuser »
  de la v1.84.3, sous une autre forme : une commande masquée par une condition que l'utilisateur
  ne peut pas satisfaire. Le repli déjà employé ailleurs est généralisé — visible par défaut,
  révélé au survol seulement à partir de `md`.
- **La barre d'action des Doublons était fixée à `left-52`**, soit la largeur de la barre
  latérale — or celle-ci n'occupe la mise en page qu'à partir de `md` ; en dessous c'est un
  tiroir hors-champ. Sur un écran de 375 px, la barre démarrait donc à 208 px du bord.
- **Le calendrier du planning écrasait sept colonnes dans 375 px** (~47 px par case : un titre
  de jalon y tenait en deux lettres). Défilement horizontal en dessous de 34 rem, **inchangé**
  sur grand écran où le conteneur dépasse cette largeur.
- **Les notifications** pouvaient déborder par la gauche sur téléphone (384 px de large sur un
  écran de 375). Bornées à l'écran.

### Documenté
- **[docs/plan-ged-dossiers.md](docs/plan-ged-dossiers.md)** — plan en trois lots pour rendre les
  Dossiers trouvables depuis la recherche GED, jusqu'à la proposition d'épisodes de podcast.
  Rien n'est codé ; les trois refus structurants sont écrits d'avance.

---

## [v1.86.0] — 2026-09-06 — Trier les épisodes, et les avoir tous

### Ajouté
- **Tri des épisodes** dans le panneau de diffusion : du plus récent (défaut, pour suivre une
  émission) ou du plus ancien (pour en reprendre une depuis le début). Le nombre d'épisodes
  est affiché à côté. Un épisode sans date part à la fin **dans les deux sens**, plutôt que
  de sauter d'un bout à l'autre de la liste selon le tri.

### Corrigé
- **La liste était plafonnée à 30 épisodes** (et le parseur à 40 avant elle), sur des émissions
  qui en comptent plus de 200. Le tri croissant aurait donc donné un **ordre juste sur un
  extrait faux** : le « plus ancien » affiché aurait été le 30ᵉ en partant de la fin, pas le
  premier épisode. `parse_feed` / `fetch_flux` prennent désormais un `max_items` ; la veille
  garde son plafond de 40 (elle ne veut que les nouveautés), la liste des épisodes lit tout
  le catalogue. *Le tri a été l'occasion de trouver le défaut, il ne l'a pas causé : la liste
  était déjà tronquée sans le dire.*

---

## [v1.85.0] — 2026-09-06 — Matothèque sait retrouver le flux d'un podcast

### Le problème trouvé en regardant les données
`flux_url` de « La Matrescence » valait `https://www.deezer.com/search/La%20Matrescence…` —
**une page de recherche Deezer, pas un flux RSS.** « Voir les épisodes » ne pouvait donc
qu'échouer, en annonçant un « format illisible » qui envoie chercher un problème de réseau là
où il n'y a qu'un mauvais champ. L'import avait rempli le champ avec un lien de plateforme.
Trois autres ressources ont la même maladie (Spotify, Apple Podcasts).

### Ajouté
- **« Chercher le flux pour moi »** — interroge l'annuaire Apple Podcasts, qui est l'index où
  les éditeurs déclarent leur flux, et renvoie les candidats avec leur nom, leur auteur et
  leur nombre d'épisodes. **Sortie Internet sur clic, annoncée avant : seuls le titre et
  l'auteur du podcast sortent** — aucun document, aucun tag, aucun identifiant de la GED.
  Rien n'est écrit : **l'utilisateur choisit**, parce que plusieurs émissions portent le même
  nom (« Le Nid », « Père ») et que trancher à sa place mettrait le mauvais flux en base
  sans qu'il le sache. Route `POST /dossiers/ressources/{id}/chercher-flux` — POST comme
  `episodes`, pour qu'un préchargement ne puisse pas déclencher un appel sortant.
- **Garde-fou « ceci n'est pas un flux »** : Spotify, Deezer, Apple Podcasts, YouTube et
  consorts servent une page d'écoute. L'adresse est désormais signalée **avant** l'échec,
  à la saisie comme sur une valeur déjà en base. Averti, jamais bloqué : un éditeur peut
  héberger son flux où il veut, et c'est la lecture réelle qui tranche.

### Changé
- **L'URL du flux est visible et modifiable depuis le panneau « Diffuser ».** Elle n'était
  affichée nulle part une fois enregistrée : pour la corriger il fallait deviner qu'elle se
  trouvait dans le formulaire d'édition de la fiche.

---

## [v1.84.3] — 2026-09-06 — Un bouton absent ne s'explique pas

Deux fonctions livrées en 1.84.0 étaient présentes mais **invisibles**, chacune pour une
raison différente. Dans les deux cas, l'écran laissait croire à une absence.

### Corrigé
- **Le bouton « Diffuser » ne s'affichait pour aucun podcast.** Il était conditionné à
  `flux_url`, et **aucune des ressources du dossier « Devenir parent » n'en porte** — le seed
  n'en pose pas une seule. Résultat : une fonction livrée, testée, déployée… et introuvable.
  Le bouton s'affiche désormais pour **tout podcast** ; quand le flux manque, le panneau le dit
  et **propose de saisir l'URL sur place** (enregistrement en base, aucune sortie réseau).
  *Leçon générale : masquer une commande faute de donnée transforme un champ vide en
  fonctionnalité manquante. Mieux vaut la montrer et expliquer ce qu'il lui faut.*
- **Le champ « Jeton Home Assistant » semblait vide alors que le jeton était bien en base.**
  Le backend ne renvoie jamais un secret — c'est voulu — mais l'UI n'affichait pas pour autant
  qu'il était **défini**. On lisait donc « rien n'est enregistré ». Le drapeau `defini`, déjà
  renvoyé par `/system/config`, est maintenant exploité : mention verte « jeton enregistré
  (chiffré) » et invite « laisse vide pour le conserver ». Mécanisme générique
  (`secretsDefinis`), réutilisable pour les six autres secrets qui ont le même défaut.

---

## [v1.84.0] — 2026-09-06 — Écouter un podcast sur une enceinte de la maison

> Les trois lots de `docs/plan-podcast-diffusion.md`, livrés ensemble parce qu'ils ne valent
> rien séparément. **Toujours pas de lecteur intégré** : Matothèque catalogue, elle ne rejoue
> pas. On n'écoute pas un podcast devant sa GED.

### Lot 1 — l'URL du flux
- **`ressources.flux_url`** (migration `0007`), saisissable pour les podcasts. Distincte de
  `url`, qui pointe la page de l'émission : c'est le **flux** qui porte les épisodes et leur
  audio. À ne pas confondre avec la table `flux_rss`, qui abonne un **dossier** à une veille —
  les réunir ferait déverser les épisodes de chaque podcast catalogué dans les nouveautés.

### Lot 2 — les épisodes
- **Le parseur RSS extrait enfin l'`<enclosure>`.** Il servait la veille, qui n'a que faire du
  média attaché, et le jetait donc. Or un podcast **est** un flux RSS dont chaque item porte son
  audio. Les deux dialectes sont couverts (RSS 2.0 `<enclosure>`, Atom `<link rel="enclosure">`),
  la durée `itunes:duration` est lue en secondes comme en `hh:mm:ss`, et une valeur illisible ne
  fait pas tomber la lecture.
- **`POST /api/dossiers/ressources/{id}/episodes`** — en POST délibérément : ce n'est pas une
  lecture de notre base mais un appel sortant, et un préchargement ne doit pas le déclencher.
  Seuls les items **portant un audio** sont rendus : un flux mixte ne doit pas proposer de
  « diffuser » une page web.

### Lot 3 — la diffusion
- **`services/maison_service` + `/api/maison/{enceintes,diffuser}`** : liste les `media_player`
  de **Home Assistant** (LAN) et envoie l'audio sur celui qu'on choisit
  (`media_player.play_media`). Les enceintes hors ligne sont montrées **grisées** plutôt
  qu'omises — leur absence ferait croire qu'elles n'existent pas.
- **Bouton `Cast`** sur la fiche d'un podcast qui a un flux, panneau d'épisodes, sélecteur
  d'enceinte. Ce qui sort est annoncé **avant** le clic, comme pour la veille : seule l'URL du
  flux part, et l'audio va de l'éditeur à l'enceinte sans passer par Matothèque.
- **Paramètres › Maison — diffusion** : URL de Home Assistant + jeton, chiffré en base.

### Ce que l'écran dit, et qu'il aurait été facile de taire
Un jeton de longue durée Home Assistant donne accès à **toute son API**, pas seulement aux
enceintes. C'est une limite de HA, pas un choix de notre part — l'écran le dit et suggère un
utilisateur dédié, plutôt que de laisser croire à une portée restreinte.

---

## [v1.83.1] — 2026-09-06 — Une section repliée est cachée, plus démontée

### Corrigé
- `CollapsibleSection` retirait son contenu du DOM au repli : **Ctrl+F ne le trouvait plus**, et
  un formulaire à moitié rempli était **perdu**. Il est désormais caché par `hidden`, donc absent
  de l'affichage et de l'arbre d'accessibilité, mais présent dans le DOM.
- Porte de sortie `demonterSiReplie`, posée sur la seule section qui en a besoin : garder monté,
  c'est aussi **monter les effets**, et `AuditActivity` charge 300 lignes à l'affichage dans une
  section fermée par défaut. Sans ça, deux requêtes à chaque visite de la page Logs.
- Défaut signalé par la session `_modele`. Son exemple principal (`SettingsPage`) n'était pas
  concerné pour Ctrl+F : la page est en maître-détail, les autres sections n'existent pas du tout.

---

## [v1.83.0] — 2026-09-06 — Le résumé IA persiste, s'édite, et s'enregistre seul

### Ajouté
- **`ressources.resume_ia`** (migration `0006`) : la proposition ne vivait qu'en mémoire du
  navigateur — un rechargement l'effaçait et il fallait refaire tourner le modèle.
- **Édition sur place, enregistrée seule** 800 ms après la dernière frappe, avec l'état affiché :
  « modification en cours », coche verte « enregistré », message rouge si l'écriture échoue.
- Colonne **séparée de `note`**, délibérément : la note est ce que l'utilisateur assume, le
  résumé une suggestion qu'il garde, corrige ou promeut. « Supprimer » efface aussi en base.

---

## [v1.82.0] — 2026-09-06 — Antivirus : les fichiers concernés, nommés

### Ajouté
- Chaque état actionnable (**infecté**, **non examiné**, **antivirus éteint**) liste les fichiers
  concernés, triés par taille, avec la **signature ClamAV** pour les infectés. Un compteur seul
  ne permet pas d'agir : « 3 infectés » ne dit ni lesquels, ni où.

### Clarifié
- **« Désactivé » n'est pas une quarantaine, et il n'y en a aucune.** Matothèque ne déplace ni ne
  supprime aucun fichier : un document infecté est refusé à l'indexation et marqué en erreur, le
  fichier reste sur le partage. La seule quarantaine de l'application est celle des **doublons**.

---

## [v1.81.1] — 2026-09-06 — Antivirus : ce que ClamAV ne PEUT PAS scanner

### Ajouté
- **La limite INSTREAM est affichée, et la population au-dessus est comptée.** ClamAV refuse de
  scanner au-delà de **25 Mo** (défaut de l'image ; aucun `clamd.conf` n'est monté). Le tableau
  de bord dit donc combien de documents dépassent ce seuil — **calculé sur la taille**, donc sans
  relire un seul fichier. C'est la seule réponse instantanée à « qu'est-ce qui m'échappe ? ».
- Réglage `CLAMAV_STREAM_MAX_MO` (défaut 25), à aligner si l'on change `StreamMaxLength` côté
  conteneur.

### Répond à une vraie question
« L'état des 66 000 documents en `inconnu` va-t-il se mettre à jour ? » — **Non.** Rien ne
repasse sur l'existant, et re-scanner 66 000 fichiers (NAS compris) coûterait des jours pour un
bénéfice faible. Mais la question qui compte — *lesquels ne peuvent de toute façon pas être
examinés ?* — a maintenant une réponse immédiate, sans la moindre lecture disque.

### Documentation
- `docs/plan-podcast-diffusion.md` — plan en trois lots pour écouter un podcast sur une enceinte
  de la maison via Home Assistant, avec ce qui reste **hors périmètre** et pourquoi.

---

## [v1.81.0] — 2026-09-06 — Matothèque sait maintenant compléter ses propres liens

### Ajouté
- **Bouton « Compléter N liens manquants »** dans un dossier, visible seulement s'il y a
  quelque chose à compléter. Il **n'appelle rien sur le réseau** : il ouvre l'IA internet avec
  la liste des titres déjà rédigée, l'IA **locale** en fait un prompt, et on l'envoie où l'on
  veut. Même mécanique que les prompts livrés avec « Mon bébé », mais appliquée aux ressources
  du dossier courant. Les prompts IA sont exclus (ils n'ont pas vocation à avoir une URL), et la
  demande est plafonnée à 25 titres par lot.

### Corrigé — sans quoi le bouton n'aurait servi à rien
- **L'import ignorait une ressource déjà présente**, donc l'URL retrouvée pour « La Matrescence »
  était jetée par le dédoublonnage. Il **complète** désormais une ressource dépourvue d'URL au
  lieu de l'écarter. C'était le chaînon manquant.
- ⚠️ **Jamais d'écrasement.** Auteur et note ne sont complétés que s'ils sont **vides** : ce qui
  a été saisi à la main prime sur ce que rapporte une IA. Sans cette règle, un import écraserait
  silencieusement un travail de curation.
- Le message de retour distingue **ajoutées** / **complétées** / **déjà présentes** — annoncer
  « 0 ajoutée » après avoir renseigné 12 liens donnerait l'impression que rien ne s'est passé.
- 3 tests, dont celui qui vérifie qu'un auteur saisi survit à un import contradictoire.

---

## [v1.80.0] — 2026-09-06 — Antivirus : le tableau de bord dit ce qui n'a PAS été examiné

### Ajouté
- **Section « Antivirus » dans les Paramètres.** Un tableau de bord qui n'afficherait que
  « service : OK » ne dirait rien d'utile : ce qui compte n'est pas que `clamd` réponde, c'est
  **combien de documents sont passés sans être regardés**, et lesquels.
- **Trois populations, jamais confondues** : `sain` (examiné, rien trouvé — le seul état qui
  affirme quelque chose), `non_scanne` (trop gros ou service muet : **indexé sans être
  examiné**), `inconnu` (indexé avant la v1.79.0, quand l'état n'était pas enregistré).
  Un bandeau compte explicitement ceux sur lesquels l'antivirus n'affirme rien.
- **Liste des plus gros non examinés**, triés par taille : la limite de ClamAV se franchit par
  le haut, c'est exactement là que se trouvaient les fichiers qui échappaient au scan.
- Nouvel endpoint `GET /api/system/antivirus`.

### Note
Pas encore d'action « re-scanner » : elle demande de récupérer chaque fichier, NAS compris, et
de le repasser dans le pipeline. C'est **dit dans l'écran** plutôt que laissé deviner.

---

## [v1.79.0] — 2026-09-06 — Antivirus : « pas pu être scanné » n'est plus « sain »

### Corrigé — les plus gros fichiers étaient les moins protégés
- `clamav_service` renvoyait **`(True, None)`** pour un fichier examiné et propre **comme** pour
  un fichier qu'il n'avait **pas pu** examiner — trop gros pour la limite `INSTREAM` de `clamd`,
  ou `clamd` injoignable. L'appelant ne pouvait pas les distinguer, l'information était perdue à
  l'indexation, et **plus un fichier était gros, moins il était protégé** : il suffisait de le
  rembourrer au-delà de `StreamMaxLength` pour qu'il soit réputé propre.
- `scan_file()` rend désormais un **état** en plus du verdict : `sain` | `infecte` |
  `non_scanne` | `desactive`. La **dégradation gracieuse est conservée** — un fichier non
  examiné est toujours indexé, la sécurité ne doit pas casser le pipeline — mais on ne le fait
  plus passer pour propre.
- **Nouvelle colonne `documents.antivirus`** (migration `0005`), avec un index partiel sur les
  seuls états à réexaminer : les documents jamais examinés sont **retrouvables**, donc
  re-scannables. Les documents antérieurs restent à `NULL`, ce qui est la vérité — on ignore
  dans quel état ils ont été scannés, et c'est distinct de `non_scanne`, qui est un constat.
- « Éteint » et « en panne » ont deux états distincts : ils ne se soignent pas de la même façon.
- 6 tests (`test_clamav_etat.py`), dont celui qui dit l'essentiel : `etat != SAIN` quand le
  fichier dépasse la limite.

### Origine
Défaut relevé par la session **AIGUILLEUR** en lisant notre code, et vérifié avant correction.
Reste à faire (ROADMAP) : exposer le filtre « jamais examinés » dans la GED et une action de
re-scan — la donnée est là, l'écran ne l'est pas encore.

---

## [v1.78.4] — 2026-09-06 — Un podcast n'ouvre plus une recherche Google

### Modifié
- **Le repli d'un podcast pointe sur Deezer** et non plus sur une recherche Google : on cherche
  à **écouter**, pas à lire des pages.

### Mais ce n'est qu'un pansement
La cause réelle : **73 des 95 ressources de « Devenir parent » n'ont pas d'URL** (17 podcasts,
21 livres, 7 chaînes…). Sans URL, `lienSource()` ne peut fabriquer qu'une **recherche** — aucun
lien ne mènera « au site » tant qu'elle manque. Renseigner les vraies URLs demande de les
vérifier en ligne : à faire sur confirmation.

### Non fait — et pourquoi pas l'API Deezer
Un lecteur intégré via Deezer exigerait un **compte**, des **identifiants d'application à
stocker**, un SDK propriétaire et un abonnement pour la lecture complète — et l'historique
d'écoute partirait chez eux. Or **un podcast EST un flux RSS**, avec l'audio en `<enclosure>`,
et Matothèque sait déjà lire du RSS. Le lecteur naturel tient en trois pièces : stocker l'URL du
flux, lister les épisodes à la demande (sortie réseau confirmée), jouer avec une balise
`<audio>`. Aucun compte, aucun jeton. Cadré en ROADMAP.

---

## [v1.78.3] — 2026-09-06 — IA internet : le dossier cible se déduit d'où l'on vient

### Modifié
- **`?dossier=<slug>` pré-sélectionne le dossier cible** de l'étape 2. Quand on arrive depuis un
  dossier, c'est presque toujours là qu'on veut reverser la réponse : le laisser vide obligeait
  à rechoisir ce qu'on venait de quitter — et à se tromper un jour sur deux. Le bouton
  « Trouver des flux avec l'IA » transmet donc le dossier en même temps que le besoin.
- **Les sous-dossiers fonctionnent aussi.** `GET /dossiers` ne rend que les **racines** : le slug
  d'un sous-dossier n'y figure pas, le `<select>` aurait affiché du vide et l'import aurait
  atterri ailleurs. Son titre est maintenant chargé à la volée et ajouté aux options ; un slug
  introuvable ne présélectionne rien plutôt que de désigner le mauvais dossier.

---

## [v1.78.2] — 2026-09-06 — Export ICS : le pliage débordait sur les lignes accentuées

### Corrigé
- **Une ligne de l'export réel faisait 77 octets** au lieu des 75 de la RFC 5545. Le pliage
  parcourait les **octets** et devait rattraper les coupes au milieu d'un caractère
  multi-octets — ce rattrapage débordait. Il parcourt maintenant les **caractères** en comptant
  leurs octets : le dépassement devient impossible par construction.
- Trouvé en testant l'export **sur la production**, pas en relisant le code. Le test qui l'aurait
  attrapé existait déjà (`test_le_seed_complet_s_exporte`) mais n'a jamais pu tourner ici — les
  dépendances backend ne s'installent pas hors conteneur. Il aurait échoué en CI.

---

## [v1.78.1] — 2026-09-06 — Dossiers : la page respire en largeur, plus en hauteur

### Modifié
- **La page d'un dossier passe de `max-w-4xl` à `max-w-7xl`**, comme les Paramètres. Elle porte
  des **grilles** (ressources, sous-dossiers, jalons), pas un texte suivi : en 896 px, un écran
  1080p laissait ~500 px de vide de chaque côté et empilait tout en hauteur. La **description
  garde sa largeur de lecture** (`max-w-3xl`) — une ligne de 1200 px se lit mal.
- **Planning : jusqu'à 5 colonnes** sur grand écran (3 auparavant, quel que soit l'écran) et
  gouttières resserrées.
- **Le bouton « Ajouter à ce mois » quitte la grille** pour l'en-tête du mois. Il occupait une
  tuile par mois — **23 tuiles de vide** sur un planning complet, soit plusieurs écrans de
  défilement pour rien. La saisie s'ouvre sous l'en-tête et ne prend de la place que le temps
  qu'on écrive.

### Note
Les autres pages (Dossiers, Doublons, Liens, Logs, Administration, Réorganiser) sont encore en
`max-w-4xl`. Elles portent aussi des listes et gagneraient au même traitement — **non modifiées
ici**, pour ne pas changer d'un bloc la mise en page de six écrans sans les avoir regardés un
par un.

### Décidé
- **Abonnement au calendrier : abandonné.** Cible visée = Google Agenda, ce qui imposerait une
  URL publique (c'est un serveur Google qui lit, pas le navigateur — le VPN n'y change rien), et
  Google ne relit une URL `.ics` que toutes les 8 à 24 h. L'export manuel, avec son `UID` stable,
  est plus rapide et n'expose rien. Analyse conservée en ROADMAP.

---

## [v1.78.0] — 2026-09-06 — Veille : une sortie quand la liste de flux est vide

### Ajouté
- **« Trouver des flux avec l'IA »** dans le panneau de veille quand aucun flux n'est abonné :
  plutôt qu'un constat, une sortie. Le bouton **n'appelle rien sur le réseau** — il ouvre la page
  IA internet avec le **besoin pré-rempli** (thème du dossier, exigence d'URL de flux exacte et
  vérifiée, fréquence, éditeur). L'IA **locale** rédige le prompt ; c'est l'utilisateur qui
  l'envoie, où il veut, et qui rapporte la réponse par Import IA.
- **`?besoin=` sur la page IA internet** : un appelant peut y amener avec la demande déjà écrite.
  **Pré-remplie, pas envoyée** — on relit et on corrige avant de lancer quoi que ce soit.

### Non fait, délibérément
- **Des flux proposés d'office pour « Devenir parent ».** Les quatre de « Mon bébé » ont été
  **vérifiés en ligne** avant d'entrer dans le seed. Je ne peux pas vérifier de nouvelles URLs
  sans sortie réseau, et livrer des flux non vérifiés produirait des erreurs dès la première
  utilisation. À faire sur confirmation : vérification, puis ajout.

### Note — le 100 % local tient ici sans AIGUILLEUR
La page IA internet n'appelle **rien**. Aucune donnée ne peut fuir parce que **rien n'est
envoyé** : la garantie est structurelle, pas déclarative. Le jour où AIGUILLEUR aura sa
passerelle Internet, le risque se déplacera vers le **contenu du prompt** — chiffrer le
transport ne protège de rien si le prompt porte un nom ou une date de terme. Les trois points à
trancher avant sont en ROADMAP.

---

## [v1.77.0] — 2026-09-06 — Planning : couleurs cohérentes et export iCalendar

### Ajouté
- **Export `.ics`** du rétroplanning, à importer dans n'importe quel agenda. Deux choix qui
  comptent : des événements **journée entière** (aucun de ces jalons n'a d'horaire, en inventer
  un ferait croire à un rendez-vous pris) et un **`UID` stable** — réimporter **met à jour** au
  lieu de dupliquer, c'est la différence entre un export utilisable deux fois et un export qui
  pollue l'agenda dès la seconde. Les jalons sans date propre portent la mention « (période) »
  et l'expliquent dans leur description.
- Le bouton n'apparaît **que si une date de terme est saisie** : sans elle, rien n'a de date à
  exporter, et un fichier vide vaudrait moins qu'une absence de bouton.

### Modifié
- **Les filtres portent enfin la couleur de leur catégorie**, la même que dans le calendrier.
  Avant, on cochait « Médical » sans savoir quelles pastilles allaient disparaître : le filtre
  et la grille parlaient deux langues.
- **Le calendrier affiche l'icône de la catégorie** (stéthoscope, mairie, valise…) à la place
  de la pastille ronde, dans sa couleur. La distinction date exacte / période est conservée par
  l'opacité, et l'infobulle nomme la catégorie et le caractère approximatif.

### Notes techniques
- Le téléchargement passe par un **vrai lien** vers l'API, pas par un blob piloté en JavaScript :
  seule voie fiable quand l'application est servie en HTTP.
- Pliage des lignes ICS à **75 octets** et non 75 caractères (un « é » en pèse deux, et un repli
  au mauvais endroit casse le fichier chez certains clients), échappement RFC 5545, CRLF.
  5 tests couvrent le refus sans terme, la journée entière, l'`UID`, l'échappement et l'export
  complet des 67 jalons.
- **Abonnement au calendrier** (URL à s'abonner plutôt que fichier) : **non fait**, cadré en
  ROADMAP. Deux corrections au passage — AIGUILLEUR est une passerelle d'inférence IA et n'a
  aucun rôle ici ; et le risque n'est pas « le reste de Matothèque » mais le calendrier lui-même,
  qu'une URL d'abonnement expose en continu pendant des mois.

---

## [v1.76.2] — 2026-09-06 — Le lien vers les Paramètres pointait sur une route inexistante

### Corrigé
- **`/parametres` n'existe pas, la route est `/settings`.** Les deux liens du planning
  (« Saisir la date du terme », et l'invitation de la vue calendrier) menaient donc à la page
  d'accueil. Signalé à l'usage, sur la production.
- **Le lien profond ouvre maintenant la bonne section.** `SettingsPage` lit `?section=<id>` et
  déplie directement la carte demandée ; sans ça le paramètre était décoratif et l'utilisateur
  était déposé sur le tableau de bord, à retrouver la bonne carte parmi treize. Un identifiant
  inconnu est ignoré plutôt que d'ouvrir une section vide.

---

## [v1.76.1] — 2026-09-06 — `keep_alive` : plus aucun chemin ne peut renvoyer la chaîne

### Corrigé
- **La garde s'applique aussi à la valeur d'environnement.** Le correctif de la v1.74.0 ne
  couvrait que le modèle épinglé ; `OLLAMA_KEEP_ALIVE=-1` dans un `.env` aurait rejoué le
  même HTTP 400 par un autre chemin. `-1`, `"-1s"` et `"-1"` se ressemblent à l'œil et ne
  font pas du tout la même chose : on retire le piège plutôt que de compter sur la vigilance.
- **`embed()` et `warm()` envoyaient encore la valeur brute**, contournant la garde. Les six
  points d'envoi passent désormais tous par `_keep_alive_for()`.
- Tests étendus (11 cas), qui vérifient le **type** autant que la valeur.

### Note — l'origine, mesurée
La session **AIGUILLEUR** a capturé 41 h de trafic (04→06/09) : **2 652 refus HTTP 400**,
soit la totalité de nos appels vers `llama3.1:latest`, et `Qwythos-9B` devenu cheval de trait
par accident (1 412 appels). Elle attribuait la valeur à une saisie dans notre base ; c'est
inexact — `ollama_keep_alive` n'est exposé ni dans `runtime_config` ni dans `ConfigUpdate`,
donc aucune UI ne peut l'écrire. La cause était bien du **code** (`_keep_alive_for`), et sa
sélectivité le prouve : seuls les appels au modèle épinglé partaient en 400, les autres
portaient `30m`. Le correctif est en v1.74.0 — **et n'est toujours pas déployé**.

---

## [v1.76.0] — 2026-09-06 — Bandeau « une nouvelle version est en ligne »

### Ajouté
- **Bandeau de mise à jour** : un onglet resté ouvert tourne indéfiniment sur le bundle
  d'hier, sans aucune raison de recharger. Il est maintenant prévenu, et un clic recharge.
  **Jamais de rechargement automatique** — il jetterait une fiche en cours d'édition ou un
  rapport en train de se générer. Masquable, mais il revient au sondage suivant : le fait de
  tourner sur une version périmée, lui, ne disparaît pas.
- **Deux signaux surveillés, parce qu'ils ne bougent pas ensemble** : la version du backend
  (`/api/version`) et le **nom du bundle d'entrée** lu dans `index.html`. Le second est le
  seul qui attrape un frontend rebuild **sans** changement de version — cas réel quand on
  republie le tag `latest`. Sondage toutes les 5 min et au retour sur l'onglet.

### Notes
- Mécanisme calqué sur celui de **FOULÉE** (`ui-version.js`), adapté à une SPA buildée
  séparément : elle compare à un `<meta app-version>` rendu par le serveur, impossible ici
  faute de rendu serveur — d'où la lecture du bundle dans le DOM, qui dit exactement ce que
  CET onglet exécute.
- `location.reload()` suffit : les bundles Vite sont déjà hashés et servis `immutable`, et
  notre nginx sert `index.html` en `no-cache, must-revalidate`. Pas de service worker
  (l'application est servie en HTTP, donc hors contexte sécurisé).

### Outillage
- **`scripts/verifier-deploiement.ps1`** — répond aux trois questions qui font foi : le
  registre porte-t-il le tag ? **`latest` pointe-t-il sur CE build** ? la prod sert-elle cette
  version ? Ne modifie rien, sort en erreur tant que ce n'est pas vrai.
  **Pourquoi, alors qu'il y a un bandeau ?** Parce qu'un détecteur de nouvelle version ne peut
  pas détecter l'**absence** de nouvelle version : quand rien n'a été publié, le bandeau ne
  s'affiche pas, et son silence se lit « je suis à jour ». Il donne une fausse confiance
  exactement là où l'alerte serait la plus utile. *(Point structurel dû à la session FOULÉE.)*
- `scripts/check-image-ready.ps1` marqué **obsolète** : il visait GHCR et le NAS, deux chemins
  abandonnés.

### Documentation
- `CLAUDE.md` § Déploiement : **`docker compose pull` ne fabrique rien.** Si `build-push.ps1`
  n'a pas tourné, le tag `latest` pointe encore sur l'ancien build et le déploiement « réussit »
  sans rien changer (vécu le 06/09 : pull + up + restart impeccables, et toujours `1.73.0`).
  Le seul verdict qui compte est la sortie de `/api/version`.

---

## [v1.75.0] — 2026-09-06 — Barre latérale : l'arborescence des dossiers

### Ajouté
- **Les dossiers thématiques et leurs sous-dossiers dans la barre latérale**, sous « Dossiers ».
  Deux niveaux dépliables : les racines sont chargées au montage, les sous-dossiers **à la
  demande** — charger le détail de chaque dossier d'emblée ferait N requêtes pour un menu
  qu'on n'ouvrira peut-être pas. État déplié mémorisé entre les visites.
- **Mise à jour dynamique** : les pages qui créent ou suppriment un dossier émettent un
  événement (`utils/evenements`), la barre latérale l'écoute et relit — y compris les branches
  déjà ouvertes, pour qu'un sous-dossier créé à l'instant apparaisse sans replier/redéplier
  son parent. Les pages n'ont pas à connaître la barre latérale, et rien à défaire si l'une
  des deux disparaît.

### Détails d'usage
- Le **mot** « Dossiers » reste un lien vers la liste ; seul le **chevron** déplie. Mélanger
  les deux gestes sur la même zone est le défaut classique de ces menus.
- Le chevron d'un dossier n'apparaît que s'il a réellement des sous-dossiers (`nb_sous_dossiers`).
- Titres tronqués avec l'intitulé complet en infobulle : la colonne fait 208 px.

---

## [v1.74.1] — 2026-09-06 — Planning : l'agenda dit son âge et sait se relire

### Ajouté
- **Bouton « Actualiser »** dans l'en-tête du planning, avec l'**âge des données** à côté
  (« à l'instant », « il y a 12 min »…). Un agenda est un instantané ; le libellé vieillit
  tout seul à l'écran, sinon il resterait figé sur « à l'instant » — précisément le mensonge
  qu'on veut supprimer.
- **Relecture automatique au retour sur l'onglet**, si les données ont plus d'une minute.
  Assez pour rattraper une modification faite ailleurs (autre onglet, autre poste), pas assez
  pour marteler l'API à chaque aller-retour.
- **Rechargement silencieux** : la vue n'est plus démontée. La fiche ouverte le reste, le
  défilement ne saute pas, seul le bouton tourne. Les rechargements qui suivent un ajout, une
  suppression ou l'installation du seed passent aussi en silencieux — plus de clignotement.

### Notes
- Un rechargement redemande **tout ce dont l'agenda dépend** : les jalons, leur suivi, **et la
  date du terme** (relue en base par le backend à chaque requête). Changer le terme dans les
  Paramètres depuis un autre onglet est donc bien répercuté par ce bouton.
- Le planning n'a **qu'une source** aujourd'hui : `GET /api/dossiers/{slug}/planning`. Il n'y a
  pas d'agrégation de calendriers externes à réinterroger — si c'est le besoin, c'est un
  chantier distinct (cf. ROADMAP).

---

## [v1.74.0] — 2026-09-06 — Dossiers : rétroplanning, vue calendrier, et un `-1` qui coûtait 9,5 % du GPU

### Corrigé — en production, invisible depuis au moins le 04/09
- **`_keep_alive_for()` renvoyait la chaîne `"-1"`, pas l'entier.** Ollama attend une durée Go
  (« 30m », « -1s ») ou un **nombre de secondes** ; `"-1"` n'est ni l'un ni l'autre et part en
  **HTTP 400** (`time: missing unit in duration "-1"`) en 1 ms. Mesuré par la capture E0
  d'AIGUILLEUR sur la prod : **488 refus en 7 h 30, 9,5 % du trafic de la carte**.
  Personne ne le voyait — le refus est instantané, le repli « même famille » prenait le relais,
  l'utilisateur obtenait sa classification. Sauf que **l'enrichissement ne tournait jamais sur
  `llama3.1`**, et que la chaîne de repli finissait par charger un modèle de 41 Gio dont le
  débordement en RAM faisait évincer par Ollama… le `llama3.1` épinglé que ce code protège.
  **Le correctif censé aider JARVIS lui coûtait ses 61 s de latence vocale.** Test de
  régression `tests/test_ollama_keep_alive.py`, qui vérifie le **type** autant que la valeur.

### Ajouté
- **Vue calendrier** (bascule « Cartes / Calendrier ») : une grille mensuelle façon agenda,
  navigation mois par mois, bouton « Aujourd'hui », jour courant surligné. Les deux vues
  répondent à deux questions différentes — « qu'y a-t-il à faire à cette période » et
  « qu'est-ce qui tombe ce mois-ci » — et un clic ouvre la même fiche dans les deux.
- **Datation des jalons, avec sa qualité assumée** : un jalon qui porte des **semaines
  d'aménorrhée** est daté au jour près (`terme - (41 - SA) semaines`, le terme étant à 41 SA
  par convention française) ; les autres sont posés au début de leur période et affichés avec
  une **pastille creuse**. Prétendre à une date exacte ferait croire à un rendez-vous là où il
  n'y a qu'une fenêtre. L'API expose `date_prevue` et `date_precise`.
- **Onglet « Planning »** dans la page d'un dossier thématique, à côté des ressources.
  Un mois = une section, un jalon = une **carte cliquable** ; le clic ouvre la fiche, où
  vivent les options : cocher, annoter, modifier, ouvrir le lien officiel, retirer. La carte
  reste pauvre (titre, échéance, état) — 67 entrées deviennent illisibles si on met le détail
  dessus.
- **Table `jalons`** (migration `0004_jalons`). Le temps est repéré par **un seul entier
  signé** : `-9 … -1` = 1ᵉʳ … 9ᵉ mois de grossesse, `0 … 36` = âge de l'enfant en mois. La
  fenêtre du mois `m` va de `terme + m mois` à `terme + (m+1) mois` — **la même formule des
  deux côtés de la naissance**, en mois calendaires (le 31 mars moins un mois tombe le 28 ou
  le 29 février, pas le 3 mars).
- **Rétroplanning « Devenir parent » livré : 67 jalons**, 41 avant la naissance et 26 sur les
  trois premières années, dont 28 marqués obligatoires. Médical (7 examens prénataux,
  3 échographies, entretien prénatal précoce, dépistages, calendrier vaccinal), administratif
  (déclaration de grossesse, reconnaissance anticipée, déclaration de naissance, PAJE),
  congés (maternité, paternité et son préavis d'un mois), mode de garde, matériel,
  préparation, et repères de développement.
- **Suivi personnel** : `fait`, `fait_le`, `note_perso` sur la ligne du jalon. Cocher horodate,
  **décocher efface l'horodatage** — une date de réalisation qui survit au décochage est un
  mensonge silencieux. Un seed rejoué n'y touche jamais.
- **Paramètres › Dossiers — Parents** : saisie de la **date du terme** (`parents_date_terme`).
  C'est l'ancre de tout le calcul.
- **Filtres** par catégorie et « reste à faire », barre d'avancement, repère visuel du **mois
  en cours**, et ajout d'un jalon directement dans son mois.

### Notes
- **Sans date de terme, le planning reste consultable** : les mois s'affichent par leur rang
  (« 5ᵉ mois de grossesse ») sans dates. Une page qui refuse de s'ouvrir tant qu'on n'a pas
  saisi une date ne sert à personne qui vient d'abord voir de quoi il retourne. Une date
  illisible en base dégrade l'affichage, elle ne le casse pas.
- **Le contenu ne remplace ni un avis médical ni les textes officiels** — l'avertissement est
  servi par l'API avec le planning, jamais séparable de lui. Les échéances réglementaires
  portent leur formulation exacte (« avant la fin de la 14ᵉ semaine ») : le mois seul ne dit
  pas une date limite opposable.
- Un dossier installé avant cette version n'a pas ses jalons : l'onglet propose de **rejouer
  le seed**, qui est idempotent.
- 17 tests (`test_dossiers_planning.py`), dont l'arithmétique des fins de mois et la
  non-régression du suivi personnel lors d'une réinstallation.

---

## [v1.73.0] — 2026-09-04 — Prewarm du modèle de rapport activable/désactivable depuis l'UI (GPU partagé)

### Ajouté
- **Interrupteur « Garder le modèle de rapport chaud »** dans Paramètres (près de la concurrence worker) —
  active/désactive le **prewarm** à chaud (config `prewarm_enabled`, relue par le worker à chaque cycle,
  sans redémarrage). Sur un **GPU partagé** (assistant vocal JARVIS, FOULEE…), le **désactiver** rend la
  VRAM aux autres à la demande — pertinent quand le modèle de rapport est petit (rechargement à froid
  rapide). Le défaut vient de l'env `OLLAMA_PREWARM_ENABLED`.
- Complément du réglage **Modèles par usage › Rapport** : router un rapport vers un modèle qui **tient dans
  la carte** (ex. `ministral-3:14b`, 8,5 Gio) au lieu de Qwen3.6-35B (40 Gio, déborde) — voir note VRAM.

## [v1.72.1] — 2026-09-04 — Fix : keep_alive:-1 sur llama3.1 (ne plus casser le verrou GPU de JARVIS)

### Corrigé
- **Matothèque cassait le verrou `keep_alive` de JARVIS (Home Assistant)** sur l'Ollama **partagé**.
  `keep_alive` d'Ollama est un attribut du *chargement en cours*, réécrit à chaque requête (le dernier
  appelant gagne) ; en envoyant `keep_alive=30m` sur **llama3.1** (le modèle épinglé partagé), Matothèque
  écrasait le `-1` posé par JARVIS → la commande vocale suivante repayait le chargement (mesuré, note VRAM
  PC-GAME 04/09). **Fix** : Matothèque envoie désormais **`keep_alive:-1` uniquement sur le modèle épinglé**
  (`ollama_pinned_model`, défaut `llama3.1:latest`) ; les autres modèles gardent le défaut. Aucun
  `OLLAMA_KEEP_ALIVE` global (interdit : épinglerait les gros modèles → éviction sur 16 Go).

## [v1.72.0] — 2026-09-04 — Maintenance : mettre l'IA en pause / l'arrêter (libérer Ollama)

### Ajouté
- **Bouton « Traitement IA (Ollama) » dans Paramètres › Maintenance** — pour **libérer Ollama** au
  profit d'un autre usage (ex. projet FOULEE) sans toucher à la console :
  - **Mettre en pause** : le worker cesse de réclamer les tâches IA (enrichissement, analyse, vision,
    embeddings) ; celles en cours se terminent. La synchro/réorganisation (sans IA) continue.
  - **Arrêter** : pause + **annule les tâches IA en cours** → Ollama libéré tout de suite (elles
    repasseront plus tard).
  - **Reprendre** : redémarre le traitement. Badge d'état « Actif / En pause ».
- Drapeau `ia_pause` (config à chaud) relu par le worker toutes les ~10 s ; endpoints
  `GET /system/ia/status` et `POST /system/ia/pause`.

## [v1.71.1] — 2026-09-04 — Veille : flux plus robustes (retry sur 404/5xx transitoires, en-têtes YouTube)

### Corrigé
- **Flux YouTube « HTTP 404 » sporadiques** : YouTube renvoie par intermittence un 404 sur ses flux
  `videos.xml` (l'URL est pourtant valide). `fetch_flux` **retente désormais jusqu'à 3 fois** sur les
  statuts transitoires (404/429/5xx) avec un petit backoff, et envoie des en-têtes plus complets
  (`Accept` de flux + cookie de consentement Google) → un flux valide n'affiche plus une fausse erreur.

## [v1.71.0] — 2026-09-04 — Dossiers : glisser-déposer une carte vers un (sous-)dossier

### Ajouté
- **Glisser-déposer** des ressources : une **poignée** (⠿) sur chaque carte permet de la **glisser**
  et de la **déposer** sur un **sous-dossier** (surligné en vert pendant le drag, « Déposer ici ») ou
  sur le **dossier parent** dans le fil d'Ariane. Complète le bouton 📁 « Déplacer » (sélecteur) déjà
  présent — pratique notamment pour ranger les inclassables dans un sous-dossier dédié.

## [v1.70.0] — 2026-09-03 — Dossiers : déplacer une ressource d'un (sous-)dossier à l'autre

### Ajouté
- **Déplacer une ressource vers un autre dossier de la même famille** — bouton 📁 sur chaque ressource :
  un sélecteur propose **toute la famille** (dossier racine + tous ses sous-dossiers, indentés), la
  ressource part en fin de destination. Idéal pour ranger un item promu depuis la veille (arrivé « Sans
  groupe » dans la racine) vers le bon sous-dossier d'âge (« 5-10 ans »…).
- Endpoints `GET /dossiers/{ref}/cibles-deplacement` (la famille, sauf le dossier courant) et
  `POST /dossiers/ressources/{id}/deplacer`.

## [v1.69.0] — 2026-09-03 — Veille RSS : sortie réseau confirmée (100 % local certifié) + flux « Mon bébé » par défaut

### Sécurité / conception
- **Sortie Internet de la veille alignée sur la garantie « 100 % local ».** Plutôt qu'un service séparé
  (piste écartée : incohérente — vérif modèles/HF sortent déjà du même process, et le cœur doit joindre
  Ollama sur l'hôte), la veille est **branchée sur le mécanisme existant** « Demandes Mise à jour internet » :
  - « Rafraîchir la veille » devient une **action réseau confirmée** — un encart certifie, **avant** tout
    téléchargement, que **seules les URLs des flux ajoutés** sont contactées (téléchargement **entrant**),
    et qu'**aucun** document, tag, résumé, chemin ni nom de fichier n'est envoyé. Jamais de fetch automatique.
  - la veille est **recensée dans Paramètres › Demandes Mise à jour internet** (traçabilité centralisée).

### Ajouté
- **Flux « Mon bébé » par défaut dans le seed** — 4 flux **vérifiés en ligne** (HTTP 200 + flux valide) :
  mpedia.fr (AFPA/pédiatres), La Maison des Maternelles (vidéos YouTube), Réseau Sécurité Naissance
  (actualités + agenda). Abonnés au dossier racine à l'installation du seed (idempotent, aucun téléchargement).

## [v1.68.0] — 2026-09-03 — Dossiers : page « Assistant IA internet » (boucle prompt → IA web → import, 100 % local)

### Ajouté
- **Page « IA internet »** (accessible depuis Dossiers) — le pont assumé entre le local et une IA web,
  **sans que l'application ne sorte du réseau** :
  1. **Décris ton besoin** → l'IA **locale** (Ollama, même template que « Discuter avec l'IA ») te
     rédige un **prompt prêt à copier** (rendu tableau markdown, anti-invention d'URL), avec bouton *Copier*.
  2. Tu le colles dans une vraie IA web (Claude, ChatGPT, Perplexity) — **c'est TOI qui sors**, pas l'app.
  3. **Tu ramènes la réponse** : collée ici, analysée en local (**Import IA**), puis ajoutée en masse
     aux ressources d'un **dossier cible** (aperçu à cocher, dédup URL/titre).
- Route `dossiers/ia-internet` + lien « IA internet » dans l'en-tête des Dossiers.

### Conception
- **100 % local** : cette page n'appelle **aucun** service externe (chat = Ollama local ; analyse =
  Import IA local). La sortie Internet reste à la main de l'utilisateur (copier/coller), jamais de l'app.

## [v1.67.0] — 2026-09-03 — Dossiers : bouton « Résumé IA » par ressource (IA locale, anti-invention)

### Ajouté
- **Résumé IA par ressource** — un bouton ✨ demande à l'**IA LOCALE** un court résumé (2-3 phrases),
  affiché comme **proposition** : on l'**enregistre dans la note**, on le **copie** ou on l'**ignore**
  (jamais écrit d'office). Deux régimes :
  - **condensation** si la ressource porte déjà du texte (`contenu`, ou une note longue) → sûr, l'IA
    ne fait que raccourcir un texte fourni ;
  - **description** si l'on n'a que le titre/auteur → l'IA décrit d'après ses connaissances, avec
    consigne stricte : dire « Ressource non identifiée avec certitude » **plutôt qu'inventer** un
    synopsis, des dates ou des noms.
- Endpoint `POST /dossiers/ressources/{id}/resume` (propose, n'enregistre rien).

### Note
- L'IA locale n'a **aucun accès web** : pour le vrai synopsis, le clic sur la ressource ouvre déjà
  la source (Babelio, Allociné…). Le résumé IA est un complément, pas une recherche en ligne.

## [v1.66.0] — 2026-09-03 — Dossiers : veille RSS (flux → nouveautés → promotion en ressource)

### Ajouté
- **Veille RSS par dossier** — un dossier peut s'**abonner à des flux RSS/Atom** (blog, chaîne
  YouTube, podcast, revue…). Les nouveautés arrivent dans une **liste de veille** ; on lit, puis on
  **promeut** en ressource permanente ce qui mérite d'être gardé, ou on écarte le reste.
  Panneau « Veille RSS » repliable en tête de la page dossier (badge « à lire »).
- **Parseur RSS/Atom sans dépendance** (`services/rss_service`, xml.etree) : RSS 2.0, RSS 1.0/RDF et
  Atom ; nettoyage HTML du résumé, dates RFC 822 / ISO 8601, dédup par `guid` (repli sur le lien).
- Endpoints : `…/flux` (CRUD abonnements), `…/veille/refresh` (récupère les nouveautés),
  `…/veille` (liste), `…/veille/{id}/lu` · `/promouvoir` · suppression, `…/veille/lu-tout`.

### Sécurité / conception
- **100 % local, sortie réseau CONFIRMÉE** : aucun polling en tâche de fond. Le téléchargement des
  flux ne part QUE sur clic explicite du bouton « Rafraîchir la veille » — comme un test de service
  ou un pull de modèle. Robuste flux par flux (un flux en erreur n'interrompt pas les autres).

## [v1.65.1] — 2026-09-03 — Dossiers : sections pliables + tags cliquables

### Ajouté
- **Sections pliables/dépliables** dans une page dossier — **repliées par défaut** à l'ouverture :
  l'en-tête de groupe devient un bouton avec chevron, un clic déplie/replie. On voit d'abord la
  structure (les groupes), on déplie ce qui intéresse — utile sur un dossier riche (« Mon bébé »…).
- **Tags cliquables** : un clic sur `#tag` filtre le dossier sur ce mot-clé. Un filtre actif
  (recherche, type, langue, favoris) **force l'ouverture** des sections concernées — un tag « ouvre »
  donc la section où il apparaît, au lieu de rester masqué derrière un repli.

## [v1.65.0] — 2026-09-03 — Dossiers : Import IA (coller une réponse) + import/export CSV

### Ajouté
- **Import IA** — le pont entre la recherche et l'app : tu **colles la réponse d'une IA web**
  (tableau markdown de sources), et **l'IA LOCALE (Ollama) la PARSE** en ressources structurées
  (titre, type, URL, note, tags) → **aperçu à valider** (coche/décoche) → **ajout en masse**.
  L'IA locale ne fait qu'**extraire** ce qui est collé (aucune URL inventée). Idempotent (dédup URL/titre).
  Endpoints `POST /dossiers/importer/parse` (aperçu, rien en base) et `POST /dossiers/{ref}/ressources/import`.
- **Import CSV** : charger un fichier CSV (`titre, auteur, type, url, note, groupe, tags`) → même aperçu → ajout.
- **Export CSV** : télécharger les ressources d'un dossier en CSV (BOM UTF-8, tags séparés par « | »).

## [v1.64.2] — 2026-09-03 — Dossiers : chaque ressource cliquable (lien direct ou recherche ciblée)

### Ajouté
- **Toute ressource est désormais cliquable** pour ouvrir sa source. Si elle a une **URL**, lien
  direct (↗). Sinon, une **recherche CIBLÉE selon le type** (icône 🔍), sans URL inventée :
  **livre/BD → Babelio** (description/résumé), **film/doc/série → Allociné** (synopsis),
  **chaîne/vidéo → YouTube**, **étude/rapport → Google Scholar**, le reste → recherche web.

## [v1.64.1] — 2026-09-05 — `keep_alive: "-1"` : 9,5 % des appels IA refusés en silence

### Corrigé
- **Une chaîne sans unité n'est pas une durée pour Ollama.** `OLLAMA_KEEP_ALIVE=-1` produisait
  `"keep_alive": "-1"`, refusé en **HTTP 400** (`time: missing unit in duration "-1"`) en 1 ms.
  `_keep_alive()` normalise désormais au seul endroit qui envoie la valeur : une durée sans unité
  devient l'entier de secondes qu'Ollama accepte (`-1` = indéfiniment), une valeur vide retombe
  sur le défaut. Test de régression : `tests/test_ollama_keep_alive.py`.

### Ce que ça cassait, et que personne ne voyait
Mesuré par la **capture E0 d'AIGUILLEUR** sur la **production** (192.168.42.83), 05/09/2026 :
**488 requêtes refusées en 7 h 30**, soit **9,5 % du trafic** de la carte. La séquence, répétée
488 fois : deux appels à `llama3.1:latest` refusés en 1 ms, puis repli « même famille » sur un
autre modèle qui, lui, répond. Donc :

- l'enrichissement (classification documentaire) **n'a jamais tourné sur le modèle configuré** ;
- la chaîne de repli allait jusqu'à **Qwen3.6-35B (41 Gio)**, qui déborde en RAM système ;
- Ollama évinçait alors le modèle épinglé des autres projets de la maison — **les 61 s de latence
  vocale de JARVIS viennent de là**.

Rien n'échouait visiblement : le 400 revenait en 1 ms, le repli fonctionnait, l'utilisateur
obtenait sa classification. **Aucun code de retour d'Ollama n'était regardé.**

### ⚠️ À faire côté production (hors dépôt)
Le correctif rend la valeur *valide* — il ne la rend pas *souhaitable*. `-1` normalisé signifie
**épingler le modèle indéfiniment**, exactement ce qu'il ne faut pas sur un GPU partagé avec
FOULÉE et JARVIS. Remettre `OLLAMA_KEEP_ALIVE=30m` (ou retirer la variable) dans
`/opt/docflow/.env` sur le LXC, et redéployer.

---

## [v1.64.1] — 2026-09-03 — 🔴 Fix : la synchro NAS effaçait l'enrichissement (hash non vérifié)

### Corrigé
- **La synchronisation NAS ré-extrayait des fichiers au contenu INCHANGÉ** (dont la seule DATE avait
  bougé : sauvegarde, restore, `touch`, heure d'été…), **effaçant leur enrichissement IA** (catégorie,
  tags, résumé) — c'est ce qui a fait bondir « Relancer l'IA » de ~150 à **1226** en une synchro.
  Cause : `extraction.process_file` traitait tout fichier au même chemin comme une « nouvelle version »
  (suppression de `metadonnees_ia` + statut `extracted`) **sans jamais comparer l'ancien et le nouveau
  hash**. **Correctif** : si le hash est identique, on **n'ré-extrait plus** (on rafraîchit juste la
  date stockée). Le texte des documents n'était pas perdu ; l'enrichissement se répare en relançant l'IA.
  Audit complet : `docs/audit-relance-ia-compteur.md`.

## [v1.64.0] — 2026-09-05 — AIGUILLEUR : Matothèque déclare son intention
## [v1.64.0] — 2026-09-03 — Dossiers hiérarchiques + « Mon bébé » (par tranche d'âge) + page d'aide

### Ajouté
- **Sous-dossiers (hiérarchie)** : un dossier peut désormais contenir des **sous-dossiers**
  (ex. « Mon bébé » → « 0-1 an », « 1-2 ans »…). Colonne `parent_id` (auto-référence, migration
  au démarrage), endpoints (créer un sous-dossier via `parent`, liste des racines, détail avec
  **fil d'Ariane** + sous-dossiers), suppression **en cascade**. Les dossiers plats existants sont
  inchangés (racines).
- **Seed « Mon bébé »** — hiérarchique : 6 sous-dossiers d'âge (**0-1 · 1-2 · 2-5 · 5-10 · 10-15 ·
  15-18 ans**), chacun livré avec **un prompt de recherche ciblé** sur les besoins de l'âge (sommeil,
  alimentation, langage, écrans, puberté, sexualité…), à copier dans une IA web puis reporter les
  sources. Install/complète idempotent (par slug + URL/titre).
- **Page d'aide « Aide — Prompts »** (accessible depuis Dossiers) : une bibliothèque d'exemples de
  prompts **copiables** — bibliographie sur un sujet, par tranche d'âge, recentrer, sources primaires,
  transformer en plan, vérifier des liens, trouver les lacunes.
- UI : cartes de sous-dossiers navigables + « Nouveau sous-dossier », compteur de sous-dossiers.

## [v1.63.0] — 2026-09-03 — Dossiers : texte intégral des ressources (prompts copiables)

### Ajouté
- **Champ `contenu`** sur les ressources : texte long INTÉGRAL, pour les cas où la ressource
  *est* le contenu au lieu de pointer vers lui — prompt à copier, extrait, citation, mode
  d'emploi. `note` reste la phrase de présentation affichée en liste ; `contenu` se déplie.
  Colonne nullable (migration Alembic `0003_ressource_contenu` + ALTER idempotent au démarrage
  dans `database.py`, puisque `create_all` ne fait que CREATE TABLE).
- **Bloc dépliable avec bouton « Copier »** dans la page dossier, replié par défaut — un seul
  prompt de 40 lignes noierait la liste. La copie passe par `utils/clipboard.copierTexte`,
  obligatoire ici : `navigator.clipboard` est absent quand l'application est servie en HTTP.
- **Champ texte long dans le formulaire** d'ajout et d'édition de ressource, et **recherche
  plein texte étendue au contenu** — on retrouve un prompt par une phrase qu'il contient.
- **Dossier « Devenir parent » complété** : 91 ressources. La section « Prompts IA » passe de
  3 résumés à **5 entrées à texte intégral** — prompt principal (bibliographie large), variante A
  (creuser la paternité), variante B (exigence scientifique), variante C (plan de contenu) et une
  fiche méthode en quatre règles. Description du dossier enrichie (les trois familles de livres,
  les trois titres à lire en priorité, le rappel que rien ne remplace un avis médical).
- **4 tests supplémentaires** (26 au total sur le module), dont l'aller-retour d'un texte
  multiligne accentué et la présence effective de la clause anti-invention dans le prompt livré.

### Corrigé
- **`installer_seed` ignorait `contenu`** : les prompts du seed arrivaient en base sans leur
  texte, donc vides et inutilisables. Trouvé par `test_prompts_du_seed_portent_leur_texte`.

## [v1.62.0] — 2026-09-03 — Dossiers thématiques (veille par sujet)

### Ajouté
- **Nouveau module « Dossiers »** (`/dossiers`) : veille documentaire par sujet. Un dossier
  rassemble des **ressources externes** — podcasts, chaînes, documentaires, émissions, films,
  séries, livres, BD, articles, études, rapports, associations, prompts IA — décrites par leur
  URL, leur type, leur langue et une **note** disant ce qu'elles apportent de spécifique.
  À ne pas confondre avec **Liens**, qui relie des *documents indexés* entre eux, ni avec la
  **GED**, qui indexe des *fichiers* : un dossier vit hors du système de fichiers.
- **Page dynamique par dossier** (`/dossiers/:slug`) : sections dans l'ordre du dossier, filtres
  par type / langue / essentiels et recherche plein texte (titre, auteur, note, tags). Ajout,
  édition, mise en favori, archivage et suppression de ressources depuis la page.
- **Dossier pré-rempli « Devenir parent »** (~90 ressources : maternité, paternité, matrescence,
  1000 premiers jours, sources institutionnelles et prompts de recherche), installable d'un clic
  depuis la liste des dossiers. Installation **idempotente** : relancée, elle n'ajoute que les
  ressources absentes et ne restaure jamais ce qui a été modifié ou supprimé à la main.
- **API `/api/dossiers`** : CRUD dossiers (adressables par UUID **ou par slug**, d'où les URLs
  lisibles), CRUD ressources, `GET /dossiers/types` (types reconnus + seeds disponibles) et
  `POST /dossiers/seed/{cle}`. Tables `dossiers_thematiques` et `ressources`, migration Alembic
  `0002_dossiers`.
- **22 tests d'intégration** (`backend/tests/test_dossiers_router.py`), dont l'idempotence du seed
  et l'ordre des sections.

### Détail d'implémentation
- **Ordre des sections** : les ressources sont triées par `position` seule, **pas** par `groupe` —
  un `ORDER BY groupe` classait les sections par ordre alphabétique alors que leur succession
  porte une progression voulue (Podcasts → YouTube → Documentaires → Livres → Sources primaires).
  L'ordre des groupes est dérivé de leur première apparition. Index `(dossier_id, position)`.
  Défaut trouvé par le test `test_groupes_dans_l_ordre_d_insertion`, corrigé avant livraison.
- **Filtrage côté client** : un dossier de veille tient dans la centaine d'entrées, le détail sert
  tout d'un coup — pas d'aller-retour réseau à chaque clic sur un filtre.
- `type` et `langue` sont **sans contrainte CHECK** en base (comme `document_links.type_lien`) :
  ajouter un type ne demande pas de migration, la liste de référence vit dans
  `routers/dossiers.TYPES_RESSOURCE` et est servie au front par `/dossiers/types`.

### Corrigé
- **Sidebar** : l'item actif reconnaît désormais les **sous-routes** — `/dossiers/devenir-parent`
  surligne « Dossiers », au lieu d'exiger l'égalité stricte du chemin (`/` reste exclu de la règle).

## [v1.61.0] — 2026-09-03 — Chat robuste si le modèle a été supprimé + avertissement

### Corrigé
- **« Discussion libre » affichait « IA injoignable » alors qu'Ollama était vert** : le chat utilisait
  le modèle configuré **tel quel**. Si ce modèle avait été **supprimé côté Ollama** (config périmée),
  la génération plantait — alors que le simple ping `/api/tags` (pastille du header) réussissait.
  Le chat **valide/résout désormais le modèle avant de streamer** (`_resoudre_modele(…, "chat")`,
  généralisé depuis les rapports) → **bascule automatique sur un modèle texte réellement installé**
  + trace dans les logs. Plus de « IA injoignable » à cause d'un modèle disparu.

### Ajouté
- **Avertissement dans Paramètres → Services & modèles IA** quand le **modèle par défaut** configuré
  n'est **plus installé** : bandeau ambre « … n'est plus installé — l'IA bascule sur un modèle
  présent ; choisis-en un installé ». (Répond à « pourquoi propose-t-il un modèle absent ? ».)

## [v1.60.4] — 2026-08-27 — Bouton « Rafraîchir la page » dans le header

### Ajouté
- **Bouton rafraîchir** (icône ⟳) dans le header, à côté de la bascule de thème (soleil/lune) :
  recharge la page d'un clic, sans passer par le menu du navigateur.

## [v1.60.3] — 2026-08-27 — Boutons « Copier » réparés en HTTP + projet passerelle visible

### Corrigé
- **Boutons « Copier » qui ne faisaient rien en HTTP** (jeton passerelle, message « claude projet »,
  chemins GED, commande HF, rapport…) : `navigator.clipboard` n'existe qu'en contexte sécurisé
  (HTTPS/localhost). Nouveau helper **`utils/clipboard.ts`** (`copierTexte()`, repli `<textarea>` +
  `execCommand`) branché sur les **8** boutons. Même famille que le bug `crypto.randomUUID`.
- **Projet passerelle qui n'apparaissait pas dans la liste après création** (ex. « Foulée ») : le
  toast de succès plantait (`crypto.randomUUID`, avant 1.60.2) *avant* le rafraîchissement de la
  liste. Ajout d'un **ajout optimiste** du projet à la liste dès la création (indépendant du refetch).

### Doc / convention
- **CLAUDE.md § Pièges connus** : section « contexte non sécurisé (HTTP) » — toujours passer par
  `utils/uuid` et `utils/clipboard`, et **tester les boutons Copier en HTTP** (bug invisible en HTTPS).

## [v1.60.2] — 2026-08-27 — 🔴 Fix racine : crypto.randomUUID en HTTP (toasts + test HF)

### Corrigé
- **`crypto.randomUUID is not a function`** en accès **HTTP** (non sécurisé — ex.
  `http://<ip-LAN>:3003`) : `crypto.randomUUID()` n'existe qu'en contexte sécurisé (HTTPS/localhost).
  Résultat : **tous les toasts** plantaient (souvent en silence), et surtout le **test HuggingFace**
  était marqué en échec alors que la connexion réussissait (`ok:true, user:"Agesti"`) — car le toast
  de succès crashait juste après. Nouveau helper **`utils/uuid()`** (repli `crypto.getRandomValues`
  puis `Math.random`) utilisé par `Toast`, `reportStore` et `GroupBuilder`. Le badge HF passe enfin
  au vert.

## [v1.60.1] — 2026-08-27 — Test HuggingFace : erreur affichée (plus juste un toast fugace)

### Ajouté
- L'erreur du test HuggingFace est désormais **affichée à côté du badge** (persistante), en plus du
  toast — pour lire la vraie cause (HTTP 401 / réseau…) sans la rater. Le message se réinitialise à
  chaque nouveau test.

## [v1.60.0] — 2026-08-27 — Modèles IA : statut de version clair + bandeau de vérification

### Ajouté / Modifié
- **Statut de version lisible** par modèle (fini le « ? » ambigu quand `update` était `null`) :
  `check_update` distingue désormais **« absent »** (hors registre Ollama — import perso / `hf.co/…`,
  pas de version de référence) de **« injoignable »** (registre non joignable). L'UI affiche
  ✅ à jour · ⚠️ MAJ dispo · **« local / importé »** · **« non vérifié »**. Nouveau champ
  `update_statut` (`a_jour|maj_dispo|absent|injoignable`) ; `update` (bool|null) conservé pour compat.
  Un modèle « injoignable » n'est plus reclassé « uncensored » à tort (souci réseau ≠ import perso).
- **Bandeau de chargement** pendant la vérification des versions (« Vérification des versions auprès
  du registre Ollama… ») — l'appel réseau est visible au lieu d'un simple spinner sur l'icône.

## [v1.59.6] — 2026-08-27 — HuggingFace : test de connexion fiabilisé (token collé)

### Corrigé
- Le **test de connexion HuggingFace** échouait dans l'UI alors que le token était valide : un token
  **collé avec une espace / un retour à la ligne** en trop partait tel quel (« Bearer hf_…\n ») → rejet.
  Le token est maintenant **`strip()`** avant usage (test + catalogue/détail), et le champ **masqué**
  (puces) est reconnu comme « inchangé » → repli sur le token stocké. *(Vérifié serveur :
  `POST /system/test/huggingface` → `ok:true, user:"Agesti"`.)*

## [v1.59.5] — 2026-08-26 — GED : rafraîchissement au retour de focus

### Ajouté
- La liste GED (« Tous les documents ») **se rafraîchit au retour de focus** sur l'onglet — les
  documents fraîchement indexés en arrière-plan apparaissent sans recharger la page. Non disruptif :
  en vue plate, on ne recharge que si on n'a pas paginé (page 1), pour ne pas perdre un « Charger
  plus » ; en vue groupée, on recharge les groupes. *(La navigation vers la GED rechargeait déjà au
  montage ; ceci couvre le cas « on reste sur la page pendant une indexation ».)*

## [v1.59.4] — 2026-08-26 — « Créer » : fin de la numérotation d'étapes trompeuse

### Modifié
- Les étapes de « Créer » n'affichent plus de **numéro** (① ② ③…) : selon le mode, l'ordre et le
  nombre d'étapes changent → « ② » désignait tantôt les documents, tantôt un template. Le **titre**
  porte déjà le nom de l'étape ; la pastille devient un **repère neutre** (point), le fil vertical
  conserve la notion de parcours. `Step` + `ReportsPage` (compteur `num()` supprimé).

## [v1.59.3] — 2026-08-26 — Fini le Ctrl+Shift+R + renommage visible instantanément

### Corrigé
- **Plus besoin de Ctrl+Shift+R après un déploiement** : le `no-cache` sur `index.html` était posé
  sur `location = /index.html`, jamais atteint par le fallback SPA (`/`, `/wiki/…` servis via
  `location /`). Déplacé au bon endroit → le navigateur récupère le nouvel `index.html` (qui pointe
  vers les bundles Vite re-hashés) tout seul. Assets hashés servis en `immutable` 1 an (comme le
  fingerprinting de Sapyn, adapté à la SPA). *(Un dernier hard-refresh reste nécessaire cette
  fois-ci, car l'ancien index.html est déjà en cache ; ensuite, plus jamais.)*
- **Renommage d'un livre/étagère visible immédiatement** : mise à jour **optimiste** de l'état local
  dès le succès (la liste BookStack pouvait renvoyer brièvement l'ancien nom juste après le PUT →
  le renommage semblait ne pas s'appliquer).

## [v1.59.2] — 2026-08-26 — Renommage wiki : « Entrée » valide (form onSubmit)

### Corrigé
- Le renommage inline (livre / étagère) ne validait pas avec **Entrée** (seul le ✓ marchait) :
  les champs sont maintenant dans un `<form onSubmit>` → **Entrée = valider** nativement (Échap
  annule toujours).

## [v1.59.1] — 2026-08-26 — Gestion wiki : mode édition (cadenas), inline, auto-refresh

### Modifié / Corrigé
- **Cadenas (mode Lecture ⇄ Édition)** : par défaut on parcourt (lecture) ; on clique **« Modifier »**
  pour activer l'édition — évite les manipulations accidentelles. Drag & drop et renommage ne sont
  possibles qu'en mode édition.
- **Renommage EN LIGNE** (plus de popup navigateur) : ✏️ transforme le titre du livre / le nom de
  l'étagère en champ éditable (Entrée = valider, Échap = annuler, ✓/✗).
- **Drag & drop corrigé** : `preventDefault()` inconditionnel sur `dragover` (sans lui, le navigateur
  refusait le dépôt → `onDrop` ne se déclenchait jamais) + payload complet dans le `dataTransfer`.
- **Auto-refresh** (toutes les 45 s en lecture + au retour de focus) pour refléter les changements
  faits ailleurs, sans jamais écraser une édition en cours.
- ⚠ Nécessite le **backend ≥ 1.59** (endpoints `PATCH /wiki/books|shelves/{id}`, `POST
  /wiki/books/{id}/deplacer`) : sur un backend plus ancien, déplacer/renommer renvoyaient 404.

## [v1.59.0] — 2026-08-26 — Gérer le wiki depuis Matothèque (déplacer / renommer)

### Ajouté
- **Wiki → Liste des livres** devient éditable, avec répercussion **directe dans BookStack**
  (aucune étape de synchro séparée) :
  - **Glisser-déposer** un livre d'une étagère à l'autre (ou vers « Sans étagère » = détacher).
    Le déplacement ajoute d'abord à la cible puis retire de la source (jamais de livre orphelin).
  - **Renommer** un livre (✏️ au survol de la carte) ou une étagère (✏️ sur l'en-tête).
- Backend : `bookstack_service.{retirer_livre_etagere,renommer_livre,renommer_etagere}` +
  endpoints `PATCH /wiki/books/{id}`, `PATCH /wiki/shelves/{id}`, `POST /wiki/books/{id}/deplacer`.
  Renommage d'étagère : la liste de livres est réinjectée pour ne pas la vider.

## [v1.58.2] — 2026-08-26 — « Créer » : onglet « Récapitulatif » à vide (plus « Aperçu »)

### Modifié
- Dans « Créer », tant qu'aucun contenu n'est généré, l'onglet (et le titre du panneau résultat)
  s'appelle **« Récapitulatif »** au lieu de « Aperçu » — à vide c'est une check-list de préparation,
  pas un aperçu. Il redevient « Aperçu » une fois le rapport prêt. *(Les onglets Rendu/Source/Éditer
  étaient déjà masqués tant qu'il n'y a pas de contenu.)*
- Rappel : la version affichée dans l'UI vient de `/api/version` (backend) → le backend est désormais
  rebâti à chaque bump pour que l'affiché colle à la version.

## [v1.58.1] — 2026-08-26 — Passerelle : message prêt-à-coller pour le « claude projet »

### Ajouté
- À la création/rotation d'un jeton, un **chevron repliable « Voir le message à donner au claude
  projet »** ouvre une **fenêtre éditable** (textarea) pré-remplie avec le message complet : adresse
  de la passerelle (déduite de l'hôte + port 8008), jeton, livres autorisés, exemple de manifeste
  JSON et étapes de publication. Bouton **« Copier le message »**. Éditable avant copie (ajuster
  l'adresse/port si besoin).

## [v1.58.0] — 2026-08-26 — UI d'administration de la passerelle (projets & jetons)

### Ajouté
- **Paramètres → Wiki BookStack → « Passerelle de publication (projets & jetons) »** : gérer les
  projets externes autorisés à publier sur le wiki, sans passer par `curl`. Créer un projet (nom +
  liste blanche de livres) → **jeton affiché une seule fois** avec bouton « Copier » ; **régénérer**
  le jeton (rotation) ; **révoquer/réactiver** ; **modifier la liste blanche**. Message dédié si
  l'image backend déployée ne contient pas encore le routeur passerelle. `passerelleApi` +
  composant `PasserelleProjets`.

## [v1.57.7] — 2026-08-26 — Version dans l'UI + refresh du widget Tâches à l'ouverture

### Corrigé
- **Version applicative de nouveau affichée** (fini « vdev ») : les images backend étaient bâties
  sans `--build-arg APP_VERSION` → l'image figeait `APP_VERSION=dev` (le fichier `VERSION` n'est pas
  dans le contexte `./backend`). Le backend est désormais bâti en injectant la version.

### Ajouté
- **Rafraîchissement à l'ouverture du menu « Tâches »** : ouvrir le widget force un `poll()` immédiat
  (au lieu d'attendre le prochain tick de 2,5 s) → l'état affiché est toujours frais.

## [v1.57.6] — 2026-08-26 — « Annuler » effectif sur les tâches longues

### Corrigé
- **« Annuler » désormais effectif** sur les jobs longs. Le mécanisme base (drapeau
  `jobs.annulation_demandee` posé par l'API, relu par le worker à chaque tick → `ctx.cancelled`)
  était en place mais **seule l'indexation** le vérifiait. Ajout de la vérification `ctx.cancelled`
  aux autres boucles longues : **réorganisation** (appliquer/annuler), **indexation d'un connecteur
  cloud**, **indexation du wiki** — arrêt propre entre deux éléments (ce qui est fait est committé,
  le résultat porte `annule: true`). *(En prod, le worker est un conteneur séparé : l'ancien drapeau
  en mémoire du process API lui était invisible → le bouton ne faisait rien.)*

## [v1.57.5] — 2026-08-26 — Mode sombre : fin de la sur-brillance des blocs teintés

### Corrigé
- **Cadres/fonds colorés « éblouissants » en mode sombre** (ex. « 1. Choisis un dossier » dans
  Décrire les images) : les surfaces `-50` colorées (bleu/rouge/vert/violet/ambre…) et leurs
  bordures `-100/-200` n'étaient pas remappées (le remap global ne couvrait que gris/blanc) →
  elles restaient très claires. Ajout d'un remap sombre **par teinte** (couleur sémantique
  conservée, faible luminance) dans `index.css` + éclaircissement des textes d'accent `-800`
  pour la lisibilité. Corrige tous ces blocs d'un coup, pas seulement celui signalé.

## [v1.57.4] — 2026-08-26 — Fix : progression > 100 % + sur-brillance du logo (sombre)

### Corrigé
- **Progression d'indexation faussée** (« 40047 / 34290 fichiers » à 100 %) : l'endpoint
  `/sources/{id}/progression` borne désormais `fait ≤ total` et renvoie un `pct` clampé [0,100] ;
  `IndexedSourcesSummary` l'affiche sans dépassement. (Le message côté « Tâches » était déjà borné.)
  Fix de fond — progression PAR job — reste un chantier séparé.
- **Sur-brillance blanche du logo en mode sombre** : le badge (feuilles blanches pleines) sur la
  sidebar sombre était le seul élément « éblouissant » en thème sombre → atténué (`dark:brightness-75`).

## [v1.57.3] — 2026-08-26 — Paramètre : repli par défaut des étagères Wiki

### Ajouté
- **Paramètres → Wiki BookStack → Affichage du menu Wiki** : un **interrupteur** « Replier les
  étagères par défaut ». Quand il est activé, les sections d'étagères de « Wiki → Liste des livres »
  démarrent repliées (chevron ▸) ; on peut toujours en déplier une à la main. Préférence persistée
  en local (store `matotheque-wiki-prefs`, sans réseau).

## [v1.57.2] — 2026-08-26 — Étagère aussi dans « Wiki › Publier »

### Ajouté
- Le sélecteur d'**étagère (optionnel)** manquait sur la page pleine **Wiki › Publier**
  (elle a son propre formulaire, distinct de la modale « Publier sur le wiki »). Ajouté à
  l'identique : étagère existante ou **nouvelle** → le livre de la page y est rangé.

## [v1.57.1] — 2026-08-26 — Étagères : repli menu Wiki + choix à la publication

### Ajouté
- **Étagères pliables/dépliables** dans « Wiki — Liste des livres » : chaque groupe d'étagère se
  replie d'un clic (chevron), pratique quand il y a beaucoup de livres.
- **Choix d'étagère à la publication** : la modale « Publier sur le wiki » (rapports/documents)
  propose désormais un sélecteur d'étagère optionnel (existante ou **nouvelle**) ; le livre de la
  page y est rangé automatiquement. `GET /bookstack/targets` renvoie les étagères ; `POST
  /bookstack/publish` accepte `shelf_id` / `new_shelf` (rattachement résilient — n'invalide jamais
  une page déjà publiée).

## [v1.57.0] — 2026-08-26 — Passerelle wiki : étagères (Lot 1b) + bandeau auto

### Ajouté
- **Étagères BookStack (Lot 1b)** : le manifeste de publication accepte un champ `etagere` ; la
  passerelle rattache (idempotent) les livres du manifeste à cette étagère
  (`ensure_shelf` + `ensure_book_in_shelf`). Le rattachement est résilient — un souci d'étagère
  n'annule pas la publication des pages.
- **Menu Wiki regroupé par étagère** : `GET /wiki/books` renvoie désormais `shelves`
  (`[{id, name, book_ids}]`) et la page « Wiki — Liste des livres » regroupe les livres par
  étagère (section « Sans étagère » pour les livres non rattachés ; affichage à plat conservé
  s'il n'existe aucune étagère).
- **Bandeau « généré automatiquement » (§6.3)** : chaque page publiée par la passerelle est
  préfixée d'un avertissement rappelant qu'elle est gérée par le projet source et qu'une édition
  manuelle sera écrasée à la prochaine synchronisation. La déduplication reste calculée sur le
  markdown d'origine du manifeste (le bandeau ne déclenche pas de fausse mise à jour).

## [v1.47.1] — 2026-07-24 — Fix : route images-count vs {document_id}

### Corrigé
- `GET /documents/images-count` (1 segment) était **intercepté par `/documents/{document_id}`**
  → « ID de document invalide ». Renommé **`/documents/images/count`** (2 segments) → plus de collision.

## [v1.47.0] — 2026-07-24 — Décrire les images : ciblage par DOSSIER

### Ajouté
- **Cibler un dossier** pour la description IA vision des photos : au lieu de tout le NAS (48 000
  images = plusieurs jours de GPU), on sélectionne un **dossier précis** (explorateur de source) →
  seules ses images sont décrites. `analyze-batch?scope=images&prefixe=…` + `GET /documents/images-count?prefixe=`
  (nombre d'images du dossier). Bouton adaptatif « Décrire ce dossier (N) » / « Décrire tout (N) ».

## [v1.46.0] — 2026-07-24 — Badge « Tâches » : vrais chiffres (en cours / en file)

### Corrigé
- **Badge « Tâches · N » trompeur** : il comptait les tâches actives d'une **fenêtre de 20 jobs**
  récupérés → sur un gros lot il affichait « ·22 » (la fenêtre), pas la réalité. Nouveau endpoint
  `GET /jobs/stats` (COUNT en base) → le badge affiche **« N en cours · M en file »** exacts
  (ex. « 2 en cours · 4944 en file »).

## [v1.45.0] — 2026-07-24 — Maintenance : compteurs « Total · Traité · Restant »

### Ajouté / Modifié
- **Compteurs clairs** sous chaque action de maintenance : au lieu du seul « restant » (source de
  confusion), une ligne **Total N · Traité N (%) · Restant N · en file** — auto-actualisée. `maintenance/
  counts` renvoie `enrich_total` (docs enrichissables), `images_total` (toutes les images), `docs_total`.
- **Lots d'images plus gros** : « Décrire les images » enfile jusqu'à **5000** images par clic (au lieu de
  1000) — moins de clics pour un gros corpus ; message de confirmation précisant la taille du lot et le reste.

## [v1.44.0] — 2026-07-24 — Maintenance : avancement des lots en direct

### Ajouté / Modifié
- **Indicateur d'avancement vivant** sous les actions de maintenance (Paramètres) : le chiffre du
  bouton est le **nombre restant** à traiter (candidats), et une ligne sous chaque action affiche
  désormais **« N en file/en cours · M restant »**, **auto-actualisée toutes les 15 s** tant que des
  jobs tournent → le « restant » décroît en direct sans recharger la page. `maintenance/counts`
  renvoie `jobs_enrich` et `jobs_analyze` (files réelles, comptées en base).

## [v1.43.0] — 2026-07-24 — Rendre les photos cherchables (IA vision, ciblé)

### Ajouté
- **Bouton « Décrire les images (IA vision) »** (Paramètres → Maintenance) : génère une
  **description/OCR** des **photos cataloguées** via le modèle vision (qwen2.5vl) → texte +
  embeddings → **cherchables par contenu** (elles ne l'étaient pas — cataloguées nom+taille seuls).
- **Scope `images`** sur `/documents/analyze-batch` : cible **uniquement les images** OCR-ables, pour
  **ne pas rapatrier vidéos/audio** (que `media`/`all` téléchargeraient pour rien → risque disque).
  Compteur `images` ajouté à `/documents/maintenance/counts`.

> Le pipeline `analyze` (fetch → Tika → OCR/description vision → enrichissement → embeddings) existait
> déjà ; il manquait un déclencheur **sûr et ciblé** pour les photos. Traitement **long et GPU-lourd**.

## [v1.42.0] — 2026-07-24 — Recherche : regrouper par type de fichier

### Ajouté
- **Regroupement des résultats de recherche par TYPE** : sélecteur **Grouper : Aucun / Pertinence /
  Type**. « Type » range les résultats par catégorie de fichier (📕 PDF, 📄 Document, 📊 Tableur,
  📑 Présentation, 🖼️ Image, 🎵 Audio, 🎬 Vidéo, 🗜️ Archive) en sections repliables. Chaque résultat
  porte un champ `type_groupe` dérivé de l'extension (aucune réindexation).

### Note
- **Les images/photos n'apparaissent pas dans la recherche par contenu** : elles sont **cataloguées**
  (nom + taille) **sans extraction de texte ni embedding** → introuvables par mots-clés (sauf via leur
  nom de fichier) et absentes du sémantique. Les rendre cherchables nécessiterait une **description IA
  vision** à l'indexation (chantier séparé).

## [v1.41.1] — 2026-07-24 — Fix : l'endpoint /api/search utilise enfin tsv + ANN

### Corrigé
- **🔴 Les optimisations E7 (sémantique ANN) et 1.41.0 (full-text tsv) n'étaient PAS actives via
  l'API** : elles avaient été appliquées à la classe `services/search_service.py`, mais l'endpoint
  `/api/search` utilise ses **propres** fonctions dans `routers/search.py` — restées sur l'ancien
  code (recalcul `to_tsvector`, scan complet 4096). D'où les recherches toujours à ~30 s malgré les
  déploiements. Correctif porté dans `routers/search.py` : full-text via `ts_rank(d.tsv, …)`
  (**5 s → 0,1 s** mesuré API dev) et sémantique via l'**ANN 1024-d indexé HNSW** (**70 ms** hors
  embedding Ollama), avec repli sur l'ancien comportement si `tsv`/`embedding_small` absents.

## [v1.41.0] — 2026-07-24 — Full-text : colonne tsvector stockée (perf)

### Corrigé
- **Recherche texte/hybride encore lente malgré l'index (1.40.x)** : l'index GIN accélère le FILTRE
  (`@@`), mais le CLASSEMENT `ts_rank(to_tsvector(texte || nom), …)` **recalculait le tsvector sur le
  texte COMPLET de chaque document trouvé** → ~30 s sur un terme fréquent (66 k docs). Correctif :
  colonne **`tsv` tsvector STOCKÉE** (générée) + index GIN dédié → `ts_rank(d.tsv, …)` sans recalcul.
  Mesuré : **1800 ms → 4 ms** (terme « chat », dev). L'index d'expression redondant est retiré.
  La colonne est **générée** (auto-maintenue) ; 1ᵉ démarrage = réécriture unique (~70 s, non bloquante
  car le backend n'a pas de healthcheck). Requête avec **repli** sur l'expression si la colonne manque.

## [v1.40.1] — 2026-07-24 — Fix : index full-text créé de façon robuste

### Corrigé
- L'index full-text (1.40.0) était créé **dans la transaction principale d'`init_db`** : si une DDL
  précédente échouait (transaction empoisonnée), sa création était **sautée en silence** → recherche
  texte toujours lente en prod. Il est désormais créé dans **sa propre transaction** + **`ANALYZE
  documents`** (stats du planificateur). Robuste et vérifiable (log si échec).

## [v1.40.0] — 2026-07-24 — Recherche full-text indexée (perf, suite E7)

### Corrigé
- **Recherche texte/hybride ~1000× plus rapide** : la requête cherche sur `texte_extrait || ' ' || nom`,
  mais l'index GIN historique ne couvrait que `texte_extrait` → **expression différente → index jamais
  utilisé → scan séquentiel de tout le corpus** (~30 s sur 66 k docs, d'où les « timeout 30000ms » de
  l'UI). Ajout de l'index GIN sur l'**expression exacte** de la requête → **Seq Scan → Bitmap Index Scan**
  (coût 20260 → 23). Complète l'accélération sémantique (E7, v1.38.0). Index créé au démarrage (idempotent).

## [v1.39.0] — 2026-07-24 — Connecteur reMarkable (E5)

### Ajouté
- **Connecteur reMarkable Cloud** (lecture) : indexe les PDF/EPUB et notes d'un compte reMarkable.
  Appairage par **code à usage unique** (`my.remarkable.com/device/desktop`) → device token durable
  chiffré ; user token dérivé à chaque accès. `services/connectors/remarkable.py` (register/test/
  browse/walk/fetch), arbre reconstruit depuis la liste plate (`parse_docs`/`collect_documents`,
  5 tests). `POST /connectors/remarkable/pair` + UI Paramètres. Réutilise le pipeline connecteur.
  ⚠️ API cloud non officielle → à valider sur un compte réel. Doc `docs/setup-remarkable.md`.

## [v1.38.0] — 2026-07-24 — Recherche sémantique accélérée (E7)

### Ajouté / Modifié
- **Recherche sémantique ~10 000× plus rapide** (mesuré : **41 s → 4 ms** sur 78 k vecteurs, à
  chaud). Cause de la lenteur : les embeddings **4096-d** ne sont **pas indexables** par pgvector
  (plafond 2000 dims) → chaque recherche scannait tous les vecteurs. Solution **Matryoshka** :
  colonne `embedding_small` **1024-d** dérivée du 4096 (préfixe L2-normalisé — `qwen3-embedding`
  est MRL, donc **aucun ré-embed**), **indexée HNSW** ; la recherche fait un **ANN indexé** puis
  agrège par document. **Qualité conservée** (recouvrement top-10 = 9-10/10 vs scan complet).
- **Backfill + index en tâche de fond** (worker, une seule fois, protégé par verrou d'avis ;
  `CREATE INDEX CONCURRENTLY` non bloquant) → aucune interruption au déploiement. Les nouveaux
  embeddings remplissent `embedding_small` **à l'insertion**. Repli automatique sur le scan complet
  tant que le backfill n'est pas terminé.

## [v1.37.0] — 2026-07-24 — Transcription audio (E5 : openplaud)

### Ajouté
- **Transcription audio → texte** : les fichiers audio (dictaphone **Plaud/openplaud**, mémos,
  réunions…) sont **transcrits** puis indexés/enrichis/vectorisés comme un document — donc
  **recherchables** en plein texte ET en sémantique. `services/transcription_service.py` appelle un
  **serveur local compatible OpenAI** `/v1/audio/transcriptions` (faster-whisper-server, LocalAI…) ;
  aucun tiers. Config **Paramètres → Transcription audio** (URL/modèle/langue/clé, test de connexion).
- **Routage média unifié** (`folder_watcher.media_a_cataloguer`) : l'audio est envoyé à l'extraction
  (transcription) dès qu'un serveur est configuré, sinon **catalogué** sans texte comme avant — sur
  tous les points d'indexation (upload, watch local, synchro SMB, connecteurs, restauration corbeille).
- Voyant du service dans **Paramètres → Services**. Doc `docs/setup-transcription.md`. 10 tests.

## [v1.36.0] — 2026-07-24 — Documents liés sur la fiche (E3, suite)

### Ajouté
- **Section « Documents liés »** dans la fiche document (GED) : liste les documents **liés**
  (liens validés partageant une référence — BC ↔ facture…), avec la **référence** et la nature
  du lien. Un clic **ouvre la fiche** du document lié (navigation de proche en proche). Alimentée
  par `GET /links/document/{id}` (déjà livré en v1.33.0) → complète la boucle de la page « Liens ».

## [v1.35.0] — 2026-07-24 — Responsive / smartphone (Phase 2)

### Ajouté / Modifié
- **GED sur mobile** : les filtres (catégories + tags), jusqu'ici **inaccessibles** sous `md`,
  s'ouvrent désormais dans un **tiroir latéral** via un bouton **« Filtres »** (barre de recherche).
  Sélectionner une catégorie/un tag referme le tiroir. Sur bureau, l'aside reste fixe (inchangé).
- **Regroupements sur mobile** : passage au motif **maître-détail « une vue à la fois »** — la liste
  occupe tout l'écran, l'ouverture d'un regroupement affiche le détail en plein écran avec un bouton
  **« ← Retour »**. Les deux volets côte à côte reviennent dès `md` (bureau inchangé).
- **Lecteur Wiki (livres BookStack) sur mobile** : le **sommaire** (256 px fixes) devient un **tiroir**
  ouvert par une icône ☰ ; le clic sur une page le referme. Contenu en pleine largeur.
- **Finitions** : marges de page adoucies sur mobile (Réorganiser `p-3`), formulaire de prompt et
  libellés de modèles empilés sous `sm` au lieu de colonnes trop étroites.

> Suite de la Phase 1 (v1.30.0, menu burger + pages principales). Audit responsive poursuivi
> page par page ; il reste des écrans secondaires à peaufiner au fil de l'usage.

## [v1.34.0] — 2026-07-24 — Connecteur WebDAV générique (E1)

### Ajouté
- **Connecteur WebDAV** (lecture seule, HTTP Basic — **pas d'OAuth**) : indexe **Nextcloud /
  ownCloud**, **Infomaniak kDrive**, **Synology WebDAV**, serveurs `mod_dav`… `services/connectors/
  webdav.py` (test/browse/walk/fetch/stream via `PROPFIND` + `GET`, parsing `multistatus`
  namespacé, gestion des chemins encodés %XX, mot de passe chiffré Fernet). 7 tests de parsing.
- **UI Paramètres → Connecteurs cloud → WebDAV** : formulaire **URL + identifiants** →
  « Connecter et tester » (pastille verte/rouge immédiate), puis **Indexer** (tâche durable) /
  Déconnecter. Un compte = une Source (multi-comptes), documentée dans `docs/setup-webdav.md`.
- Réutilise **tout** le pipeline connecteur existant (indexation durable, synchro périodique,
  « Dossiers indexés » sous `webdav://<id>/…`) sans code spécifique — traitement générique par type.

## [v1.33.0] — 2026-07-24 — Liens documentaires : BC ↔ facture (E3)

### Ajouté
- **Nouvelle page « Liens »** : relie les documents qui **partagent une référence** (n° de bon de
  commande, de facture, de devis…) détectée dans leur texte. **Hybride** (demande utilisateur 01/07) :
  extraction de références par motifs FR + détection du **type documentaire** (BC / facture / devis /
  BL) → un lien entre types complémentaires (**BC ↔ facture**) est proposé avec une confiance plus
  forte. 100 % local, sans IA (rapide et déterministe).
- **Flux de validation** : « Analyser » propose des paires → l'utilisateur **valide**, **rejette** ou
  crée un lien **manuel**. Rien n'est lié automatiquement ; un lien **rejeté n'est jamais reproposé**.
  Périmètre d'analyse optionnel (cibler un dossier via l'explorateur de source).
- API `/api/links` : `scan`, liste par statut, `validate`/`reject`/suppression, création manuelle,
  et `GET /links/document/{id}` (liens validés d'un document, pour une future intégration à la fiche).
- Table `document_links` (paire normalisée, statut suggéré/validé/rejeté, référence, score, origine).

## [v1.32.0] — 2026-07-23 — Doublons avancés (E4)

### Ajouté / Modifié
- **Détection de scan disque en 3 passes** : `taille → hash partiel (4 Ko) → SHA256 complet`. La
  passe intermédiaire écarte les fichiers de même taille mais de début différent **sans lire leur
  contenu entier** → beaucoup moins d'I/O sur un gros volume.
- **Photos floues** (nouvel onglet Doublons) : détecte les images à **faible netteté** via la
  **variance du Laplacien** (numpy + Pillow, sans OpenCV). Seuil réglable, liste triée du plus flou
  au moins flou, mise en **quarantaine réversible** (comme les doublons). `GET /duplicates/blurry`.

## [v1.31.5] — 2026-07-23

### Corrigé
- **🔴 OAuth Google `invalid_client` — LA cause** : le connecteur envoyait à Google le
  `gdrive_client_secret` **encore chiffré** (`enc::…`, valeur Fernet) au lieu du secret en clair
  (`GOCSPX-…`). Google rejetait donc systématiquement (« The provided client secret is invalid »),
  quel que soit le secret saisi. Le connecteur **déchiffre** désormais le secret avant l'échange
  (comme BookStack). Diagnostic de forme du secret ajouté (préfixe + longueur, sans le révéler) et
  `strip()` des identifiants (garde-fou copier-coller).

## [v1.31.3] — 2026-07-23

### Corrigé
- **OAuth Google : `invalid_client` malgré un secret correct** — le flux OAuth lisait le
  `gdrive_client_secret` du cache du process (multi-uvicorn), qui pouvait être périmé après une
  mise à jour de config → échange du code refusé (« The provided client secret is invalid »).
  `oauth/start` et `oauth/callback` **rechargent désormais la config depuis la base** avant usage
  → plus besoin de redémarrer le backend après avoir changé le secret.

---

## [v1.31.2] — 2026-07-23

### Ajouté / Modifié
- **Pastille de connexion** sur les comptes Google Drive (Paramètres → Connecteurs cloud) :
  **verte** = connexion établie, **rouge** = à reconnecter, grise = vérification. Testée à
  l'affichage via `/connectors/{id}/test`.
- **Sources cloud dans « Dossiers indexés »** : un compte Drive indexé apparaît dans le récap
  (icône ☁, libellé « Google Drive ») au même titre que le NAS.
- Les comptes cloud ne s'affichent plus dans « Sources de fichiers » (local/smb) — ils se gèrent
  dans « Connecteurs cloud » (leurs boutons Explorer/Synchroniser ne s'y appliquaient pas).

---

## [v1.31.1] — 2026-07-23

### Corrigé
- **Sources cloud (Google Drive…) invisibles dans « Dossiers indexés »** : l'arbre par source
  cherchait au préfixe `root/` alors que les documents connecteur sont rangés sous
  `{type}://{source_id}/…`. `_prefixe_source` reconnaît désormais les types connecteur → l'arbre
  « Dossiers indexés » affiche bien le contenu d'un Drive (les docs étaient déjà cherchables en GED).

---

## [v1.31.0] — 2026-07-23 — Connecteur Google Drive (OAuth, lecture)

### Ajouté
- **Connecteur Google Drive** (lecture seule, `drive.readonly`) : un **compte Google = une Source**
  (multi-comptes). `services/connectors/gdrive.py` (test/browse/walk/fetch/stream, refresh_token
  chiffré, pagination Drive API v3, **export** des documents Google natifs Docs→PDF / Sheets→xlsx /
  Slides→pptx). Réutilise le pipeline d'indexation durable existant.
- **Flux OAuth** : `GET /connectors/oauth/start` (URL de consentement) + `GET /connectors/oauth/callback`
  (échange du code → refresh_token → création de la Source → retour Paramètres). Config
  `oauth_redirect_uri` (à fixer en prod derrière proxy).
- **UI Paramètres → Connecteurs cloud** : bouton **« Connecter un compte Google »** + liste des
  comptes (Indexer / Déconnecter). Retour OAuth signalé par un toast.

> ⚠️ **Prérequis utilisateur** : créer l'app OAuth Google Cloud (cf. `docs/setup-google-drive-oauth.md`)
> et saisir Client ID/Secret. Connecteur **cloud** (accès réseau sortant vers Google).

---

## [v1.30.0] — 2026-07-23 — Responsive / smartphone (Phase 1)

### Ajouté / Modifié
- **Menu burger** : sous `md` (tablette/smartphone), la barre de navigation latérale devient un
  **tiroir off-canvas** ouvert par un bouton ☰ dans l'en-tête (fond assombri, fermeture au clic
  hors zone ou à la navigation). Au-delà, la sidebar reste fixe (bureau inchangé).
- **Page « Créer » empilée** sous `lg` : les colonnes configuration / résultat se placent l'une
  **sous l'autre** (au lieu de côte à côte illisible sur écran étroit) ; le panneau résultat garde
  une hauteur minimale utilisable.
- **En-tête compact** : les libellés des voyants de services (Tika/Ollama/n8n/Antivirus) se
  réduisent aux pastilles sous `sm`.
- **GED** : les filtres latéraux se masquent sous `md` (recherche + grille de cartes conservées,
  déjà responsive) ; **marges de page** adoucies sur mobile (`p-3` au lieu de `p-6`).

> Premier passage responsive (menu + pages principales). Audit page-par-page complet à poursuivre.

---

## [v1.29.0] — 2026-07-23 — Préparation du modèle (cold-load)

### Ajouté
- **Indicateur « modèle prêt / à préparer »** à côté du sélecteur de modèle (page Créer) : dit si
  le modèle des rapports est **chargé en mémoire** (⚡ prêt — génération instantanée) ou à froid.
- **Bouton « préparer »** : charge le modèle à l'avance, pour éviter l'attente de chargement au clic
  « Générer » (utile pour un gros modèle lent à charger). API `GET /system/model-status` +
  `POST /system/warm-model`. Complète le pré-chargement automatique du worker.

---

## [v1.28.0] — 2026-07-23 — Indexation continue Phase 4

### Ajouté
- **Purge assistée des documents « disparus »** : les fichiers supprimés du NAS sont marqués
  `absent` par la synchro (jamais supprimés d'office). Un **badge « N disparu(s) »** apparaît sur
  la source (Paramètres → Sources) → **modale de revue** listant les documents disparus, avec
  suppression **par sélection** ou **tout**, après confirmation. Ne touche à aucun fichier ;
  l'index se reconstruit si les fichiers reviennent. API `GET /sources/{id}/absents`,
  `POST /sources/{id}/purge-absents`.

### Corrigé
- **Énumération SMB (walk) annulable** : le parcours récursif d'un partage tournait dans un thread
  **non interruptible** → « Annuler » ne prenait effet qu'**après** l'énumération (parfois plusieurs
  minutes sur 65k fichiers). Un `cancel_event` (positionné à l'annulation) l'arrête désormais
  proprement, avant la connexion et à chaque dossier.

---

## [v1.27.0] — 2026-07-23 — Observabilité Phase 2 (traçabilité)

### Ajouté
- **Journal d'activité métier de bout en bout** (`audit_events`) : chaque opération (indexation,
  synchro, génération, analyse, enrich…) est tracée par un **`correlation_id`** commun qui relie
  les couches **API → worker** (`queued` → `start` → `success`/`error`/`cancelled`), avec **acteur**,
  **statut** et **durée** mesurée.
- **Instrumentation automatique** de tous les jobs durables (au cœur du worker) + de la génération
  de rapport — aucun handler à modifier ; le `correlation_id` est injecté à l'enfilement.
- **Page Logs → « Traçabilité »** : liste filtrable par action ; clic sur une ligne → **chaîne
  complète** de la corrélation (tout l'enchaînement d'une même opération, dans l'ordre).
- API `GET /api/audit` (filtres action/statut/acteur/correlation_id) + `GET /api/audit/actions`.

---

## [v1.26.0] — 2026-07-23 — Sprint N+1 (finitions + irritants)

### Corrigé
- **🔴 « Annuler » sans effet sur un job en cours** : le drapeau d'annulation était un `set` en
  mémoire de l'API, alors que le job tourne dans le **worker** (process séparé) → jamais vu.
  Désormais **en base** (`jobs.annulation_demandee`), relu par le worker à chaque tick. Vérifié :
  un job `running` passe bien `cancelled`.
- **Jobs fantômes** : compteur de **reprises** (running→pending après crash) — au-delà de 3, le job
  est déclaré `failed` au lieu de boucler ; et **purge auto des `pending` d'un type sans handler**
  (ex. `rapport`) restés trop longtemps (ce qu'on nettoyait à la main).
- **🐞 % de progression > 100 %** dans le widget Tâches (`40047/34290`) : affichage borné à
  `min(fait, total)` (garde-fou ; le fond — progression par job — reste un chantier séparé).
- **Fiabilité enrichissement** : les sous-documents de ZIP étaient marqués `enriched`
  inconditionnellement (même sans métadonnées IA) → alignés sur le pipeline (`enriched` seulement
  si l'IA a produit des métadonnées, sinon `extracted`).
- **« Ré-analyser » (analyze-batch)** : l'erreur est désormais **journalisée** (type + message +
  scope) et renvoyée clairement, au lieu de « erreur affichée mais rien dans les logs ».

### Modifié
- **Paramètres — navigation persistante** : le fil d'ariane (« Tous les paramètres / … ») **et la
  barre de recherche** restent visibles **en vue détail** d'une section ; chercher en vue détail
  ramène au tableau de bord filtré (plus besoin de ressortir).

---

## [v1.25.1] — 2026-07-23

### Modifié
- **Export PDF nettement plus soigné** : nouveau rendu « document » du Markdown — bandeau de
  titre à accent indigo + sous-titre daté (« Matothèque · Rapport généré le … »), titres de
  section colorés à bordure d'accent, **tableaux à en-tête indigo et lignes zébrées**, listes à
  puces colorées, citations en encart arrondi, bloc **Sources** détaché, **pied de page paginé**
  (« Page N / M »). Rendu vérifié visuellement. Auto-suffisant (aucune ressource externe).

---

## [v1.25.0] — 2026-07-23

### Ajouté — Historique des rapports (persistant)
- **Onglet « Historique »** dans le panneau de la page Créer : liste des rapports générés,
  **archivés en base** (table `rapports`) — survivent au rechargement, à la fermeture du navigateur
  et au redémarrage (l'ancien historique était un tampon de session perdu au F5). Chaque rapport
  garde titre, date, modèle, documents sources et contenu.
- **Rouvrir** un rapport d'un clic (chargé dans l'onglet Rendu).
- **Suppression par cases** : sélection individuelle + « tout sélectionner » + « tout vider »
  (avec confirmation).
- **Purge automatique** réglable (Jamais / 7 / 30 / 90 j / 1 an) — appliquée par le worker
  (`rapports_purge_jours`). Réglage exposé dans l'onglet Historique.
- Endpoints `/api/rapports` (liste, détail, suppression individuelle/lot, purge).

---

## [v1.24.10] — 2026-07-23

### Corrigé
- **🔴 Export PDF cassé** (`'super' object has no attribute 'transform'`) : `pydyf` 0.12 (installé
  faute d'épingle) casse WeasyPrint 62.3. **`pydyf==0.10.0`** épinglé.
- **🔴 Export DOCX cassé** (`Permission denied: /app/storage/exports/…`) : le conteneur (uid 10001)
  ne pouvait pas écrire dans le montage `exports`. **Les deux exports génèrent désormais le fichier
  EN MÉMOIRE** (BytesIO / `write_pdf()` sans cible) et le renvoient directement — **aucune écriture
  disque**, donc plus aucune dépendance aux droits du montage. Nom de fichier encodé UTF-8.

---

## [v1.24.9] — 2026-07-23

### Ajouté
- **Liste des documents sources à la fin du rapport** : un bloc « **Sources** *(N documents)* »
  est ajouté en fin de rapport généré (traçabilité — visible dans tous les exports PDF/DOCX/MD/Wiki).
  Répond au doute « combien de documents ont été traités ? ».
- **Pré-chargement du modèle de rapport** (`ollama_prewarm_enabled`, défaut activé) : le worker
  maintient le gros modèle (Qwen3.6-35B, ~44 Go) **résident** — au démarrage puis périodiquement
  (`ollama_prewarm_minutes`, 20 min < keep_alive). Évite qu'un premier rapport après inactivité
  doive recharger 44 Go **à froid** (lent, risque de 502 via le proxy). Modèle lu dans les
  Paramètres (`model_for("rapport")`), jamais en dur. *Approche à améliorer (cf. suivi).*

---

## [v1.24.8] — 2026-07-23

### Corrigé
- **🔴 « Aucun handler pour le type 'rapport' » — génération de rapport tuée par une course** : le
  rapport crée une ligne `jobs` (type `rapport`) pour le suivi, mais il est traité par une *background
  task* FastAPI, **pas** par le worker durable. Or `_claim` réclamait **tout** job `pending` sans
  filtrer le type → le worker raflait le job `rapport`, ne trouvait pas de handler et le marquait
  `failed`. Masqué tant que la file débordait de synchros (la background task gagnait toujours la
  course) ; dès la file vidée, le worker gagnait et **tuait chaque rapport**. Le worker ne réclame
  désormais **que les types possédant un handler enregistré**.

---

## [v1.24.7] — 2026-07-23

### Ajouté / Modifié — page « Créer », panneau de résultat
- **Nouvel onglet « Rendu »** — les onglets deviennent **Aperçu | Rendu | Source | Éditer**. Le
  document rendu (Markdown → HTML) et les boutons de téléchargement vivent désormais dans « Rendu »,
  séparés de la préparation. **Bascule automatique** sur « Rendu » au clic « Générer ».
- **Export Markdown `.md`** ajouté à côté de PDF / DOCX / Wiki (téléchargement direct, aucun backend).
- **Onglet Aperçu = préparation + avancement** : la check-list « Votre rapport » (Documents / Mode /
  Instruction) est **figée** au lancement, et un bloc **réflexion/avancement** vivant apparaît en
  dessous — « ⏳ le modèle réfléchit… » pendant le silence (`think:false`), puis « ✍️ rédaction —
  N caractères » avec chrono, enfin « ✅ rapport prêt ». Répond à « je le vois où ? à quoi sert
  *Votre rapport* ? ».
- **Onglets conditionnels** : Rendu / Source / Éditer n'apparaissent qu'une fois une génération
  démarrée (avant : seul Aperçu) — corrige l'affichage prématuré des onglets (ROADMAP ④).

---

## [v1.24.6] — 2026-07-21

### Corrigé
- **Le rapport contenait le raisonnement du modèle en anglais** (« Here's a thinking process:
  1. Analyze User Input… ») au lieu d'un résumé propre : les modèles de raisonnement
  (Qwen3.6-35B) déversent leur *chain-of-thought* dans la sortie. Une consigne système seule
  s'est révélée **insuffisante** (testé : le modèle l'ignore). Corrigé via le paramètre Ollama
  **`think: false`**, qui supprime le raisonnement visible. **Agnostique du modèle** : Ollama
  l'ignore pour ceux qui n'en ont pas (vérifié sur llama3.1 et ministral-3, sans erreur) — donc
  valable quel que soit le modèle choisi dans les Paramètres, sans rien coder en dur.

---

## [v1.24.5] — 2026-07-21

### Corrigé
- **`ReadTimeout` sur la génération de rapport** — diagnostiqué grâce au message d'erreur enfin
  nommé (v1.24.4) : le délai client était de **5 min**, insuffisant pour le chargement **à froid**
  d'un modèle de 43 Go, qui reste muet plusieurs minutes avant le premier octet. Porté à **30 min**
  (`config.py`, `docker-compose.yml`, `.env.example`) et délais **dissociés** : `connect` court
  (10 s) pour qu'un hôte injoignable échoue vite, `read` long pour couvrir le chargement.
  ⚠️ Ce délai borne le **silence avant le premier octet**, pas la durée de génération : dès que
  le flux commence, chaque morceau réarme le compteur.

---

## [v1.24.4] — 2026-07-21

### Corrigé
- **« Erreur de génération : » sans aucune cause** : le code journalisait `str(e)`, or plusieurs
  exceptions httpx (timeout, coupure de connexion) ont un message **vide** — impossible de
  distinguer un délai dépassé d'un modèle absent. On journalise désormais le **type**
  d'exception (toujours présent) et la trace complète, et le job stocke `Type: message`.
- **L'interface annonçait le mauvais modèle** : elle affichait `default_model` (« Auto :
  llama3.1 », 4,9 Go) alors que la génération route **par usage** (`usage_models.rapport` =
  Qwen3.6-35B, **43 Go**). L'utilisateur croyait lancer un modèle rapide et se heurtait à des
  attentes interminables. `/system/models` renvoie maintenant `par_usage`, et l'écran affiche
  le modèle **réellement** appliqué.
- **`keep_alive` oublié sur le chemin des rapports** : `generate()` et les embeddings le
  transmettaient, mais **pas** `generate_stream()`. Le modèle des rapports retombait donc sur le
  défaut d'Ollama (5 min) et se faisait décharger entre deux usages — la requête suivante devait
  recharger 43 Go à froid. C'est la cause directe de l'échec constaté (deux rapports réussis,
  puis échec 1 h 45 plus tard, mêmes documents et même modèle).

---

## [v1.24.3] — 2026-07-21

### Corrigé
- **L'estimation avant génération annonçait « 0 doc · 0 Ko »** alors que des documents étaient
  cochés : elle ne regardait que la liste des documents *chargés en mémoire*, or le picker en
  arbre coche des identifiants sans jamais les charger. Les métadonnées des fichiers cochés
  depuis l'arbre sont désormais mémorisées dans le store.
- **L'estimation de tokens se basait sur la TAILLE DU FICHIER**, pas sur le texte réellement
  envoyé au modèle. Deux PDF de 4,9 Mo (36 000 caractères de texte) étaient annoncés à
  **≈ 1 285 k tokens** avec une alerte « le contenu sera tronqué » — au lieu de **≈ 9 k**, soit
  10× *sous* la fenêtre du modèle. `/documents/tree` renvoie maintenant `texte_longueur`
  (calculé en SQL), et l'estimation s'appuie dessus ; la mention « (approx.) » signale les cas
  où la longueur est inconnue.

---

## [v1.24.2] — 2026-07-21

### Corrigé
- **🔴 Les jobs de synchro finissaient en « échec » alors que le travail était fait** :
  `jsonb_build_object($1, …)` sans cast explicite → asyncpg ne peut pas inférer le type du
  paramètre (`IndeterminateDatatypeError`). Seul l'enregistrement du récapitulatif échouait,
  après une synchro pourtant menée à bien (3 912 nouveaux fichiers indexés sur un périmètre).
  Casts `cast(… AS text)` / `cast(… AS jsonb)` ajoutés. Ce chemin n'avait jamais été exécuté
  avant la mise en production — il l'est désormais par un test de bout en bout.
- **Cocher un dossier sans document exploitable** affichait une erreur rouge trompeuse. Message
  passé en information et reformulé ; la case du dossier se **désactive** dès qu'on sait qu'il
  n'y a rien à cocher (après une tentative, ou dès le dépliage si tous ses fichiers sont
  sans texte).

---

## [v1.24.1] — 2026-07-21

### Corrigé
- **L'explorateur de « Créer » ne montrait pas la même chose que « Paramètres → Dossiers
  indexés »** : un filtre `texte=true` était appliqué **en silence**, masquant les médias
  catalogués et les documents sans texte extrait. Conséquence mesurée : `[MaTo]` affichait
  **92** documents au lieu de **1 043**, et deux dossiers entiers (`[Mode-…]`, `[Sophie]`)
  étaient **totalement invisibles**. L'arbre affiche désormais le **même périmètre**, les
  documents sans texte restant visibles mais **grisés et non cochables** (mention « sans texte »
  + explication au survol), avec une case **« Masquer les documents sans texte »** pour
  retrouver l'ancienne vue à la demande.

---

## [v1.24.0] — 2026-07-21

### Ajouté
- **Synchronisation automatique des sources** — l'indexation devient réellement *continue* :
  sélecteur **« Synchro auto »** par source (désactivée / 1 h / 6 h / 24 h), « dernière : il y a … »
  et récapitulatif du dernier écart affiché sous la source. Un tick worker (5 min) déclenche les
  sources dues ; une source déjà occupée par une synchro **ou** une indexation passe son tour.

### Corrigé
- **🔴 `statut='absent'` violait la contrainte `CHECK` de `documents`** : la synchro aurait échoué
  **en production à la première suppression d'un fichier sur le NAS**. Invisible en développement
  (aucun fichier disparu au premier passage). Contrainte élargie, avec garde-fou idempotent au
  démarrage pour les bases existantes.
- **🔴 Fuite de verrou d'avis Postgres** : `pg_try_advisory_lock` suivi d'un `commit()` rendait la
  connexion au pool, si bien que le `pg_advisory_unlock` s'exécutait sur une **autre** connexion et
  ne libérait rien — verrou pris à vie. Conséquences : la planification des synchros renonçait
  **en silence** à chaque tick, et la **reprise des jobs orphelins au démarrage était sautée depuis
  toujours** (d'où des jobs fantômes bloquant la file). Remplacé par un verrou **transactionnel**
  (`pg_try_advisory_xact_lock`), libéré par le commit.

---

## [v1.23.0] — 2026-07-21

### Ajouté
- **Synchronisation incrémentale des sources** (`POST /api/sources/{id}/sync`, bouton
  **« Synchroniser »**) : compare la source à l'index et ne traite que les **écarts** —
  nouveaux, modifiés, **déplacés**, disparus, revenus. Mesuré sur le NAS : **50 910 fichiers
  reconnus inchangés sans transférer un octet** (ni Tika ni Ollama sollicités) et
  **10 459 nouveaux** détectés, ceux qui n'apparaissaient jamais.
  - un **déplacement** = simple mise à jour du chemin (aucun transfert, aucun doublon, historique conservé) ;
  - un fichier disparu passe en `statut='absent'` — **jamais supprimé** ;
  - **garde-fou** : un scan qui ne renvoie rien alors que l'index est peuplé (partage démonté,
    droits perdus) **abandonne** la synchro au lieu de marquer tout le corpus absent ;
  - récapitulatif du diff affiché sous la source ; 13 tests sur la logique de comparaison.

### Corrigé
- **Un fichier NAS modifié créait une 2ᵉ ligne au même chemin** au lieu d'une nouvelle version :
  `process_file` recevait le chemin du *fichier temporaire* de rapatriement, donc la détection de
  version (« même chemin, contenu différent ») ne pouvait jamais correspondre. Nouveau paramètre
  `chemin_logique` (+ `mtime_fichier`), utilisé par l'indexation **et** la synchro.
- Le `walk` SMB remonte désormais la **date de modification** réelle des fichiers.

---

## [Unreleased]

### Ajouté
- **Rebrand Matothèque** (UI + backend) ; alignement sur le modèle docker AgestiTC
  (VERSION racine, `/api/version` `/healthz` `/api/logs/tail`, Dockerfile non-root,
  CI build+verify tag-driven, Dependabot, audit hebdo, hooks `.claude`).
- **Page Doublons** : détection des fichiers en double sur le volume (scan disque
  taille→SHA256), case à cocher par fichier, **déplacement** vers `DOUBLON-MATOTEQUE/`
  avec confirmation (`GET /api/duplicates`, `POST /api/duplicates/quarantine`).
- `ROADMAP.md` (plan projet) + `DEVELOPMENT.md` + `README-UTILISATEUR.md`.

### Modifié
- Volume documents monté en **lecture-écriture** (requis pour déplacer les doublons ;
  aucun contenu de fichier n'est modifié, déplacement uniquement).

### En cours
- Optimisations performances (index pgvector ivfflat tuning)
- Quasi-doublons (similarité sémantique) — Phase 2 ROADMAP

---

## [v1.3.0] — 2026-04-13

### Couverture de tests complète — tous les routers backend + hooks frontend

**Tests backend — nouveaux fichiers :**
- `test_folders_router.py` : 20 tests
  - `TestListFolders` : liste vide, liste peuplée, structure réponse
  - `TestAddFolder` : ajout dossier existant (mock Path), chemin inexistant (422), doublon (409), nom_affichage personnalisé
  - `TestUpdateFolder` : actif, nom, partiel (autres champs conservés), intervalle min 30s (422), inexistant (404), ID invalide
  - `TestRemoveFolder` : suppression OK, absent après, avec documents associés (`supprimer_documents=true`), inexistant, ID invalide
  - `TestForceScan` : dossier actif (200), dossier inactif (422), inexistant (404), ID invalide
  - `TestBrowseFilesystem` : chemin valide (dossiers + fichiers), inexistant (404), chemin_parent, filtre extensions, taille fichier
- `test_upload_router.py` : 12 tests
  - Acceptés : PDF, DOCX, XLSX — rejetés : TXT, JPG (statut="rejeté" + raison)
  - Multi-fichiers en une requête ; mélange acceptés/rejetés dans une même réponse
  - Job créé en DB après upload (statut="pending", type="extraction")
  - ZIP : accepté via `/upload/zip`, rejeté si non-ZIP (400), paramètre type="zip" dans le job
- `test_extract_router.py` : 18 tests
  - `TestGetJobStatus` : pending/completed/failed, structure réponse, inexistant (404), ID invalide
  - `TestRelancerExtraction` : doc existant → job créé, doc repasse en "pending", fichier source manquant (422), inexistant (404), ID invalide
  - `TestListJobs` : liste vide, filtre statut, filtre type, limite, structure, ordre décroissant (plus récent en premier)

- `test_templates_router.py` : 20 tests
  - `TestListTemplates` : liste vide, templates peuplés, structure réponse (sans champs), ordre alphabétique
  - `TestUploadTemplate` : DOCX accepté (201), PDF accepté (nb_champs=0), extension TXT rejetée (400), champs `{{ }}` détectés, nom_affichage généré (title case), template créé en DB
  - `TestGetTemplate` : template existant avec champs, structure champs (nom/type/description), inexistant (404), ID invalide (400)
  - `TestDeleteTemplate` : suppression OK avec message, absent après, fichier physique supprimé, fichier manquant OK, inexistant (404), ID invalide, double suppression (404)

**Tests frontend — nouveau fichier :**
- `useDropZone.test.ts` : 16 tests
  - Types MIME acceptés : PDF, DOCX, XLSX, PPTX+PPSX, ZIP, ODT/ODS/ODP
  - `multiple: true` transmis à react-dropzone
  - `onDrop` délègue à `uploadFiles` du store ; ne l'appelle pas si liste vide
  - Transmet tous les fichiers d'un dépôt multi-fichiers
  - `noClick` : false par défaut, true/false transmis correctement
  - Valeur retournée : `getRootProps`, `getInputProps`, `isDragActive`, `open`

---

## [v1.2.0] — 2026-04-13

### Couverture de tests étendue + hook useSearch mis à jour

**`useSearch.ts` :**
- Expose désormais `hasMore`, `currentOffset`, `loadingMore`, `loadMore` (pagination GED)

**Tests backend nouveaux :**
- `test_documents_router.py` : 22 tests
  - `TestListDocuments` : liste vide, filtres statut/extension/nom, pagination, structure réponse
  - `TestDocumentStats` : base vide, agrégation taille + total, endpoint avant `/{id}` (régression)
  - `TestGetDocument` : doc existant, avec/sans métadonnées, inexistant, ID invalide
  - `TestGetDocumentText` : texte extrait, texte vide (null → ""), doc inexistant
  - `TestPatchMetadata` : tags, catégorie, résumé, sans meta (404), champs non fournis conservés
  - `TestGetVersions` : sans versions, avec versions (ordre décroissant), doc inexistant
  - `TestDeleteDocument` : suppression OK, absent après suppression, inexistant (404), ID invalide
- `test_prompts_router.py` : 17 tests
  - `TestListPrompts` : liste + structure réponse
  - `TestCreatePrompt` : création 201, nom vide (422), prompt_text vide (422), champs optionnels, ID UUID
  - `TestUpdatePrompt` : modification nom, modification partielle (autres champs conservés), inexistant (404), ID invalide
  - `TestDeletePrompt` : suppression OK, absent après suppression, inexistant (404), ID invalide, double suppression (404)

**Tests frontend hooks :**
- `useDocuments.test.ts` : 18 tests — expose documents/total/page/loading/error, selectedCount dérivé, toutes les actions (toggleSelect/selectAll/deselectAll/isSelected/selectDocument/deselectDocument)
- `useSearch.test.ts` : 18 tests — expose query/results/total/loading/error + `hasMore/currentOffset/loadingMore`, toutes les actions + search/loadMore guards

---

## [v1.1.0] — 2026-04-13

### Tests + Onglet texte extrait + Pagination affinée

**gedStore — tests de pagination :**
- `gedStore.test.ts` entièrement reécrit : 20 tests couvrant setters, search(), loadMore(), loadTags/loadCategories
- Mock de base `BASE_SEARCH_RESPONSE` avec `has_more/offset/limit` requis par le nouveau type
- `RESET_STATE` commun (inclut `hasMore/currentOffset/loadingMore`) pour isolation des tests
- `loadMore()` : 6 nouveaux tests (accumulation, offset passé à l'API, guards hasMore/query/loadingMore, reset en erreur)

**DocumentCard — onglet "Texte extrait" :**
- Ajout système d'onglets "Métadonnées" | "Texte extrait" avec indicateur actif (bordure bleue)
- Chargement paresseux du texte : `GET /documents/{id}/text` appelé uniquement à l'activation de l'onglet
- Bouton "Copier" avec feedback "Copié !" (2 secondes) via `navigator.clipboard`
- Compteur de caractères affiché dans la toolbar de l'onglet texte
- Reset de l'état texte quand `documentId` change

**Tests backend — search pagination :**
- `test_search_pagination.py` : 9 tests
  - Champs `has_more/offset/limit` présents dans toute réponse
  - `has_more=false` si résultats < limit
  - `has_more=true` si résultats > limit
  - Décalage correct entre page 1 (offset=0) et page 2 (offset=20) — IDs non-chevauchants
  - Offset négatif rejeté (422)
  - Offset par défaut = 0
  - Total stable entre pages
  - Filtre catégorie appliqué avant pagination (15 rapports sur 25 docs = total=15)

---

## [v1.0.0] — 2026-04-13

### Production-ready : Outillage + Pagination GED + Tests generate

**Makefile :**
- `make help` : liste toutes les cibles avec documentation inline
- `make up / down / logs / build / restart` : cycle de vie Docker
- `make test / test-backend / test-frontend / test-e2e / test-e2e-mocked` : tous les tests
- `make migrate / migrate-create / migrate-history / migrate-downgrade` : gestion Alembic
- `make dev-backend / dev-frontend / install / install-playwright` : développement local
- `make lint / lint-backend / lint-frontend / format / typecheck` : qualité de code
- `make health` : vérification état Tika + Ollama + backend en une commande
- `make clean / clean-docker / reset` : nettoyage environnement

**Pagination GED (backend + frontend) :**
- `GET /search` : ajout paramètre `offset` (ge=0), retourne `has_more`, `offset`, `limit` dans la réponse
- `searchApi.search()` : paramètre `offset` ajouté dans le type TypeScript
- `gedStore` : ajout `hasMore`, `currentOffset`, `loadingMore`, action `loadMore()` (accumulation des résultats)
- `GEDPage` : bouton "Charger plus de résultats" (visible si `hasMore`), spinner pendant `loadingMore`, message "Tous les N résultats" quand complet

**Tests backend — generate router :**
- `test_generate_router.py` : 14 tests
  - `TestListModels` : retour modèles Ollama, fallback si indisponible, format `{name}`
  - `TestGenerateReport` : document_ids vide (400), UUID invalide (400), document inexistant (404), prompt vide (422), rapport avec doc existant (200 + job_id + stream_url), modèle par défaut
  - `TestGenerationStatus` : job inexistant (404), ID invalide (400), statut après création
  - `TestConstruireContexte` : contexte simple, doc sans texte ignoré, troncature marquée, plusieurs documents

**Corrections E2E :**
- `mockModelsAPI` : route corrigée de `**/api/tags` → `**/api/generate/models` (proxy backend, pas Ollama direct)

---

## [v0.5.0] — 2026-04-13

### Migrations Alembic + Tests E2E Playwright

**Migrations Alembic (production-ready) :**
- `alembic.ini` : configuration Alembic avec async, template de nommage daté
- `alembic/env.py` : env async compatible asyncpg, lit `DATABASE_URL` depuis l'environnement
- `alembic/script.py.mako` : template de migration avec type hints
- `alembic/versions/20260413_0001_initial_schema.py` : migration initiale complète
  - Extensions : `vector`, `pg_trgm`
  - Tables : `documents`, `metadonnees_ia`, `embeddings` (colonne `vector(4096)`), `versions`, `templates`, `prompts_presets`, `jobs`, `dossiers_surveilles`
  - Index : trgm pour nom, GIN pour full-text, IVFFlat pour embeddings, GIN pour tags

**Tests E2E Playwright :**
- `playwright.config.ts` : config Chromium, retries CI, webServer Vite auto, reporters HTML
- `package.json` : scripts `test:e2e` et `test:e2e:ui`, dépendance `@playwright/test`

**Tests E2E sans backend (mocked) :**
- `e2e/fixtures.ts` : données mock, helpers `mockDocumentsAPI`, `mockSearchAPI`, `mockFoldersAPI`, `mockTagsAndCategoriesAPI`, `mockModelsAPI`, `mockHealthAPI` + fixture `mockedPage`
- `e2e/mocked/reports-mocked.spec.ts` : documents dans la liste, sélection + compteur, activation bouton générer, tout sélectionner/désélectionner
- `e2e/mocked/ged-mocked.spec.ts` : catégories/tags sidebar, résultats de recherche, score, panneau latéral, effacer, filtre par tag

**Tests E2E avec backend réel :**
- `e2e/navigation.spec.ts` : page par défaut, sidebar, navigation entre pages, layout de base
- `e2e/reports.spec.ts` : prompt editor, modes de sortie (rapport/template/classement), validation formulaire
- `e2e/ged.spec.ts` : barre de recherche, modes, état vide, drag & drop
- `e2e/upload.spec.ts` : zone dropzone, types de fichiers, retour API upload

**Autres :**
- `requirements.txt` : ajout `aiosqlite==0.20.0` pour les tests SQLite async

---

## [v0.4.0] — 2026-04-13

### Phase 4 — Polish : Tests + Templates + n8n

**Tests backend (pytest) :**
- `conftest.py` : fixtures SQLite en mémoire, mocks Tika/Ollama/EmbeddingService, client HTTP de test
- `test_chunker.py` : 9 tests unitaires pour `chunk_text()` (vide, taille, overlap, couverture)
- `test_hash_utils.py` : 6 tests pour `compute_sha256()` (cohérence, format, hash connu, 5 MB)
- `test_extraction.py` : tests `_extraire_json` + 7 tests intégration `ExtractionService` (déduplication, erreurs Tika/Ollama, création MetadonneeIA)
- `test_export_router.py` : endpoints DOCX/PDF + `_nom_export` (sanitisation, troncature, horodatage)
- `test_search_service.py` : pondération fusion 40/60, union IDs, fallback embedding
- `pytest.ini` : `asyncio_mode = auto`, `testpaths = tests`

**Tests frontend (vitest) :**
- `__tests__/setup.ts` : stub `EventSource`, `crypto.randomUUID`, `import.meta.env`
- `stores/documentStore.test.ts` : 13 tests (sélection, fetch, delete, upload jobs)
- `stores/reportStore.test.ts` : 12 tests (setters, streaming, historique, erreurs)
- `stores/gedStore.test.ts` : 13 tests (recherche, filtres, tags, catégories)
- `hooks/useReport.test.ts` : logique `canGenerate` + `generate()` avec selectedIds
- `utils/typeUtils.test.ts` : 16 tests (statuts, poids fusion, pagination, sanitisation, formatTaille)
- `vite.config.ts` : configuration vitest (globals, jsdom, setupFiles, coverage)

**Services backend complétés :**
- `TemplateFiller` : detect_fields → prompt LLM → parse JSON → docxtpl.render → export DOCX
- `FolderWatcher` : polling async, mtime comparison, fichiers cachés filtrés
- `SearchService` : `_fusionner()` 40/60, recherche sémantique avec fallback, `_charger_resultats()`
- `GEDService` : `get_documents()`, `detect_duplicate()`, `get_stats()`
- `ExportService` : CSS complet weasyprint PDF, parser ligne par ligne python-docx DOCX
- `ReportGenerator` : `generate_stream()`, `build_context()`, `_charger_textes()`
- `main.py` : seed prompts idempotent depuis `scripts/seed-prompts.json` au startup

**Workflows n8n :**
- `folder-watcher.json` : ScheduleTrigger (5 min) → GET /api/folders → POST /api/folders/{id}/scan
- `indexer.json` : Cron (2h) → GET documents extracted/error → POST /api/extract/{id} → log
- `report-pipeline.json` : Webhook POST → validate → POST /api/generate/report → respondToWebhook

---

## [v0.3.0] — 2026-04-13

### Phase 3 — GED avancée

**Composants GED :**
- `DocumentCard` : fiche complète (métadonnées, résumé éditable, entités, tags, versions, actions)
- `TagManager` : tags éditables inline (ajout/suppression, `PATCH /api/documents/{id}/metadata`)
- `VersionHistory` : historique des versions avec diff résumé par IA
- `SearchBar` : toggle type (Hybride/Texte/Sémantique), loading state, submit/clear
- `CategoryBrowser` : filtre actif avec ✕, click → setFilters + search()

**Composants reports complétés :**
- `PromptPresets` : dropdown groupé par catégorie, overlay + outside click
- `GenerateButton` : lecture selectedIds + prompt + isGenerating, Loader2 animate-spin
- `OutputMode` : sélecteur 3 modes (rapport libre, remplir template, classement)
- `TemplateUpload` : upload template DOCX + détection champs {{ }} via API

**Composants fichiers complétés :**
- `FileCard` : dot statut coloré, toggle CheckSquare/Square, hover actions (relance/suppression)
- `FolderSelector` : navigation arborescence filesystem via API browse, sélection dossier

**Composants common complétés :**
- `ErrorBoundary` : getDerivedStateFromError, retry button, componentDidCatch

**Hooks :**
- `useDocuments` : wrapper documentStore + `selectedCount`
- `useReport` : wrapper reportStore + `canGenerate` + `generate()`
- `useSearch` : wrapper gedStore
- `useDropZone` : react-dropzone + uploadFiles, 9 types MIME acceptés

**Pages mises à jour :**
- `ReportsPage` : OutputMode selector, TemplateUpload conditionnel, GenerateButton, badge sélection
- `GEDPage` : panneau latéral DocumentCard (w-80, wired avec selectedDocId)

**Backend :**
- Router `search.py` : correction GROUP BY sémantique, endpoint `PATCH /api/documents/{id}/metadata`

---

## [v0.2.0] — 2026-04-13

### Backend — Implémentation complète Phase 1 + 2

**Pipeline d'extraction :**
- `ExtractionService.process_file()` : hash SHA256 → dédup → Tika → enrichissement IA (Ollama) → embeddings pgvector
- `ExtractionService.process_zip()` : extraction de chaque fichier ZIP via Tika `/rmeta`
- `EmbeddingService.embed_document()` : chunking → embed par chunk + fallback modèle
- Prompt d'enrichissement IA → JSON parsé robustement (gère ```json```, texte brut, extraction regex)

**Routers FastAPI implémentés :**
- `/api/upload` — multipart + background tasks + polling jobs
- `/api/extract` — status jobs, relance
- `/api/documents` — CRUD + pagination + filtres (statut, extension, source, nom)
- `/api/generate` — génération rapport + SSE streaming temps réel
- `/api/search` — recherche hybride (PostgreSQL full-text 40% + pgvector cosine 60%)
- `/api/export` — Markdown → PDF (weasyprint) + DOCX (python-docx)
- `/api/folders` — CRUD dossiers surveillés + scan en background + browse filesystem
- `/api/prompts` — CRUD prompts pré-enregistrés
- `/api/templates` — upload DOCX + détection champs `{{ champ }}`
- `main.py` — startup : init DB + health check Tika/Ollama (non bloquant)

### Frontend — Interface complète Phase 2

**Couche données :**
- `api/index.ts` : fonctions typées pour tous les endpoints backend
- `documentStore` : liste, sélection multi, upload + polling jobs, delete, relance
- `reportStore` : prompt, modèle, génération SSE, historique, export
- `gedStore` : recherche hybride, filtres, tags, catégories

**Composants :**
- `Sidebar` : navigation + indicateur version
- `Header` : statut Tika/Ollama (ping toutes les 30s)
- `Toast` : système notifications (success/error/info)
- `DropZone` : drag & drop fichiers/ZIP avec react-dropzone + feedback visuel
- `FileExplorer` : liste documents avec statut coloré, sélection multi, actions
- `PromptEditor` : textarea + dropdown presets + sauvegarde API
- `ModelSelector` : dropdown modèles Ollama chargés dynamiquement
- `ReportPreview` : aperçu Markdown rendu + streaming cursor + export PDF/DOCX

**Pages :**
- `ReportsPage` : layout 3 colonnes (fichiers | config | résultat)
- `GEDPage` : recherche hybride + filtres catégories/tags + grille cartes
- `SettingsPage` : gestion dossiers surveillés + état services + ajout/scan/suppression

---

## [v0.1.0] — 2026-04-10

### Ajouté
- Structure complète du projet (backend, frontend, scripts, documentation)
- Configuration Docker Compose avec volumes mappés sur l'hôte (aucune donnée dans les conteneurs)
- Squelette FastAPI avec tous les modules, routers, services, modèles
- Squelette React + Vite + TailwindCSS avec tous les composants
- Configuration du logging structuré (structlog JSON)
- Schéma PostgreSQL + pgvector (init-db.sql)
- Stubs workflows n8n (folder-watcher, indexer, report-pipeline)
- Documentation initiale (architecture, API, DB, guides)
- .gitignore adapté au projet
- CHANGELOG.md (ce fichier)

### Infrastructure
- PostgreSQL 16 + pgvector : données sur `./data/postgres/` (hôte)
- Uploads : `./storage/uploads/` (hôte)
- Exports : `./storage/exports/` (hôte)
- Templates : `./storage/templates/` (hôte)
- Logs : `./logs/` (hôte)
- Documents surveillés : chemin configurable via `DOCUMENTS_ROOT` dans `.env`

---

## Roadmap versions

| Version | Contenu | Statut |
|---------|---------|--------|
| `v0.1.0` | Scaffold + structure | ✅ |
| `v0.2.0` | Backend complet (Tika + Ollama + DB) + Frontend Phase 2 | ✅ |
| `v0.3.0` | GED avancée (DocumentCard, TagManager, VersionHistory, panneau latéral) | ✅ |
| `v0.4.0` | Polish : tests, services complets, n8n workflows | ✅ |
| `v0.5.0` | Migrations Alembic + tests E2E Playwright | ✅ |
| `v1.0.0` | Makefile + pagination GED + tests generate router | ✅ |
| `v1.1.0` | Onglet texte extrait + tests pagination + gedStore tests | ✅ |
| `v1.2.0` | test_documents_router + test_prompts_router + useDocuments/useSearch tests | ✅ |
