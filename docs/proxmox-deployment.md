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
```

> Le schéma est créé/complété par le backend au démarrage (`create_all`). **Ne pas lancer
> `alembic upgrade`** : les migrations sont vestigiales et échoueraient (`relation ... already exists`).

> Prérequis : les images `git.agesti.fr/agestitc/docflow-{backend,frontend}` doivent
> exister dans le registre Gitea — build/push manuel depuis Windows
> (`build-push.ps1`, ou `synology-deployment.md` Étape 2). Namespace **en minuscules**.

---

## Retour d'expérience — pièges & correctifs (déploiement réel LXC)

Le service `docker` de Proxmox était un **conteneur LXC** (pas une VM QEMU), partagé avec
d'autres services (portainer, npmplus…). Points appris, résumés (détail complet : livre
BookStack *« Déploiement Matothèque sur Proxmox »*) :

| Sujet | À retenir |
|-------|-----------|
| **Accès** | `pct enter 102` depuis pve (pas de SSH root sur le LXC ; `qm` ne marche pas sur un LXC). |
| **Secret DB** | Le conteneur tourne en `appuser` (UID 10001) : `chown 10001:10001 secrets/db_password.txt && chmod 400` (sinon `Permission denied`). |
| **Mot de passe PG** | PostgreSQL fige le mot de passe au 1er init. Sur base neuve incohérente : `docker compose down && rm -rf data/postgres/* && docker compose up -d`. |
| **Port** | `8000` souvent déjà pris → publier le backend sur **8008**. |
| **Worker** | `healthcheck: disable: true` (sinon `unhealthy` à tort). |
| **RAM** | Prévoir **6 Go** pour le LXC (`pct set 102 --memory 6144`) ; 2 Go insuffisants avec ClamAV. |
| **Disque** | Prévoir **≥ 20 Go** (`pct resize 102 rootfs +12G`) ; un disque plein tronque les transferts. |
| **IA / Sources** | Réglées dans l'UI (Paramètres → *Enregistrer* **puis** *Rafraîchir* pour les modèles). |

**Récupérer une base déjà indexée** (dump/restore dev → prod, sans réindexer) : voir la page
*Migration de la base* du livre BookStack (validé sur 56k documents / dump ~1,5 Go).
