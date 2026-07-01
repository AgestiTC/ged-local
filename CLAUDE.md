# CLAUDE.md — Projet Matothèque (repo AgestiTC/ged-local · ex-« DocFlow AI »)

> **Nommage** : marque produit = **Matothèque** · repo Git = `AgestiTC/ged-local` ·
> identifiants techniques (DB, images GHCR) restés `docflow-*`. Aligné sur le modèle
> docker AgestiTC. Plan & avancement : [ROADMAP.md](ROADMAP.md).

## 🎯 Vue d'ensemble du projet

**Matothèque** est une plateforme locale de gestion documentaire intelligente composée de deux modules principaux :

1. **Rapports** — Génération automatique de rapports/classements (libre, template, comparatif) à partir de documents (PDF, PPTX, PPSX, DOCX, XLSX, ZIP…) via IA locale
2. **GED** — Gestion Électronique de Documents locale avec recherche hybride (full-text + sémantique)

S'y ajoutent : **Sources NAS/SMB** (indexer les partages), **Doublons** (détection + quarantaine),
**Antivirus** (ClamAV à l'indexation), **Administration des modèles IA**. Le tout **100 % local**,
sans cloud, IA via Ollama.

---

## 🏗️ Stack technique

### Infrastructure existante (déjà installée)

| Composant | Rôle | URL par défaut |
|-----------|------|----------------|
| **Ollama** | Serveur LLM local | `http://localhost:11434` |
| **Apache Tika** | Extraction de texte/métadonnées de tous formats | `http://localhost:9998` |
| **n8n** | Orchestration de workflows, surveillance de dossiers | `http://localhost:5678` |
| **Open-WebUI** | Chat IA (usage séparé, pas dans ce projet) | `http://localhost:3000` |

### Modèles Ollama disponibles

> **MAJ 01/07/2026** — Réalité actuelle (audit modèles) : OCR = **Tesseract via Tika**
> (`apache/tika:*-full`, fra+eng), pas glm-ocr. Raisonnement principal = **Qwen3.6-35B**.
> Modèle **par défaut** (enrichissement) = **`llama3.1:latest`**. Modèle **vision** configurable
> (`vision_model`, défaut glm-ocr, recommandé **qwen2.5-vl:7b**).

| Modèle | Usage dans le projet | Statut |
|--------|---------------------|--------|
| `Qwen3.6-35B:latest` (43.6 GB, MoE 34.7B) | **Raisonnement / rapports haut de gamme** — modèle principal | ✅ à jour |
| `ministral-3:14b` (9.1 GB) | Génération intermédiaire, bon compromis | ✅ |
| `llama3.1:latest` (4.9 GB) | **Modèle par défaut** (enrichissement : catégorie/tags/résumé), tâches légères | ✅ |
| `qwen3-embedding:8b` (4.7 GB, 4096d) | **Embeddings GED** — modèle embedding principal | ✅ |
| `nomic-embed-text:latest` (274 MB) | Embeddings légers, fallback rapide | ✅ |
| `qwen2.5-vl:7b` *(à installer)* | **Vision** (description d'images / OCR de secours) — remplace llava | ➕ recommandé |
| `mixtral:latest` (26 GB) | Ancien « principal » — redondant avec Qwen3.6-35B | ⚠️ legacy (retrait possible) |
| `mistral:latest` (4.4 GB) | Redondant avec llama3.1 | ⚠️ legacy (retrait possible) |
| `llava:latest` (4.7 GB) | Vision dépassée (non câblé) | ⚠️ remplacer par qwen2.5-vl |
| `glm-ocr:latest` (2.2 GB) | OCR faible (1.1B) — **supplanté par Tesseract/Tika** | 🔴 obsolète (retrait possible) |

### Stack à mettre en place

| Composant | Rôle |
|-----------|------|
| **PostgreSQL 16 + pgvector** | Base de données : documents, métadonnées, embeddings vectoriels |
| **FastAPI (Python 3.11+)** | API backend / orchestrateur |
| **React 18 + TypeScript + Vite** | Interface web |
| **TailwindCSS** | Styling |
| **Docker Compose** | Déploiement de l'ensemble |

---

## 📐 Architecture globale

```
┌──────────────────────────────────────────────────────────┐
│              Interface Web (React + TypeScript)           │
│                                                          │
│  ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐  │
│  │ Navigateur  │ │ Éditeur  │ │ Mode     │ │ GED     │  │
│  │ fichiers +  │ │ prompt + │ │ sortie + │ │ Recherche│  │
│  │ drag & drop │ │ presets  │ │ template │ │ + browse│  │
│  └─────────────┘ └──────────┘ └──────────┘ └─────────┘  │
│                                                          │
│  ⬆ Drag & Drop : fichiers, dossiers, ZIP                │
└──────────────────────┬───────────────────────────────────┘
                       │ REST API
              ┌────────▼────────┐
              │   FastAPI       │
              │   Backend       │
              │                 │
              │ /api/extract    │ → appelle Tika
              │ /api/generate   │ → appelle Ollama
              │ /api/documents  │ → CRUD PostgreSQL
              │ /api/search     │ → full-text + vectoriel
              │ /api/export     │ → génère PDF/DOCX
              │ /api/folders    │ → listing dossiers
              │ /api/templates  │ → gestion templates
              │ /api/upload     │ → upload + drag & drop
              └──┬────┬────┬───┘
                 │    │    │
     ┌───────────▼┐ ┌─▼──┐ ┌▼──────────────────┐
     │   Tika     │ │Olla│ │  PostgreSQL        │
     │   Server   │ │ ma │ │  + pgvector        │
     │            │ │    │ │                    │
     │ Extraction │ │LLM │ │ documents          │
     │ texte +    │ │API │ │ metadonnees_ia     │
     │ métadonnées│ │    │ │ embeddings         │
     │ tous       │ │    │ │ versions           │
     │ formats    │ │    │ │ templates          │
     └────────────┘ └────┘ │ jobs               │
                           └────────────────────┘
              ┌────────────────┐
              │      n8n       │
              │                │
              │ • Watch Folder │ → détecte nouveaux fichiers
              │ • Cron indexer │ → réindexation périodique
              │ • Webhook      │ → déclenché par l'API
              └────────────────┘
```

---

## 📁 Structure du projet

```
matothèque/   (repo AgestiTC/ged-local · marque « Matothèque » · images GHCR docflow-*)
├── VERSION                       # source de vérité version (→ /api/version)
├── docker-compose.yml            # PROD : init + postgres + tika + clamav 🆕 + backend + frontend
├── docker-compose.dev.yml        # DEV « tout en conteneurs » (Dockerfile.dev + hot-reload) 🆕
├── docker-compose.nas.yml        # déploiement NAS (images GHCR)
├── CLAUDE.md · MEMORY.md · README.md · README-UTILISATEUR.md 🆕 · DEVELOPMENT.md 🆕 · ROADMAP.md 🆕 · CHANGELOG.md
├── .claude/hooks/                # hooks versionnés : session-start-pull / security-check / end-warn 🆕
├── .github/                      # CI : build-push (tag-driven + verify) · security-audit · dependabot 🆕
├── scripts/                      # release · check-image-ready · validate · security-audit (.ps1) 🆕 · init-db.sql · seed-prompts.json
│
├── backend/                      # API FastAPI
│   ├── Dockerfile · Dockerfile.dev 🆕 · requirements.txt
│   ├── main.py · config.py · database.py · logger.py
│   ├── models/                   # SQLAlchemy : document, metadata, embedding, version, template, job, prompt, folder
│   │   ├── config.py             # 🆕 config en base (URLs services, modèle par défaut)
│   │   └── source.py             # 🆕 sources de fichiers (local | smb, identifiants chiffrés)
│   ├── services/                 # tika, ollama, extraction, embedding, search, report_generator, template_filler, export, folder_watcher, ged
│   │   ├── crypto.py             # 🆕 Fernet — chiffrement des secrets en base
│   │   ├── runtime_config.py     # 🆕 surcharge de config à chaud (base > env)
│   │   ├── smb_service.py        # 🆕 client SMB (pysmb) : partages / browse / fetch
│   │   ├── duplicate_service.py  # 🆕 détection de doublons (scan disque)
│   │   └── clamav_service.py     # 🆕 antivirus (scan à l'indexation)
│   ├── routers/                  # extract, generate, documents, search, export, folders, templates, upload, prompts, compare
│   │   ├── sources.py            # 🆕 /api/sources (CRUD, test, shares, browse, index)
│   │   ├── duplicates.py         # 🆕 /api/duplicates (scan, quarantine)
│   │   └── system.py             # 🆕 /api/version · /api/logs/tail · /api/system/{config,models,services,test}
│   ├── utils/ (chunker, file_utils, hash_utils) · tests/ · alembic/
│
├── frontend/                     # React 18 + Vite + Tailwind
│   ├── Dockerfile · Dockerfile.dev 🆕 · vite.config.ts · .env.development 🆕
│   └── src/
│       ├── api/ (client.ts · index.ts : documents, sources 🆕, duplicates 🆕, system 🆕, …)
│       ├── components/
│       │   ├── layout/ · files/ · reports/ (+ GroupBuilder, CompareProgress) · common/
│       │   └── ged/ (SearchBar, DocumentCard, TagManager, CategoryBrowser, VersionHistory, SourcesManager 🆕)
│       ├── hooks/ · stores/ (Zustand) · types/
│       └── pages/ (ReportsPage · GEDPage · SettingsPage · DuplicatesPage 🆕)
│
├── n8n/workflows/ · storage/ (documents, uploads, exports, templates, tika-config) · data/ (postgres, clamav 🆕)
└── ant-tool/   (gitignoré — prototype PowerShell de référence, cf. docs/plan-reorganisation-arborescence.md)
```

> 🆕 = ajouté depuis la refonte Matothèque (sources NAS/SMB, antivirus, doublons, admin modèles,
> docker de dev, alignement modèle AgestiTC). Détail des chantiers : [ROADMAP.md](ROADMAP.md).

---

## 🗄️ Schéma de base de données

### PostgreSQL + pgvector

```sql
-- Activer pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- Pour la recherche full-text rapide

-- Table principale des documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chemin TEXT NOT NULL,                    -- Chemin absolu du fichier source
    nom TEXT NOT NULL,                       -- Nom du fichier
    extension TEXT NOT NULL,                 -- pdf, docx, pptx, xlsx, zip...
    type_mime TEXT,                          -- Retourné par Tika
    hash_sha256 TEXT NOT NULL,              -- Pour déduplication et versioning
    taille_octets BIGINT,
    date_import TIMESTAMPTZ DEFAULT NOW(),
    date_modification_fichier TIMESTAMPTZ,  -- Date de modif du fichier source
    date_derniere_extraction TIMESTAMPTZ,
    texte_extrait TEXT,                     -- Texte brut extrait par Tika
    tika_metadata JSONB,                    -- Métadonnées brutes Tika (JSON)
    statut TEXT DEFAULT 'pending',          -- pending, extracted, enriched, error
    erreur TEXT,                            -- Message d'erreur si échec
    source TEXT DEFAULT 'watch',            -- watch (dossier surveillé), upload, drag_drop
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_documents_hash ON documents(hash_sha256);
CREATE INDEX idx_documents_chemin ON documents(chemin);
CREATE INDEX idx_documents_statut ON documents(statut);
CREATE INDEX idx_documents_nom_trgm ON documents USING gin(nom gin_trgm_ops);
CREATE INDEX idx_documents_texte_fts ON documents USING gin(to_tsvector('french', texte_extrait));

-- Métadonnées enrichies par l'IA
CREATE TABLE metadonnees_ia (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    categorie TEXT,                          -- Catégorie déterminée par le LLM
    sous_categorie TEXT,
    tags TEXT[],                             -- Tags extraits par le LLM
    resume TEXT,                             -- Résumé auto-généré
    langue TEXT,                             -- Langue détectée
    entites JSONB,                          -- Entités extraites : {personnes:[], dates:[], lieux:[], organisations:[]}
    mots_cles TEXT[],                       -- Mots-clés extraits
    niveau_confidentialite TEXT DEFAULT 'normal', -- normal, confidentiel, restreint
    modele_utilise TEXT,                    -- Nom du modèle Ollama utilisé
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id)
);

CREATE INDEX idx_meta_categorie ON metadonnees_ia(categorie);
CREATE INDEX idx_meta_tags ON metadonnees_ia USING gin(tags);

-- Embeddings vectoriels pour la recherche sémantique
CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,           -- Index du chunk dans le document
    chunk_text TEXT NOT NULL,               -- Texte du chunk
    embedding vector(4096),                 -- Vecteur (qwen3-embedding:8b = 4096 dims)
    modele_embedding TEXT DEFAULT 'qwen3-embedding:8b',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_embeddings_document ON embeddings(document_id);
CREATE INDEX idx_embeddings_vector ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Historique des versions de documents
CREATE TABLE versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    numero_version INTEGER NOT NULL,
    hash_sha256 TEXT NOT NULL,
    taille_octets BIGINT,
    date_detection TIMESTAMPTZ DEFAULT NOW(),
    diff_resume TEXT,                       -- Résumé des changements par le LLM
    chemin_archive TEXT                     -- Chemin vers la version archivée si conservée
);

CREATE INDEX idx_versions_document ON versions(document_id);

-- Templates de documents (pour le remplissage)
CREATE TABLE templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nom TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL,                     -- docx, pdf
    chemin_fichier TEXT NOT NULL,           -- Chemin vers le fichier template
    champs JSONB,                          -- Liste des champs à remplir [{nom, type, description}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prompts pré-enregistrés
CREATE TABLE prompts_presets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nom TEXT NOT NULL,
    description TEXT,
    prompt_text TEXT NOT NULL,
    categorie TEXT,                         -- rapport, classement, extraction, analyse
    modele_prefere TEXT,                    -- Modèle Ollama recommandé
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- File d'attente des jobs
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,                     -- extraction, enrichissement, rapport, embedding
    statut TEXT DEFAULT 'pending',          -- pending, running, completed, failed
    document_id UUID REFERENCES documents(id),
    parametres JSONB,                       -- Paramètres du job
    resultat JSONB,                         -- Résultat du job
    erreur TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_jobs_statut ON jobs(statut);
CREATE INDEX idx_jobs_type ON jobs(type);

-- Dossiers surveillés
CREATE TABLE dossiers_surveilles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chemin TEXT NOT NULL UNIQUE,
    nom_affichage TEXT,
    actif BOOLEAN DEFAULT true,
    recursive BOOLEAN DEFAULT true,         -- Surveiller les sous-dossiers
    extensions_filtrees TEXT[],             -- Filtrer par extension (null = tout)
    intervalle_scan_secondes INTEGER DEFAULT 300,  -- 5 min par défaut
    dernier_scan TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 🔌 API Endpoints détaillés

### Extraction & Upload

```
POST   /api/upload                    # Upload fichier(s) — supporte multipart + drag & drop
POST   /api/upload/folder             # Upload dossier complet (drag & drop dossier)
POST   /api/upload/zip                # Upload ZIP → extraction automatique
POST   /api/extract/{document_id}     # Relancer l'extraction d'un document
GET    /api/extract/status/{job_id}   # Statut d'un job d'extraction
```

### Documents (CRUD)

```
GET    /api/documents                 # Liste documents (pagination, filtres)
GET    /api/documents/{id}            # Détail d'un document
GET    /api/documents/{id}/text       # Texte extrait
GET    /api/documents/{id}/metadata   # Métadonnées IA
GET    /api/documents/{id}/versions   # Historique versions
DELETE /api/documents/{id}            # Supprimer un document de l'index
```

### Génération de rapports

```
POST   /api/generate/report           # Générer un rapport libre
  Body: {
    document_ids: string[],           # Documents sélectionnés
    prompt: string,                   # Prompt utilisateur
    model: string,                    # Modèle Ollama (défaut: mixtral)
    output_format: "markdown" | "text"
  }

POST   /api/generate/fill-template    # Remplir un template
  Body: {
    document_ids: string[],
    template_id: string,
    instructions: string,             # Instructions supplémentaires
    model: string
  }

GET    /api/generate/status/{job_id}  # Statut de la génération
GET    /api/generate/stream/{job_id}  # Stream SSE du rapport en cours
```

### Export

```
POST   /api/export/pdf                # Exporter en PDF
  Body: { content: string, title: string }

POST   /api/export/docx               # Exporter en DOCX
  Body: { content: string, title: string }
```

### Recherche (GED)

```
GET    /api/search?q=...&type=hybrid  # Recherche hybride (full-text + sémantique)
GET    /api/search?q=...&type=text    # Recherche full-text uniquement
GET    /api/search?q=...&type=semantic # Recherche sémantique uniquement
GET    /api/search/tags               # Liste tous les tags
GET    /api/search/categories         # Liste toutes les catégories
```

### Dossiers surveillés

```
GET    /api/folders                    # Liste dossiers surveillés
POST   /api/folders                   # Ajouter un dossier à surveiller
PUT    /api/folders/{id}              # Modifier config surveillance
DELETE /api/folders/{id}              # Retirer un dossier
POST   /api/folders/{id}/scan         # Forcer un scan immédiat
GET    /api/folders/browse?path=...   # Naviguer dans le système de fichiers
```

### Templates

```
GET    /api/templates                 # Liste templates disponibles
POST   /api/templates                 # Upload nouveau template
GET    /api/templates/{id}            # Détail template + champs détectés
DELETE /api/templates/{id}            # Supprimer template
```

### Prompts pré-enregistrés

```
GET    /api/prompts                   # Liste prompts presets
POST   /api/prompts                   # Créer un preset
PUT    /api/prompts/{id}              # Modifier
DELETE /api/prompts/{id}              # Supprimer
```

---

## 🖥️ Spécifications de l'interface web

### Page Rapports (page principale)

**Layout :** 3 colonnes responsive → sidebar gauche (fichiers) + centre (prompt + config) + droite (résultat)

**Colonne gauche — Sélection de fichiers :**
- Arborescence des dossiers surveillés avec cases à cocher
- Indicateur de statut par fichier : ● vert (indexé), ● orange (en cours), ● rouge (erreur), ● gris (non indexé)
- Barre de recherche rapide pour filtrer les fichiers
- **Zone drag & drop** en haut : glisser-déposer fichiers, dossiers entiers, ou ZIP
  - Accepte : `.pdf`, `.docx`, `.pptx`, `.ppsx`, `.xlsx`, `.zip`
  - Feedback visuel : bordure en pointillés qui s'illumine au survol
  - Barre de progression pour l'upload et l'extraction
  - Pour les ZIP : extraction automatique, affichage du contenu après extraction
  - Pour les dossiers : récursion automatique, affichage de l'arborescence
- Multi-sélection avec Ctrl+clic et Shift+clic
- Bouton "Tout sélectionner" / "Tout désélectionner"

**Colonne centrale — Configuration :**
- Sélecteur de mode : "Rapport libre" | "Remplir un template" | "Classement/Tri"
- Éditeur de prompt (textarea redimensionnable avec coloration syntaxique basique)
- Dropdown prompts pré-enregistrés avec bouton "Sauvegarder ce prompt"
- Sélecteur de modèle Ollama (dropdown avec indication de taille/vitesse)
- Si mode "Template" : zone d'upload du template DOCX/PDF + prévisualisation des champs détectés
- **Bouton "Générer"** (gros, bien visible, en bas)
- Indicateur de tokens estimés / temps estimé

**Colonne droite — Résultat :**
- Prévisualisation du rapport en markdown rendu
- Barre d'outils : "Exporter PDF" | "Exporter DOCX" | "Copier" | "Régénérer"
- Édition inline du résultat avant export
- Historique des rapports précédents (accordéon)

### Page GED

**Layout :** Barre de recherche en haut + grille de résultats

- **Barre de recherche unifiée** : texte libre → recherche hybride (full-text + sémantique)
- Filtres latéraux : par catégorie, tags, type de fichier, date, dossier source
- **Grille de résultats** : cartes de documents avec miniature, titre, catégorie, tags, score de pertinence
- **Fiche document** (panneau latéral ou modal) : prévisualisation, métadonnées complètes, résumé IA, tags éditables, historique des versions, bouton "Utiliser dans un rapport"
- **Zone drag & drop** globale pour ajouter des documents à la GED
- Statistiques : nombre de documents, répartition par catégorie, espace utilisé

### Page Paramètres

- Gestion des dossiers surveillés (ajouter/retirer/configurer)
- Configuration des modèles Ollama (modèle par défaut, paramètres)
- Gestion des prompts pré-enregistrés
- Gestion des templates
- Statistiques système (espace disque, nombre de documents, état des services)
- URLs des services (Tika, Ollama, PostgreSQL)
- Test de connexion pour chaque service

---

## 🔄 Flux de traitement des documents

### Flux d'extraction (quand un fichier est détecté ou uploadé)

```
1. Fichier détecté (watcher n8n) ou uploadé (API upload / drag & drop)
   │
2. Calcul hash SHA256
   │ → Si hash existe déjà → vérifier si même chemin (doublon) ou nouveau chemin (copie)
   │
3. Insertion dans `documents` (statut = 'pending')
   │
4. Création job d'extraction (table `jobs`)
   │
5. Appel Tika Server :
   │   PUT http://tika:9998/rmeta/text  (avec le fichier)
   │   → Récupère texte + métadonnées complètes
   │   → Si ZIP : Tika extrait chaque fichier du ZIP individuellement
   │
6. Stockage texte_extrait + tika_metadata dans `documents`
   │   → Statut = 'extracted'
   │
7. Enrichissement IA (Ollama) :
   │   → Prompt système : "Analyse ce document et retourne un JSON avec :
   │     categorie, sous_categorie, tags[], resume, langue, entites, mots_cles"
   │   → Modèle : mistral (rapide) ou mixtral (qualité)
   │   → Stockage dans `metadonnees_ia`
   │
8. Génération embeddings :
   │   → Découpage en chunks (500 tokens, overlap 50)
   │   → Pour chaque chunk : POST http://ollama:11434/api/embeddings
   │     avec modèle qwen3-embedding:8b
   │   → Stockage dans `embeddings`
   │
9. Statut final = 'enriched'
```

### Flux de génération de rapport

```
1. Utilisateur sélectionne des documents + écrit un prompt
   │
2. API récupère les textes extraits des documents sélectionnés
   │
3. Construction du contexte :
   │   "Voici les documents à analyser :
   │    --- Document 1 : {nom} ---
   │    {texte_extrait (tronqué si nécessaire)}
   │    --- Document 2 : {nom} ---
   │    {texte_extrait}
   │    ...
   │    --- Instruction ---
   │    {prompt utilisateur}"
   │
4. Appel Ollama (mixtral ou modèle choisi) en streaming
   │   → SSE vers le frontend pour affichage progressif
   │
5. Rapport stocké en mémoire (pas en DB sauf si sauvegarde demandée)
   │
6. Export : markdown → PDF (via weasyprint) ou DOCX (via python-docx)
```

---

## ⚙️ Configuration Docker Compose

```yaml
# docker-compose.yml — Structure attendue
services:
  # PostgreSQL avec pgvector
  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init.sql
    environment:
      POSTGRES_DB: docflow
      POSTGRES_USER: docflow
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  # Backend FastAPI
  backend:
    build: ./backend
    ports: ["8000:8000"]
    volumes:
      - ./storage:/app/storage
      - ${DOCUMENTS_ROOT}:/app/documents:ro  # Dossiers à surveiller (lecture seule)
    environment:
      DATABASE_URL: postgresql://docflow:${DB_PASSWORD}@postgres:5432/docflow
      TIKA_URL: http://tika:9998
      OLLAMA_URL: http://host.docker.internal:11434  # Ollama tourne sur l'hôte
    depends_on: [postgres]

  # Frontend React
  frontend:
    build: ./frontend
    ports: ["3001:80"]
    depends_on: [backend]

  # Tika (déjà existant, ajouter au compose si pas encore fait)
  tika:
    image: apache/tika:latest
    ports: ["9998:9998"]
```

**Note :** Ollama et n8n tournent déjà sur l'hôte, pas besoin de les inclure dans le compose. Le backend y accède via `host.docker.internal` ou l'IP de l'hôte.

---

## 📝 Règles de développement

### Backend (Python / FastAPI)

- Python 3.11+ avec type hints partout
- FastAPI avec Pydantic v2 pour la validation
- SQLAlchemy 2.0 (style async) + Alembic pour les migrations
- Gestion d'erreurs centralisée avec des exceptions custom
- Logging structuré (JSON) avec `structlog`
- Tous les appels à Tika et Ollama doivent être async (httpx)
- Timeout configurable pour les appels Ollama (les gros modèles sont lents)
- Chunking de texte : 500 tokens par chunk, 50 tokens d'overlap
- Les fichiers uploadés sont stockés dans `/app/storage/uploads/`
- Les exports sont stockés dans `/app/storage/exports/`

### Frontend (React / TypeScript)

- React 18 + TypeScript strict
- Vite comme bundler
- TailwindCSS pour le styling
- Zustand pour le state management
- React Query (TanStack Query) pour les appels API + cache
- react-dropzone pour le drag & drop
- Composants fonctionnels uniquement (pas de classes)
- Internationalisation : français par défaut, prévoir i18n
- Responsive : desktop-first mais utilisable sur tablette
- Le drag & drop doit accepter :
  - Fichiers individuels (PDF, DOCX, PPTX, PPSX, XLSX)
  - Dossiers entiers (via webkitdirectory)
  - Archives ZIP
  - Multi-fichiers simultanés
- Feedback visuel immédiat sur le drag & drop (bordure animée, icône, texte d'aide)
- Barre de progression pour upload + extraction

### Conventions générales

- Noms de variables/fonctions en anglais dans le code
- Commentaires en français
- Commits conventionnels : `feat:`, `fix:`, `refactor:`, `docs:`
- Un fichier = une responsabilité
- Tests : pytest pour le backend, vitest pour le frontend
- `.env` pour toute configuration (jamais de valeurs en dur)

---

## 🚀 Phases de développement

### Phase 1 — Fondation (semaines 1-3)
1. `docker-compose.yml` avec PostgreSQL/pgvector
2. Backend FastAPI : squelette + modèles DB + migrations
3. Service Tika : client + tests avec chaque format
4. Service Ollama : client LLM + client embeddings
5. Pipeline d'extraction complet (fichier → texte → métadonnées → embeddings)
6. API upload avec support drag & drop (multipart)
7. Workflow n8n : surveillance de dossiers

### Phase 2 — Interface & Rapports (semaines 4-6)
1. Frontend : setup Vite + React + Tailwind
2. Composant DropZone (drag & drop fichiers/dossiers/ZIP)
3. Navigateur de fichiers avec arborescence
4. Éditeur de prompt + sélecteur de modèle
5. Pipeline de génération de rapports (API + streaming SSE)
6. Prévisualisation + export PDF/DOCX
7. Gestion des templates (upload + remplissage)

### Phase 3 — GED (semaines 7-9)
1. Recherche hybride (full-text + vectorielle)
2. Interface GED : recherche + filtres + grille
3. Fiche document avec métadonnées éditables
4. Classement automatique à l'import
5. Gestion des versions
6. Détection de doublons

### Phase 4 — Polish (semaine 10)
1. Page paramètres
2. Gestion d'erreurs robuste
3. Tests end-to-end
4. Documentation utilisateur
5. Optimisations performances

---

## 🐛 Points d'attention / Pièges connus

- **Tika et les ZIP** : Tika peut extraire le contenu de chaque fichier dans un ZIP via `/rmeta`. Utiliser cet endpoint pour les ZIP.
- **Ollama et la mémoire** : Mixtral (26 GB) est gourmand. Ne pas lancer d'embeddings pendant une génération de rapport. Prévoir une file d'attente (table `jobs`).
- **Taille du contexte** : Mixtral supporte 32k tokens. Si les documents combinés dépassent, il faut tronquer intelligemment ou utiliser les chunks les plus pertinents (recherche sémantique dans les embeddings).
- **pgvector dimensions** : Vérifier la dimension exacte des embeddings de qwen3-embedding:8b (probablement 4096). Adapter le schéma si différent.
- **Drag & drop de dossiers** : Le drag & drop de dossiers dans un navigateur nécessite l'API `DataTransferItem.webkitGetAsEntry()`. Ce n'est pas standard mais supporté par Chrome, Edge, Firefox. Prévoir un fallback avec `<input webkitdirectory>`.
- **Encodage** : Tika gère bien l'encodage mais vérifier les fichiers XLSX avec du contenu non-UTF8.
- **Templates DOCX** : Utiliser `docxtpl` (basé sur Jinja2). Les champs dans le template doivent être marqués avec `{{ champ }}`. Le LLM doit retourner un JSON avec les valeurs de chaque champ.
