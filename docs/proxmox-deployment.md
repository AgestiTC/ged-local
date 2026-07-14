# Déploiement sur Proxmox — Matothèque

Cible : la **VM `docker`** existante du nœud Proxmox (hôte Docker). Aucune nouvelle
VM à créer — tout est du `docker compose`.

## Principes (différences avec le NAS)

| Sujet | Ici | Pourquoi |
|-------|-----|----------|
| **Mot de passe DB** | fichier secret `secrets/db_password.txt` (`chmod 600`) | jamais en clair dans `.env` ni le compose — `POSTGRES_PASSWORD_FILE` + `DB_PASSWORD_FILE` |
| **URL Ollama** | réglée dans **Paramètres → Services & modèles IA** | surcharge base > env, testable dans l'UI, modifiable à chaud |
| **Sources documents** | **Sources / Connecteurs** (SMB, Synology) dans l'UI | indexation à distance, pas de montage local requis |
| **ClamAV** | désactivé par défaut (profil `antivirus`) | ~1,5–2 Go de RAM ; nœud tendu en mémoire |
| **Ollama** | **hors Proxmox**, sur le PC Windows | le backend l'appelle par le réseau (URL réglée dans l'UI) |

## Ressources

Stack au repos ≈ **2,5–3,5 Go** (sans ClamAV), CPU 2 cœurs suffisant (le LLM est
déporté). Avec ClamAV : +1,5–2 Go. Vérifier la RAM libre du nœud avant d'activer l'AV.

## Étapes

```bash
# Sur la VM docker, dans /opt/docflow (récupérer les 2 fichiers du repo)
#   docker-compose.proxmox.yml  +  .env.proxmox.example

cp .env.proxmox.example .env                 # ajuster ports / DB_USER / DB_NAME si besoin

# Secret DB (mot de passe fort, hors git, lisible par root seul)
mkdir -p secrets
openssl rand -base64 24 > secrets/db_password.txt
chmod 600 secrets/db_password.txt

# Dossiers persistants
mkdir -p data/postgres storage/{uploads,exports,templates,tika-config} logs

# Registre Gitea (images pré-buildées)
docker login git.agesti.fr                   # user AgestiTC + token read:package

# Démarrage
docker compose -f docker-compose.proxmox.yml up -d
docker exec docflow_backend alembic upgrade head    # migrations (1re fois)
```

Accès : `http://<IP-VM>:3003` (app) · `http://<IP-VM>:8000/docs` (API).

## Post-démarrage (dans l'UI)

1. **Paramètres → Services & modèles IA** : saisir l'URL Ollama = `http://<IP-PC-Windows>:11434`
   → **Tester** → **Enregistrer**. Choisir le modèle par défaut + les modèles par usage.
   *(Sur le PC : `OLLAMA_HOST=0.0.0.0` + pare-feu port 11434.)*
2. **Sources / Connecteurs** : ajouter les partages SMB / comptes Synology à indexer.

## Variantes

- **Activer l'antivirus** :
  ```bash
  # décommenter CLAMAV_HOST=clamav dans .env, puis :
  docker compose -f docker-compose.proxmox.yml --profile antivirus up -d
  ```
- **Surveiller un dossier local / doublons sur disque** : décommenter le montage
  `- /mnt/documents:/app/documents:rw` (backend **et** worker) dans le compose, en
  pointant vers un montage SMB/NFS du NAS sur la VM.
- **Version figée** : `DOCFLOW_VERSION=vX.Y.Z` dans `.env` (défaut `latest`).

## Mise à jour

```bash
docker compose -f docker-compose.proxmox.yml pull
docker compose -f docker-compose.proxmox.yml up -d
docker exec docflow_backend alembic upgrade head   # si migration
```

> Prérequis : les images `git.agesti.fr/tclement/docflow-{backend,frontend}` doivent
> exister dans le registre Gitea — build/push manuel depuis Windows
> (cf. `synology-deployment.md`, Étape 2).
