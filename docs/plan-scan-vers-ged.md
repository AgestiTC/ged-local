# Plan — Scanner directement dans la GED (Canon G3570 + Brother ADS-1200)

> **État : étude de faisabilité + plan, rien n'est codé.** Demandé le 11/09/2026.
> Référencé depuis [ROADMAP.md](../ROADMAP.md).
> Question posée : *« Est-il possible de proposer un module dans Matothèque pour scanner
> directement dans la GED ? Scanner et déposer les scans directement dans le bon répertoire,
> avec les bons tags et déjà indexés. »*

---

## 1. Verdict en trois phrases

**Oui, c'est faisable, et 100 % local.** La partie « bon répertoire, bons tags, déjà indexé »
est déjà là aux trois quarts : c'est le pipeline d'ingestion existant (Tika + Tesseract →
catégorie/tags IA → embeddings), auquel il manque seulement une notion de **profil de scan**
(où ranger, quels tags, quel nom). La partie « déclencher le scan depuis Matothèque » dépend
du matériel : le **Canon est en réseau** et se pilote directement depuis le backend (protocole
eSCL, sans pilote) ; le **Brother est USB seulement** et passe donc forcément par le PC qui
l'héberge (soit son bouton physique + un dossier surveillé, soit un partage réseau du scanner).

---

## 2. Le matériel, ce qu'il permet vraiment

| | Canon PIXMA G3570 (MegaTank) | Brother ADS-1200 |
|---|---|---|
| Nature | multifonction jet d'encre grand public | scanner de documents dédié |
| Chargeur (ADF) | **non** — vitre A4 uniquement | **oui**, 20 feuilles, **recto-verso**, ~25 ppm |
| Connexion | **Wi-Fi** (réseau) + USB | **USB 3.0 uniquement** (le modèle Wi-Fi est l'ADS-1250W) |
| Pilotable sans PC ? | **oui** : protocole **eSCL / AirScan** (le « scan » d'AirPrint et Mopria), ou WSD — *à vérifier en 5 min, cf. §8* | **non** : toujours attaché à un ordinateur |
| Bouton physique | « Scan vers ordinateur » : demande le logiciel Canon sur un PC allumé | bouton **Start** : déclenche un profil **Brother iPrint&Scan** (PDF vers un dossier, recto-verso, page blanche ignorée…) |
| Scan vers dossier réseau depuis l'appareil | non (gamme grand public) | non (pas de réseau) |
| Pilotes | Windows (IJ Scan Utility, WIA), Linux (SANE via eSCL) | Windows TWAIN/WIA, Linux SANE (pilote Brother) |
| Son rôle dans Matothèque | la **page isolée**, le livret, la carte, ce qui ne passe pas dans un chargeur | la **liasse** : factures, courrier, contrats, relevés |

**Conséquence de conception** : les deux appareils n'appellent pas la même mécanique. Le Canon
se pilote « en direct » depuis le backend (le conteneur parle HTTP à l'imprimante sur le LAN).
Le Brother, lui, produit des PDF sur le PC ; la question est seulement **comment ces PDF
arrivent dans Matothèque** avec le bon rangement.

---

## 3. Ce qu'on ne fera PAS, et pourquoi

- ❌ **Scanner depuis le navigateur.** Aucun navigateur n'expose TWAIN/WIA ; WebUSB ne parle pas
  aux scanners et les SDK « scan dans la page » sont payants et non locaux. Le scan se déclenche
  depuis l'UI, mais c'est le **backend** qui parle au scanner.
- ❌ **Installer le pilote Brother dans le conteneur backend.** Il faudrait faire traverser l'USB
  au LXC puis à Docker : fragile, et le scanner est physiquement à côté du PC, pas du serveur.
- ❌ **Passer par les apps constructeur cloud** (Canon PRINT, Brother Mobile Connect). Tout reste
  sur le LAN ; l'invariant « 100 % local » du projet tient sans effort : eSCL est du HTTP local.
- ❌ **Réécrire un OCR.** Tika + Tesseract est déjà en place (`ocrStrategy=auto`, 300 dpi,
  `fra+eng`, cf. `storage/tika-config/tika-config.xml`) avec repli vision. Un scan est un PDF
  image comme un autre : il est OCRisé au passage.
- ❌ **Un scan silencieux qui range tout seul sans regard.** Comme pour la réorganisation
  d'arborescence : l'IA propose, l'utilisateur confirme quand le rangement n'est pas décidé à
  l'avance. Déplacer un fichier sur le NAS reste une action journalisée et annulable.

---

## 4. Ce qui existe déjà et qu'on réutilise

| Brique | Où | Ce qu'elle apporte au scan |
|---|---|---|
| Ingestion d'un fichier avec **tag pré-appliqué** | `backend/routers/upload.py` (`folder_tag`) → `services/extraction.py::process_file(folder_tag, chemin_logique, mtime_fichier)` | le scan entre par la même porte que le glisser-déposer ; `chemin_logique` permet de l'enregistrer sous son chemin NAS final |
| OCR Tesseract via Tika + repli vision | `storage/tika-config/tika-config.xml`, `extraction.py::_ocr_fallback` | texte du scan, sans code nouveau |
| Enrichissement IA (catégorie, sous-catégorie, tags, résumé, entités) | `extraction.py` (modèle par défaut `llama3.1`) | tags « métier » automatiques en plus des tags du profil ; base du mode « l'IA propose le rangement » |
| Sources local / SMB, **écriture** SMB | `services/smb_service.py` (`storeFile`, `rename`, `createDirectory`) | déposer le PDF dans le bon dossier du NAS |
| Déplacement physique journalisé + **undo** | `routers/organize.py`, `services/job_handlers.py` (`reorg_apply`, `reorg_undo`) | ranger a posteriori, sans rien perdre |
| Dossiers surveillés + synchronisation des sources | `services/folder_watcher.py`, `routers/sources.py` (`sync`) | la « boîte à scans » alimentée par le bouton du Brother |
| Tâches durables avec progression | `services/job_worker.py` (`@register`) | un scan multi-pages est un job : suivi, reprise, erreur propre |
| Antivirus à l'indexation | `services/clamav_service.py` | s'applique aux scans comme au reste |
| Pattern **connecteur** + section Paramètres | `services/connectors/base.py`, `SettingsPage.tsx` (« Sources de fichiers », « Connecteurs cloud ») | modèle pour une section « Scanners » (déclarer, tester, pastille) |
| Version d'un document (même chemin, contenu différent) | `process_file`, étape 2 | re-scanner une pièce en meilleure qualité crée une version, pas un doublon |

---

## 5. Architecture cible

```
   Canon G3570 (Wi-Fi)                Brother ADS-1200 (USB, sur le PC)
          │ eSCL (HTTP, LAN)                     │
          │                          ┌───────────┴────────────┐
          │                          │ bouton Start           │ NAPS2 « partage de
          │                          │ → iPrint&Scan → PDF    │ scanner » = serveur eSCL
          │                          │ → dossier « Scans/ »   │ sur le PC
          │                          │   (source SMB, sync)   │
          ▼                          ▼                        ▼ eSCL
   ┌──────────────────────────────────────────────────────────────────┐
   │ backend — services/scan_service.py                               │
   │   escl_client (capabilities · ScanJobs · NextDocument)           │
   │   boîte à scans (table `scans`)  ·  profils (table `scan_profils`)│
   └───────────────┬──────────────────────────────────────────────────┘
                   │ PDF + profil (destination, tags, nom)
                   ▼
   écrit à destination (source SMB / locale)  →  process_file(folder_tag=…, chemin_logique=…)
                   ▼
   OCR Tesseract → catégorie/tags/résumé IA → embeddings → GED (déjà là)
```

### Les trois objets nouveaux

**Scanner** — une entrée de configuration, comme une source : `nom`, `type` (`escl` ; plus tard
`hot_folder`), `url` (`http://192.168.42.x:80/eSCL`), capacités lues sur l'appareil (vitre /
chargeur, recto-verso, résolutions, couleur), pastille « joignable », bouton « Tester ».
La découverte mDNS/Bonjour ne traverse pas Docker : **IP saisie à la main**, avec une
**réservation DHCP** conseillée (sinon l'imprimante change d'adresse et le scanner passe rouge).

**Profil de scan** — c'est la réponse à « bon répertoire, bons tags ». Exemples : *Facture*,
*Courrier administratif*, *Santé*, *Assmat / Pajemploi*.

| champ | rôle |
|---|---|
| `nom`, `icone` | ce que l'utilisateur choisit dans la modale |
| `destination` | source (SMB/locale) + sous-dossier, ex. `smb://NAS-MATO/Documents/Factures/{annee}` |
| `tags` | liste pré-appliquée, comme `folder_tag` aujourd'hui (à généraliser en liste) |
| `modele_nom` | `{date}_{profil}_{n}.pdf` ; plus tard `{emetteur}` proposé par l'IA |
| `reglages` | dpi (300 par défaut), couleur / gris, recto-verso, format (PDF), scanner par défaut |
| `classement` | `fixe` (le profil décide) · `ia_confirme` (le scan attend en boîte, l'IA propose un profil à partir du texte OCR, l'utilisateur confirme) |
| `dossier_id` (optionnel) | rattacher automatiquement le scan à un Dossier thématique (ex. « Devenir parent ») |

**Boîte à scans** — chaque scan y passe (`recu → ocr → indexe → range`), avec sa vignette, son
profil, son nom modifiable. Elle sert à corriger avant rangement, à rattraper un scan mal
profilé, et c'est la vue « Scans » de la GED. Un scan « rangé » est un document GED comme un
autre ; la ligne `scans` garde l'origine (scanner, profil, pages, durée).

### API (esquisse)

```
GET/POST/PUT/DELETE  /api/scan/scanners            # CRUD scanners
POST   /api/scan/scanners/{id}/test                 # joignabilité + capacités
GET/POST/PUT/DELETE  /api/scan/profils              # CRUD profils
POST   /api/scan/jobs   {scanner_id, profil_id, reglages?}   # lance un scan → job durable
POST   /api/scan/jobs/{id}/page-suivante            # vitre : page suivante du même document
POST   /api/scan/jobs/{id}/terminer                 # vitre : assembler le PDF et ranger
GET    /api/scan/inbox                              # boîte à scans (statuts, vignettes)
POST   /api/scan/inbox/{id}/ranger  {profil_id?, nom?}   # (re)ranger, confirmer une proposition IA
```

### UI

- **Bouton « Scanner »** dans la GED (à côté du glisser-déposer) et dans la fiche d'un Dossier :
  modale *scanner → profil → réglages* → progression → vignette de la page → sur vitre :
  « Ajouter une page » / « Terminer » → « Rangé dans … avec les tags … ».
- **Paramètres → « Scanners »** : section jumelle de « Sources de fichiers » (liste, test,
  pastille, réglages par défaut) + gestion des profils.
- **Vue « Boîte à scans »** dans la GED : les derniers scans, leur statut, corriger / ranger.
- À vérifier par la route **HTTP** (`http://192.168.42.83:3003`) : aucun `crypto.randomUUID` ni
  `navigator.clipboard` direct — helpers `utils/uuid.ts` et `utils/clipboard.ts` (cf. CLAUDE.md).

---

## 6. Plan par phases

### Phase 0 — Aujourd'hui, zéro code : le dossier « Scans/ » surveillé

Mise en route sans toucher au code, utile dès la première semaine :

1. Créer un partage (ou sous-dossier) **`Scans/`** sur NAS-MATO, le déclarer dans **Paramètres →
   Sources de fichiers** (SMB) avec **synchronisation** activée.
2. **Brother** : dans iPrint&Scan, profil « Scan vers dossier » → `\\NAS-MATO\…\Scans`, PDF,
   300 dpi, recto-verso, **ignorer les pages blanches** ; associer au bouton **Start**.
   Geste : poser la liasse, appuyer, c'est indexé.
3. **Canon** : IJ Scan Utility → même dossier (ou depuis l'écran « Scan vers ordinateur »).

Résultat : chaque scan est **OCRisé, catégorisé, tagué par l'IA, cherchable**. Ce qui manque :
le répertoire final (tout est dans `Scans/`), les tags décidés par l'utilisateur, le nom
propre. Livrable : **`docs/setup-scanners.md`** (guide utilisateur des deux appareils).
Effort : ½ journée.

### Phase 1 — Boîte à scans + profils (le « bon répertoire, bons tags »)

Sans piloter le matériel : tout ce qui arrive dans la boîte est rangé selon un profil.

- Migration : tables `scan_profils`, `scans` (+ `scanners` vide pour la phase 2).
- La source `Scans/` devient une **boîte à scans** : tout PDF qui y arrive crée une ligne
  `scans` et est indexé (comme aujourd'hui) ; le rangement suit.
- **Rangement par profil** : déplacement SMB via le code de `reorg_apply` (journal + undo),
  nom normalisé, tags pré-appliqués (`folder_tag` → liste), `chemin_logique` mis à jour
  (pas de doublon, pas de ré-OCR).
- **Mode `ia_confirme`** : à partir de la catégorie/sous-catégorie déjà calculées, proposer le
  profil ; l'utilisateur confirme dans la vue Scans. Aucun déplacement sans clic.
- UI : vue « Boîte à scans » + gestion des profils dans Paramètres.
- Tests pytest : nommage, choix de destination, proposition IA (sans matériel).

Effort : 2 à 3 jours. **C'est la phase qui apporte le plus** : elle vaut pour les deux
appareils, et pour tout PDF déposé à la main.

### Phase 2 — Piloter le Canon G3570 depuis Matothèque (eSCL)

- `services/escl_client.py` (httpx, XML) : `ScannerCapabilities`, `ScannerStatus`, `POST
  ScanJobs`, `GET NextDocument` en boucle, formats JPEG/PDF. Aucun pilote, aucune dépendance
  lourde ; le protocole est le même que celui de `sane-airscan`.
- Job durable `scan_escl` : progression par page, timeout par page (un scan 300 dpi couleur
  peut prendre 30 à 60 s), erreurs lisibles (« capot ouvert », « occupé »).
- **Vitre = une page par passage** : le backend assemble le PDF multi-pages (img2pdf/pikepdf)
  jusqu'à « Terminer » ; la modale enchaîne « Ajouter une page ».
- Paramètres → Scanners : déclarer l'IP, tester, lire les capacités.
- Tests : faux serveur eSCL (réponses XML enregistrées) → aucun matériel en CI.

Effort : 2 à 3 jours. Prérequis : §8, points 1 et 2.

### Phase 3 — Le Brother ADS-1200, trois options (garder A + B)

| Option | Principe | Coût | Limite |
|---|---|---|---|
| **A. NAPS2 « partage de scanner »** *(recommandée)* | NAPS2 (libre, Windows) tourne sur le PC hôte et **publie le Brother en eSCL** sur le LAN → Matothèque le pilote **avec le même client que le Canon** : zéro code backend, le Brother apparaît comme un scanner de plus, on lance une liasse depuis l'UI | ~1 jour (config + tests) | le PC doit être allumé |
| **B. Bouton physique → boîte à scans** *(à garder aussi)* | c'est la Phase 0/1 : poser la liasse, appuyer sur Start, le PDF tombe dans `Scans/`, la boîte range | ½ jour | pas de choix du profil au moment du scan (mode `ia_confirme` ou rangement après coup) |
| C. **Brother branché sur le Proxmox** (USB/IP ou USB direct → LXC x86 → pilote Brother → AirSane) | rend le Brother indépendant du PC, exposé en eSCL, piloté par le même client que le Canon — **détail ci-dessous, retenu pour plus tard** | 1 à 2 jours + boîtier USB/IP (25 à 250 €) | matériel supplémentaire, pilote Brother à valider en USB/IP |

**Décision du 11/09/2026 : on garde la phase 2 (eSCL) comme voie principale dans un premier temps**, avec
3B pour le Brother. Le branchement du Brother sur le Proxmox (option C) est **documenté ici pour plus
tard**, pas planifié.

#### Plus tard : brancher le Brother sur le Proxmox (option C, détaillée)

Deux contraintes fixent le montage :

- **Le pilote Linux Brother (`brscan4` / `brscan5`) n'existe qu'en x86.** Un Raspberry Pi ne peut
  pas héberger le scanner lui-même ; le **LXC Proxmox est en x86**, c'est lui le bon hôte.
- **Le scanner n'est pas à côté du serveur.** Un câble USB 3 se limite à ~3 m ; il faut soit
  transporter l'USB sur le réseau (USB/IP), soit rapprocher le scanner du Proxmox.

```
   Brother ADS-1200 ──USB──▶ serveur USB/IP près du scanner        (ou : USB direct sur l'hôte pve)
                             (Raspberry Pi Zero 2 W + usbipd,
                              VirtualHere, ou boîtier Silex DS-600/700)
                                        │ LAN (USB/IP)
                                        ▼
                    LXC x86 dédié « scanners » sur Proxmox
                      usbip attach  →  pilote Brother SANE  →  AirSane (serveur eSCL)
                                        │ eSCL
                                        ▼
                    Matothèque (client eSCL de la phase 2, zéro code en plus)
```

| Élément | Rôle | Coût |
|---|---|---|
| Serveur USB/IP près du scanner | expose l'ADS-1200 sur le LAN | 25 € (Pi Zero 2 W) à ~250 € (Silex) |
| LXC dédié x86 (`usbip` client + `brscan` + AirSane) | attache le scanner, le publie en eSCL ; **pas dans le conteneur backend** | 0 € |
| Variante sans boîtier : USB direct sur l'hôte pve + passage USB au LXC (`lxc.cgroup2.devices.allow` / `lxc.mount.entry`) | même chose, si le scanner peut vivre près du serveur | 0 € |
| `brscan-skey` dans le LXC | capte le **bouton Start** → dépose dans la boîte à scans (3B sans PC) | 0 € |

Résultat : plus de PC allumé, le Brother devient un scanner réseau comme le Canon, l'ADF
recto-verso se pilote depuis l'UI.

**Checklist avant d'acheter / de monter :**

1. ❌ **Pas un « serveur d'impression »** (type PM1115U2 : LPR/RAW/IPP, impression seule, « no
   scan »). La fiche doit dire **USB over IP / USB device server / USB redirector**.
2. **Alimentation** : l'ADS-1200 sur son adaptateur secteur, pas sur le bus du boîtier.
3. **Pilote Brother pour ADS-1200** sur la page support Linux de Brother (`brscan4` ou
   `brscan5`, paquet amd64), puis test `scanimage -L` dans le LXC **à travers USB/IP** avant de
   figer le montage (les scanners passent bien en USB/IP — transferts bulk — mais ça se vérifie).
4. **Débit** : 25 ppm en 300 dpi gris passe sur un Pi Zero 2 W en Wi-Fi ; un Pi filaire ou un
   Silex est plus confortable.
5. **Alternative sans bricolage** si le scanner est un jour remplacé : l'**ADS-1250W** (même
   appareil, Wi-Fi + eSCL natif) s'ajoute comme le Canon, sans boîtier ni pilote.

Pour une liasse, **B est souvent le geste le plus naturel** (on ne va pas chercher une UI pour
appuyer sur un bouton) ; A sert quand on veut choisir le profil avant, ou scanner sans se lever.

### Phase 4 — Confort (non planifié, à cadrer plus tard)

- **Séparation de liasse** : page blanche ou feuille séparatrice QR → un PDF par pièce.
- **Nommage par l'IA** : `{date}_{emetteur}_{type}` lus dans le texte OCR, proposés, jamais imposés.
- **Doublon de re-scan** : deux scans de la même pièce n'ont pas le même SHA256 ; il faudra une
  similarité de texte (le `pertinence.py` existant peut servir) pour dire « déjà là ».
- **Scan dégradé** : contrôle croisé OCR + vision (`qwen2.5vl:7b`), cf. plan qualité OCR.
- **Scan → contributeurs** : une facture d'assmat scannée dans le profil *Pajemploi* alimente le
  contributeur `emploi-domicile` de l'aide à la déclaration.
- Redressement / rotation : laisser au pilote (NAPS2 et iPrint&Scan le font très bien).

---

## 7. Effort et ordre recommandé

| Phase | Effort | Dépend de | Valeur |
|---|---|---|---|
| 0 — dossier surveillé | ½ j | rien | indexé + OCR + tags IA dès maintenant |
| 1 — boîte + profils | 2-3 j | rien (aucun matériel) | **le cœur de la demande** : bon répertoire, bons tags |
| 2 — Canon eSCL | 2-3 j | §8 (1)(2) | scan d'une page depuis l'UI, sans PC |
| 3A — Brother via NAPS2 | 1 j | phase 2, PC hôte | liasse depuis l'UI |
| 3B — Brother bouton | ½ j | phase 1 | liasse d'un geste |

Ordre retenu le 11/09/2026 : **0 → 1 → 2 → 3B → 3A**, l'option C (Brother sur le Proxmox)
documentée pour plus tard. Les phases 0 et 1 rendent déjà le service demandé ; la phase 2 est la
voie principale (eSCL) et sert ensuite telle quelle au Brother, quel que soit son hôte.

---

## 8. À vérifier AVANT de coder la phase 2 (15 minutes, avec le matériel)

1. **Le Canon parle-t-il eSCL ?** Depuis un PC du LAN (ports 80, 443 ou 8080 selon firmware) :
   ```
   curl -s http://<ip-du-canon>/eSCL/ScannerCapabilities
   ```
   Un XML `<scan:ScannerCapabilities>` = feu vert. Sinon : WSD (plus lourd) ou le pilote Canon
   sur PC, et la phase 2 devient « Canon via NAPS2 partagé », comme le Brother.
2. **Le conteneur backend joint-il l'imprimante ?** Depuis le LXC :
   ```
   docker compose -f /opt/docflow/docker-compose.yml exec -T backend \
     python -c "import httpx;print(httpx.get('http://<ip-du-canon>/eSCL/ScannerCapabilities',timeout=5).status_code)"
   ```
3. **Sur vitre, quel format rend le Canon ?** (JPEG par page attendu ; PDF direct = tant mieux.)
4. **NAPS2 partage bien le Brother en eSCL** (menu *Partager*), et le pilote Brother est vu
   (TWAIN ou WIA) sur le PC hôte.
5. **Où ranger physiquement** : quel partage NAS-MATO, quelle arborescence de départ pour les
   profils (Factures / Administratif / Santé / Enfant…). À décider avec l'utilisateur ; les
   profils sont modifiables ensuite.

---

## 9. Risques et limites, dits avant

- **Canon sans chargeur** : une page par passage, on ne scanne pas une liasse dessus.
- **Brother = PC allumé**, tant que l'option C (Brother sur le Proxmox, §6) n'est pas montée.
- **Adresse IP** : pas de découverte automatique depuis Docker ; réservation DHCP obligatoire
  pour ne pas perdre le scanner.
- **Variantes eSCL** : chaque constructeur a ses écarts (formats, `InputSource`, `ColorMode`) ;
  le client doit lire les capacités plutôt que supposer.
- **Taille des PDF** : 300 dpi couleur = lourd ; les profils « texte » passent en gris.
- **Re-scans** : le SHA256 ne repère pas un doublon de scan (Phase 4).
- **Rien de nouveau côté sortie Internet** : eSCL, SMB et NAPS2 sont sur le LAN ; seule
  l'installation de NAPS2 / iPrint&Scan est un téléchargement, fait par l'utilisateur.
