# L'agent de poste (module Rangement)

Un PC de la maison ne se lit pas depuis le serveur : c'est lui qui envoie l'inventaire des
dossiers qu'on lui confie, et qui calcule les empreintes de ses fichiers pour retrouver les
**copies** entre le PC et le NAS. Il ne déplace, ne renomme ni ne supprime **rien**.

- **Code** : `agent/` (Go, un exe unique, rien d'autre à installer sur le PC). Rapatrié de
  l'appli « rangement » à l'étape 5 du plan [rangement + mails](plan-integration-rangement-mails.md).
- **Identité Windows** : service `RangementAgent`, dossiers `Program Files\Rangement Agent` et
  `ProgramData\Rangement` (gardés tels quels : un poste déjà équipé se met à jour sans rien perdre).
- **Version** : `agent/VERSION` (composant à part de Matothèque).
- **Jeton** : un jeton de `jetons_api`, de **portée `agent`** (`mato_…`), un par poste. Il
  n'atteint que `/api/agent/*` ; aucune session n'y entre, pas même celle d'un administrateur.

## 1. Mettre un PC en service

1. **Créer le poste** (administrateur connecté) — en attendant l'écran *Postes* (étape 7), depuis
   la console du navigateur :

   ```js
   fetch('/api/inventaire/postes',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({nom:'PC-GAME'})}).then(r=>r.json()).then(console.log)
   ```

   La réponse contient `jeton_clair` : **il n'est montré qu'une fois**. Le ranger dans Bitwarden.
2. **Construire l'agent** sur un poste qui a Go : `.\agent\construire.ps1` (tests, exe, SHA-256,
   archive dans `agent\dist\`).
3. Sur le PC, dans un PowerShell **administrateur** :

   ```powershell
   .\installer-agent.ps1 -Serveur http://192.168.42.83:3003 -Jeton mato_… -Racines "C:\Users","D:\"
   ```

   `-Racines` est la **liste blanche locale** : l'agent refusera tout dossier qui n'y est pas,
   même si le serveur le demande. Le serveur est joint par le frontend (nginx relaie `/api/`).
4. **Confier un dossier** au poste :

   ```js
   fetch('/api/inventaire/postes/1/emplacements',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({libelle:'Documents',racine:'C:\\Users\\Thomas'})}).then(r=>r.json()).then(console.log)
   ```

   L'inventaire arrive au contact suivant (15 min au plus).

**Jeton perdu, PC cédé** : `POST /api/inventaire/postes/{id}/jeton` (nouveau jeton, l'ancien est
révoqué aussitôt) ou `PATCH /api/inventaire/postes/{id}` `{"actif": false}`. Un jeton de poste
vaut **2 ans** : échu, l'agent est refusé (401) jusqu'au renouvellement.

> Le certificat TLS est **toujours vérifié** par l'agent : en LAN sans certificat, utiliser une
> adresse `http://`.

## 2. Ce que fait l'agent, à chaque contact

| Étape | Appel | Ce qui circule |
|---|---|---|
| Configuration | `GET /api/agent/config` | dossiers confiés, « inventaire dû ? », exclusions, intervalle |
| Inventaire (si dû) | `POST /api/agent/envois` → `…/lots` (×n) → `…/fin` | listes de dossiers : nom, dossier ?, taille, date — **jamais de contenu** |
| Empreintes | `GET /api/agent/empreintes` → `POST /api/agent/empreintes` | SHA-256 des fichiers demandés, dans la **limite du jour** |

Toutes les requêtes portent `Authorization: Bearer mato_…` et `X-Agent-Version`. La fin d'un
envoi enfile une tâche du worker (`inventaire_envoi`, classe « fond ») : c'est elle qui compare
l'envoi à l'inventaire connu.

### Lots

```json
{"dossiers": [
  {"chemin": "", "enfants": [["Docs", true, 0, 1712345678.5], ["photo.jpg", false, 2097152, 1712345678.5]]},
  {"chemin": "Docs", "illisible": true},
  {"chemin": "Photos", "enfants": [], "illisibles": ["verrouillé.psd"]}
]}
```

`chemin` est relatif à la racine confiée, séparateur `/`. Corps compressé (`Content-Encoding:
gzip`) : **10 Mo au plus reçus** (lus en flux, refus avant chargement), au plus 2 000 dossiers et
200 000 éléments par lot, **64 Mo une fois décompressé** (une bombe gzip est refusée en 413). Un
grand dossier peut arriver en plusieurs morceaux : le serveur les rassemble.

### Ce que le serveur revérifie (tout ce qui vient d'un poste est une donnée extérieure)

- chaque nom (`..`, `/`, `\`, caractère nul → écarté) et chaque type (refus du lot entier) ;
- les **exclusions** de l'inventaire (l'agent n'élague qu'un **sous-ensemble** de celles du
  serveur : élaguer plus ferait passer des fichiers pour disparus) ;
- un poste ne voit et ne touche que **ses** emplacements (404 sinon) ;
- une empreinte n'est retenue que pour un fichier de ce poste, à la taille et à la date que
  l'inventaire connaît.

### Prudence (comme pour le NAS)

L'envoi passe par **le même scan** que le NAS (`SourceEnvoi`) : un dossier absent de l'envoi ou
signalé illisible ne fait rien disparaître ; une racine vide alors que l'inventaire connaît des
fichiers → scan en échec, rien n'est marqué disparu. Un envoi interrompu (PC éteint) est
abandonné au suivant, ou au bout de 6 h.

## 3. Copies entre le PC et le NAS

Le serveur demande à l'agent la **partielle** (début + fin du fichier) des fichiers dont la taille
existe ailleurs, puis la **complète** de ceux dont la partielle est partagée. L'agent calcule
exactement les mêmes empreintes que le serveur (test Go contre des valeurs de référence). Le
rapprochement côté serveur (passes de nuit sur le NAS, page *Doublons*) est l'**étape 6** du plan.

Réglages (`PUT /api/inventaire/reglages`) : `inventaire_agent_intervalle_min` (15),
`inventaire_agent_lecture_max_go_jour` (20 Go par poste et par jour — un PC sert d'abord à
travailler), `inventaire_copies_taille_min_mo` (1). L'agent tourne en mode arrière-plan de Windows.

## 4. Construire et tester

```powershell
.\agent\construire.ps1     # tests Go, exe (version vérifiée), SHA-256, zip dans agent\dist\
```

- Tests Go (`agent/agent_test.go`) : empreintes, parcours et lots, liste blanche, protocole contre
  un faux serveur, nouvelles tentatives, identité alignée avec l'installeur.
- Tests serveur : `backend/tests/test_inventaire_agent.py`.
- Vérifié de bout en bout le 13/11/2026 : l'agent construit sur PC-GAME a envoyé un inventaire à
  une Matothèque de test (PostgreSQL, worker séparé) ; jeton révoqué → 401 ; bombe gzip → 413.

## 5. Plus tard

- Écran *Postes* (étape 7) : créer un poste, voir son dernier contact, confier un dossier.
- **Mise à jour automatique** de l'agent, **exe signé** (Authenticode) : non prévus.
