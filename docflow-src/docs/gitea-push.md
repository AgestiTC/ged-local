# Déploiement Git — DocFlow AI sur Gitea

## Informations du dépôt

| Paramètre        | Valeur                                          |
|------------------|-------------------------------------------------|
| Instance Gitea   | `https://git.agesti.fr`                         |
| Utilisateur      | `tclement`                                      |
| Dépôt            | `docflow`                                       |
| URL complète     | `https://git.agesti.fr/tclement/docflow`        |
| Branche          | `main`                                          |
| Visibilité       | Privé                                           |

---

## Mise en place initiale (fait le 2026-04-13)

### Étape 1 — Créer le dépôt sur Gitea (interface web)

> ⚠️ Ne pas utiliser l'API Gitea pour créer le dépôt : les scopes requis (`write:user`) sont différents de ceux nécessaires pour le push (`write:repository`). Passer par l'interface web est plus simple.

1. Se connecter sur `https://git.agesti.fr`
2. Cliquer **"+"** → **Nouveau dépôt**
3. Remplir :
   - **Nom** : `docflow`
   - **Description** : `DocFlow AI — Plateforme locale de gestion documentaire intelligente`
   - **Visibilité** : Privé ✅
   - **Initialiser ce dépôt** : ❌ Ne pas cocher (le projet a déjà un historique Git)
4. Cliquer **Créer le dépôt**

---

### Étape 2 — Générer un token d'accès personnel

1. `https://git.agesti.fr` → menu utilisateur → **Paramètres**
2. Onglet **Applications**
3. Section **Jetons d'accès personnels** → **Générer un jeton**
4. Remplir :
   - **Nom du token** : `docflow-push` (ou tout autre nom descriptif)
   - **Droits** : `repository` → **Lecture et écriture** ✅
5. Cliquer **Générer le jeton**
6. **Copier immédiatement** le token affiché — il ne sera plus visible après

> ⚠️ Sécurité : ne jamais coller le token dans un chat, un email ou un fichier versionné.
> Si le token est exposé accidentellement → le révoquer immédiatement et en générer un nouveau.

---

### Étape 3 — Configurer le remote Git

```powershell
git remote set-url origin https://tclement:TON_TOKEN@git.agesti.fr/tclement/docflow.git
```

Vérifier que le remote est bien configuré :

```powershell
git remote -v
# origin  https://tclement:***@git.agesti.fr/tclement/docflow.git (fetch)
# origin  https://tclement:***@git.agesti.fr/tclement/docflow.git (push)
```

---

### Étape 4 — Premier push

```powershell
git push -u origin main
```

Le `-u` configure le tracking automatique : les prochains `git push` n'ont plus besoin d'arguments.

**Résultat observé le 2026-04-13 :**
```
Enumerating objects: 271, done.
Writing objects: 100% (271/271), 230.57 KiB | 5.91 MiB/s, done.
branch 'main' set up to track 'origin/main'.
```

---

## Workflow quotidien

### Pousser les modifications

```powershell
# Vérifier ce qui a changé
git status

# Ajouter les fichiers modifiés
git add nom_du_fichier
# ou pour tout ajouter (attention aux fichiers sensibles)
git add .

# Créer un commit
git commit -m "feat: description du changement"

# Pousser
git push
```

### Conventions de commit

```
feat:     nouvelle fonctionnalité
fix:      correction de bug
refactor: refactoring sans changement de comportement
test:     ajout ou modification de tests
docs:     documentation uniquement
chore:    maintenance (dépendances, config...)
```

---

## Renouveler le token (rotation de sécurité)

À faire régulièrement ou si le token est compromis :

1. `https://git.agesti.fr` → Paramètres → Applications
2. **Supprimer** l'ancien token
3. **Générer** un nouveau token (`repository` → Lecture et écriture)
4. Mettre à jour le remote :

```powershell
git remote set-url origin https://tclement:NOUVEAU_TOKEN@git.agesti.fr/tclement/docflow.git
```

---

## Problèmes rencontrés et solutions

### `curl: (3) URL rejected: Bad hostname`

**Cause :** Sur Windows, `curl` est un alias PowerShell (`Invoke-WebRequest`) qui n'accepte pas les options Unix.

**Solution :** Utiliser `curl.exe` (le vrai curl) et écrire la commande **sur une seule ligne** sans `\` :

```powershell
curl.exe -X POST "https://git.agesti.fr/api/v1/user/repos" -H "Authorization: token TON_TOKEN" -H "Content-Type: application/json" -d "{\"name\":\"docflow\",\"private\":true}"
```

> Note : `\` est la continuation de ligne en Bash. En PowerShell c'est `` ` ``. Sur une seule ligne, le problème n'existe pas.

---

### `token does not have at least one of required scope(s), required=[write:user]`

**Cause :** L'API Gitea `POST /api/v1/user/repos` exige le scope `write:user`, différent du scope nécessaire pour le push (`write:repository`).

**Solution :** Créer le dépôt via **l'interface web Gitea** (pas l'API), puis utiliser un token `write:repository` uniquement pour le push.

---

### `curl: (3) unmatched close brace/bracket in URL`

**Cause :** La commande a été copiée sur plusieurs lignes dans PowerShell — le shell a interprété le JSON comme une URL.

**Solution :** Écrire la commande entière sur **une seule ligne** dans le terminal PowerShell.

---

## Commandes utiles

```powershell
# Voir l'état du dépôt local
git status

# Voir les commits
git log --oneline -10

# Voir le remote configuré
git remote -v

# Vérifier la synchronisation avec Gitea
git fetch origin
git status  # indique si on est en avance/retard sur origin/main

# Voir les branches
git branch -a
```

---

## Structure du dépôt sur Gitea

```
https://git.agesti.fr/tclement/docflow
├── backend/          API FastAPI + tests pytest
├── frontend/         React + TypeScript + tests Vitest + E2E Playwright
├── n8n/workflows/    Workflows d'automatisation
├── docs/             Documentation (dont ce fichier)
├── scripts/          SQL init + seed prompts
├── storage/          Dossiers de stockage (fichiers exclus par .gitignore)
├── docker-compose.yml
├── .env.example      Template de configuration (jamais .env lui-même)
├── Makefile          Toutes les commandes de développement
├── CLAUDE.md         Instructions pour l'IA
├── MEMORY.md         État d'avancement du projet
└── CHANGELOG.md      Historique des versions
```
