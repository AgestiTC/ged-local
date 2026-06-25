# README-UTILISATEUR — Matothèque

> Checklist **humaine** (les étapes que Claude ne peut pas faire à ta place :
> clés, secrets GitHub, actions sur le NAS). Le détail technique est dans
> [README.md](README.md), [DEVELOPMENT.md](DEVELOPMENT.md) et [docs/](docs/).

**Matothèque** = GED locale intelligente (extraction Tika + IA Ollama + recherche
sémantique pgvector), 100 % locale. Repo : `github.com/AgestiTC/ged-local`.

---

## 1. Première installation (poste de dev)

- [ ] Cloner le repo : `git clone git@github.com:AgestiTC/ged-local.git`
- [ ] Copier `.env.example` → `.env` et renseigner `DB_PASSWORD` (mot de passe fort)
- [ ] Vérifier qu'**Ollama** tourne sur l'hôte (`http://localhost:11434`) avec les
      modèles requis (`mixtral`, `qwen3-embedding:8b`, …) — voir `CLAUDE.md`
- [ ] Lancer la stack : `docker compose up -d` (ou la boucle de dev, cf. DEVELOPMENT.md)
- [ ] Ouvrir l'UI : `http://localhost:3001`
- [ ] Valider : `./scripts/validate.ps1` (doit afficher `/healthz` et `/api/version` OK)

## 2. Configuration GitHub (une seule fois)

- [ ] Le repo `AgestiTC/ged-local` existe sur GitHub
- [ ] `git remote set-url origin git@github.com:AgestiTC/ged-local.git`
      (⚠️ retirer tout ancien remote contenant un token en clair — voir §5)
- [ ] Vérifier que les **GitHub Actions** sont activées (onglet Actions)
- [ ] Le registre **GHCR** publiera sous `ghcr.io/agestitc/docflow-backend` et
      `…/docflow-frontend` (packages rendus publics ou NAS authentifié)

## 3. Publier une version (release)

```powershell
# Sur main (après merge de develop) :
.\scripts\release.ps1 -Version 1.8.0 -Message "Ma nouvelle fonctionnalité"
# → bump VERSION + tag v1.8.0 + push → CI build + verify → images GHCR

.\scripts\check-image-ready.ps1 1.8.0    # attendre que la CI soit verte + images pullables
```

## 4. Déployer sur le NAS (Synology / Container Manager)

- [ ] Renseigner `.env.nas` (depuis `.env.nas.example`) avec `DOCFLOW_VERSION=1.8.0`
- [ ] Container Manager → projet → **Stop** → **Pull** (récupère `:1.8.0`) → **Up**
- [ ] Valider : `./scripts/validate.ps1 -TargetHost <ip-nas> -Port 8000`
- [ ] Détail complet : [docs/synology-deployment.md](docs/synology-deployment.md)

## 5. ⚠️ Sécurité — à faire absolument

- [ ] **Token en clair dans un remote git** : si `git remote -v` montre une URL
      `https://user:<token>@…`, le **révoquer** côté Gitea/GitHub et reconfigurer
      le remote en SSH. Un token poussé/loggé est compromis.
- [ ] Ne jamais committer `.env` (déjà dans `.gitignore`)
- [ ] Audit sécurité tous les 3 mois : `./scripts/security-audit.ps1`

## 6. Travail multi-poste (bureau / maison)

Les hooks `.claude/` font un `git pull` au démarrage de session et préviennent
s'il reste des commits/tags non poussés à la fin. Toujours **push avant de
changer de poste**.
