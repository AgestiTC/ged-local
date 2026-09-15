# L'IA locale sur PC-GAME — matériel, réglages, mesures

> **Statut : état des lieux mesuré le 15/09/2026**, sur la machine qui héberge Ollama.
> Public : qui règle ou dépanne l'IA de Matothèque. Voir aussi
> [passerelle-ia-locale.md](passerelle-ia-locale.md) (mutualisation entre projets).

Matothèque ne parle qu'à **Ollama**, hébergé sur **PC-GAME** (`192.168.42.130:11434`, publié en
`https://ollama.tclement.fr`). Ce serveur est **partagé** : JARVIS (Home Assistant) et d'autres
clients s'en servent aussi. Tout ce qui suit décrit cette machine, pas le LXC de Matothèque.

## Le matériel, et ce qu'il autorise

| Élément | Valeur |
|---|---|
| GPU | RTX 4080 SUPER — **16 Go de VRAM** (Ada : pas de NVFP4, réservé aux RTX 50) |
| VRAM réellement libre | ≈ 10-11 Go — le bureau Windows en occupe ~5 (navigateurs, Docker, VS Code…) |
| CPU | i9-14900KF (8 P-cores + 16 E-cores) |
| RAM | 64 Go DDR5 (kit 6000, **tourne à 4800** tant que XMP n'est pas activé au BIOS) |

**Ce qui tient, ce qui ne tient pas :**

- ✅ un modèle **dense ≤ 14B** en Q4_K_M → 100 % GPU ;
- ✅ un **MoE** type 35B-A3B en Q4_K_M → déborde, mais reste rapide : seuls ~3B de paramètres
  travaillent par token ;
- ❌ un **dense de 27B et plus** (~16,5 Gio de poids) → ne rentre pas, quelle que soit la version ;
- ❌ du **Q8_0 sur un gros modèle** → double la taille pour un gain de qualité marginal.

## Réglages Ollama (variables d'environnement, poste Windows)

```text
OLLAMA_FLASH_ATTENTION    = 1        # requis pour quantifier le cache KV
OLLAMA_KV_CACHE_TYPE      = q8_0     # cache KV ~2x plus léger
OLLAMA_CONTEXT_LENGTH     = 16384    # défaut d'Ollama = 4096 : trop court pour un document
OLLAMA_MAX_LOADED_MODELS  = 2        # surtout PAS 1 (voir « Pièges »)
OLLAMA_NUM_PARALLEL       = 1        # chaque slot parallèle duplique le cache KV
OLLAMA_KEEP_ALIVE         = 30m
OLLAMA_HOST               = 0.0.0.0:11434
```

Effet mesuré sur `ministral-3:14b` : contexte porté de 4096 à 16384 (**×4**) pour seulement
**+0,4 Go** d'empreinte, en restant à 100 % sur GPU.

## Mesures du 15/09/2026

| Modèle | Quant | Taille | Génération | Répartition |
|---|---|---|---|---|
| `ministral-3:14b` | Q4_K_M | 9,1 Go | **72,3 tok/s** | 100 % GPU |
| `qwen3.6-uncensored:35b-a3b-q4` (MoE) | Q4_K_M | 22,1 Go | **25,3 tok/s** | 37 % CPU / 63 % GPU |
| *le même modèle en Q8_0* | Q8_0 | 43 Go | 15,7 tok/s | offload massif |

**Q8_0 → Q4_K_M sur un MoE : +61 % de débit**, pour une perte de qualité faible — seule une
fraction des poids travaille à chaque token, donc l'offload des experts coûte peu.

## Les modèles, et qui en dépend

| Modèle | Rôle dans Matothèque | À ne pas supprimer |
|---|---|---|
| `ministral-3:14b` | rapports (bonne écriture FR), vision, tools | — |
| `llama3.1:latest` | modèle par défaut : chat, enrichissement, résumés | ⚠️ **épinglé** (`keep_alive: -1`) pour **JARVIS** |
| `qwen2.5vl:7b` | `vision_model` — description d'images / OCR de secours | ⚠️ oui |
| `qwen3-embedding:8b` | embeddings (recherche sémantique) | ⚠️ oui |
| `nomic-embed-text` | **repli** des embeddings | ⚠️ oui |
| `qwen3.6-uncensored:35b-a3b-q4` | non câblé dans Matothèque (usage direct) | — |

> **Leçon du 15/09** : `qwen2.5vl:7b` a été supprimé lors d'un ménage de modèles « redondants ».
> La vision de Matothèque est tombée **sans aucun message** : la configuration pointait toujours
> vers un modèle absent. D'où le bouton **Analyser** (§ ci-dessous), qui rend ce cas visible.

## Pièges vérifiés sur cette machine

| Piège | Symptôme | Ce qu'il faut faire |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS=1` avec un modèle épinglé | toute requête vers un **autre** modèle attend indéfiniment : l'éviction du modèle épinglé n'arrive jamais | garder **2** |
| Variables changées, Ollama relancé depuis un shell | `ollama ps` affiche encore l'ancien contexte (4096) | injecter les variables dans la session **avant** de relancer, ou rouvrir la session Windows |
| WinNAT (Docker Desktop + WSL2) | Ollama ne démarre plus : `bind: … forbidden by its access permissions` | exclusion persistante du port 11434 (déjà posée, ne pas la retirer) |
| Import d'un GGUF sans template | réponses dégradées, arrêts hasardeux, **invisible dans un test de débit** | reprendre `RENDERER`/`PARSER` du modèle officiel de la même famille |
| Modèle importé en Q8_0 | lenteur inexpliquée | prendre la variante Q4_K_M |

**Importer un GGUF correctement** (exemple réel, avec projecteur vision) :

```dockerfile
FROM <modele>-Q4_K_M.gguf
FROM mmproj-<modele>-f16.gguf
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
```

Après `ollama create`, vérifier avec `ollama show <modèle>` : la **quantisation**, `vision` dans
*Capabilities*, la section *Projector*, et surtout que `ollama show --modelfile` ne contient pas
seulement `TEMPLATE {{ .Prompt }}`. Penser aussi aux **blobs orphelins** : une conversion a laissé
19,71 Go non référencés dans `~/.ollama/models/blobs`.

## Le contrôler depuis Matothèque

*Paramètres › Demandes Mise à jour internet › **Analyse IA de l'installation*** (v1.107.0) :
constats classés (usage pointant vers un modèle absent, import sans template, quantisation trop
lourde, débordement de VRAM, contexte à 4096…), synthèse rédigée par l'IA locale, et prompt à
copier dans une IA web pour ce qui demande Internet. **Rien ne sort du réseau** : seule l'API
d'Ollama est interrogée.

*Paramètres › Services & modèles IA › **Mettre à jour le tableau*** recalcule le tableau
comparatif et les recommandations 💡 par usage depuis les modèles réellement installés.

## Reste à faire sur la machine

- **Activer XMP au BIOS** (DDR5 4800 → 6000) : ~+25 % de bande passante mémoire, donc un gain
  direct sur les couches du MoE déportées en CPU. Tester la stabilité ensuite (MemTest86).
- **NVIDIA — *CUDA · Sysmem Fallback Policy*** → « Prefer No Sysmem Fallback » pour `ollama.exe` :
  sinon, un dépassement de VRAM bascule silencieusement en RAM système et tout s'écroule sans
  message.
- **Identifier les clients** encore inconnus d'Ollama (192.168.42.202, .231, conteneurs Docker en
  172.19.0.x) — indispensable avant tout nouveau ménage de modèles.
