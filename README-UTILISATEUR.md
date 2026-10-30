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
- [ ] Ajouter le remote **Gitea** (le vrai registre d'images) :
      `git remote add gitea https://git.agesti.fr/AgestiTC/GED-LOCAL.git`
- [ ] `docker login git.agesti.fr` une fois sur le poste Windows qui publie
- [ ] Clé SSH `~/.ssh/id_proxmox` présente (elle ouvre `root@192.168.42.83`, le LXC de prod)

> ⚠️ Les GitHub Actions / GHCR sont un **vestige** : pousser un tag ne construit aucune image
> utilisable. Les images sont `git.agesti.fr/agestitc/docflow-{backend,frontend}`.

## 3. Publier une version (release)

```powershell
# Sur main :
.\scripts\release.ps1 -Version 1.8.0 -Message "Ma nouvelle fonctionnalité"
# → bump VERSION + package.json + commit + tag v1.8.0 + push origin
git push gitea main --follow-tags          # le script ne pousse pas sur Gitea
```

## 4. Déployer en prod (LXC « docker », Proxmox)

- [ ] Docker Desktop lancé sur le poste Windows
- [ ] `.\scripts\deployer.ps1` — build `1.8.0` **et** `latest`, push Gitea, `pull`/`up -d`/
      `restart frontend` sur `192.168.42.83:/opt/docflow`, puis vérification
- [ ] Le verdict qui compte : `.\scripts\verifier-deploiement.ps1` doit finir en **[OK]**
- [ ] Dans le navigateur : **Ctrl+Shift+R**, le numéro sous « Matothèque » = `VERSION`
- [ ] Détail et pièges : `CLAUDE.md` § Déploiement
- [ ] (Ancien déploiement NAS Synology, non utilisé : [docs/synology-deployment.md](docs/synology-deployment.md))

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
