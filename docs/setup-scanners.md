# Scanner vers la GED — mise en route

Comment brancher un **Canon PIXMA G3570** (multifonction Wi-Fi) et un **Brother ADS-1200**
(scanner à chargeur, USB) sur Matothèque, pour que chaque scan arrive **OCRisé, tagué et
rangé au bon endroit**. Conception détaillée : [plan-scan-vers-ged.md](plan-scan-vers-ged.md).

Deux chemins coexistent, et on peut utiliser les deux :

| | Depuis Matothèque (page **Scans → Scanner**) | Depuis l'appareil (bouton Start, logiciel constructeur) |
|---|---|---|
| Comment | Matothèque pilote le scanner en **eSCL** sur le LAN | l'appareil dépose un PDF dans le **dossier de la boîte** |
| Pour qui | le Canon (Wi-Fi) ; le Brother partagé par NAPS2 | le Brother (bouton Start), le Canon (IJ Scan Utility) |
| Profil choisi | **avant** le scan, dans la modale | **après**, dans la page Scans (ou proposé par l'IA) |

---

## 1. La boîte à scans (5 minutes, valable pour tout)

1. Sur le NAS, créer un dossier **`Scans/`** dans un partage déjà déclaré (ex.
   `\\NAS-MATO\Documents\Scans`).
2. **Paramètres → Sources & indexation → Sources de fichiers** : vérifier que ce partage est
   indexé et que la **synchronisation automatique** est activée (toutes les heures suffit).
3. **Paramètres → Scanners & profils de scan → Boîte à scans** : saisir
   `smb://NAS-MATO/Documents/Scans` et Enregistrer.

Dès lors, tout PDF déposé dans `Scans/` est OCRisé (Tesseract via Tika), catégorisé et tagué
par l'IA, cherchable dans la GED, **et listé dans la page Scans** pour être rangé.

## 2. Les profils (« bon répertoire, bons tags »)

**Paramètres → Scanners & profils de scan → Profils**. Un profil par famille de papiers :

| Profil | Destination | Tags | Mots-clés (reconnaissance) | Réglages |
|---|---|---|---|---|
| 🧾 Facture | `smb://NAS-MATO/Documents/Factures/{annee}` | facture | facture, montant, TTC | chargeur, gris, 300 dpi |
| 🏛️ Administratif | `smb://NAS-MATO/Documents/Administratif/{annee}` | administratif | impôts, caf, urssaf, attestation | chargeur, gris, 300 dpi |
| 🩺 Santé | `smb://NAS-MATO/Documents/Sante` | santé | ordonnance, médecin, mutuelle | vitre, couleur, 300 dpi |
| 👶 Assmat / Pajemploi | `smb://NAS-MATO/Documents/Enfant/Pajemploi/{annee}` | pajemploi, assmat | pajemploi, assistante maternelle, garde | chargeur, gris, 300 dpi |

- **Modèle de nom** : `{date}_{profil}` donne `2026-09-11_facture.pdf` ; `{nom}` reprend le
  nom d'origine, `{annee}`/`{mois}` sont disponibles. Deux scans le même jour → `_(1)`.
- **Rangé aussitôt indexé** (`fixe`) : dès l'OCR terminé, le fichier part à destination.
- **Attend ma confirmation** (`ia_confirme`) : le scan reste dans la boîte ; la page Scans
  affiche le profil **proposé** d'après ce que l'IA a lu (mots-clés), on confirme d'un clic.
- Les tags du profil **s'ajoutent** à ceux de l'IA, ils ne les remplacent pas.
- Une destination locale doit être sous la racine documents du conteneur ; en pratique on
  vise le NAS en `smb://hote/partage/…` (l'hôte doit être une source SMB déclarée : c'est
  là que Matothèque prend les identifiants).

## 3. Canon G3570 — piloté depuis Matothèque (eSCL)

1. **Réserver son adresse IP** dans le DHCP de la box/routeur (sinon le scanner « passe rouge »
   au prochain bail).
2. Vérifier qu'il parle eSCL, depuis un PC du réseau :
   ```
   curl -s http://<ip-du-canon>/eSCL/ScannerCapabilities
   ```
   Un XML `<scan:ScannerCapabilities>` = c'est bon. (Sinon essayer `:8080` ; en dernier
   recours le Canon se partage par NAPS2 comme le Brother, §4.)
3. **Paramètres → Scanners → Ajouter** : nom « Canon », adresse `<ip-du-canon>` → **Tester**.
   La fiche affiche le modèle, « vitre », les résolutions.
4. **Page Scans → Scanner** : choisir le profil, la source *Vitre*, lancer. Chaque passage
   rend une page : **Ajouter une page** pour la suivante, **Terminer** pour assembler le PDF,
   lancer l'OCR et ranger.

Le Canon n'a pas de chargeur : c'est l'appareil de la page isolée, du livret, de la carte.

### Depuis l'appareil (sans Matothèque ouverte)

IJ Scan Utility (PC) → « Enregistrer dans » le dossier `Scans/` du NAS, PDF, 300 dpi. Le
scan arrive dans la boîte, on le range depuis la page Scans.

## 4. Brother ADS-1200 — USB, donc via le PC

L'ADS-1200 n'a **ni Wi-Fi ni Ethernet** : il est branché à un PC. Deux façons, à garder toutes
les deux.

### 4a. Bouton Start → boîte à scans (le plus simple pour une liasse)

Brother **iPrint&Scan** (Windows) → *Scan vers dossier* : dossier `\\NAS-MATO\Documents\Scans`,
PDF, 300 dpi, **recto-verso**, **ignorer les pages blanches**, associer au bouton **Start**.
Geste : poser la liasse, appuyer, c'est dans la boîte.

### 4b. NAPS2 partage le Brother → piloté depuis Matothèque

1. Installer **NAPS2** (libre) sur le PC où le Brother est branché ; vérifier qu'il voit le
   scanner (pilote Brother TWAIN/WIA).
2. NAPS2 → **Partager** le scanner (NAPS2 publie alors un serveur eSCL sur le LAN). Noter
   l'adresse et le port affichés.
3. **Paramètres → Scanners → Ajouter** : nom « Brother », adresse `http://<pc>:<port>` → Tester
   (la fiche doit dire « chargeur recto-verso »).
4. Page Scans → Scanner → source *Chargeur* : la liasse part d'un coup.

Limite : le PC doit être allumé. Pour s'en passer un jour, le plan documente le
branchement du Brother **sur le Proxmox** (USB/IP → LXC → AirSane), cf. plan §6, option C.

## 5. Dépannage

- **« Scanner injoignable »** : IP changée (réservation DHCP), appareil en veille profonde,
  ou le conteneur backend ne joint pas ce sous-réseau. Test depuis le LXC :
  ```
  docker compose -f /opt/docflow/docker-compose.yml exec -T backend \
    python -c "import httpx;print(httpx.get('http://<ip>/eSCL/ScannerCapabilities',timeout=5).status_code)"
  ```
- **« Le scanner n'est pas prêt »** : capot ouvert, chargeur vide, ou un travail en cours
  depuis un autre appareil (le panneau de l'imprimante).
- **« Réglages refusés »** : re-Tester le scanner pour rafraîchir ses capacités ; choisir une
  résolution qu'il annonce.
- **Indexé mais non rangé** : la destination n'est pas joignable (hôte SMB non déclaré en
  source, dossier en lecture seule). Le scan reste dans la boîte avec le message ; corriger
  le profil puis « Ranger ».
- **Une pièce scannée deux fois** n'est pas détectée comme doublon (deux scans n'ont jamais
  le même contenu binaire) : c'est prévu en phase 4 du plan.
