# Rapport d'audit — Matothèque v1.113.0 (28/09/2026)

Plan : [plan-audit-2026-09.md](plan-audit-2026-09.md). Cinq audits en lecture seule (sécurité,
backend FastAPI, frontend React, base PostgreSQL, erreurs silencieuses), puis **chaque constat
HAUT relu dans le code** avant d'être retenu. Les gravités ci-dessous sont celles **après**
relecture : plusieurs ont été recalibrées (motif indiqué).

**Aucun constat critique ne tient** après relecture — ni perte de données, ni fuite de document
hors du réseau. Les règles « contexte HTTP » (aucun `navigator.clipboard` / `crypto.randomUUID`
en direct) et « 100 % local » (toute sortie confirmée, aucune ne transporte de document) sont
**respectées partout**.

## HAUTE — 9

| # | Constat | Où | Scénario |
|---|---|---|---|
| H1 ✅ v1.114.0 | **Filtres catégorie/extension appliqués après la troncature à 200** | `routers/search.py:347`, `394-402` | « facture » filtré sur une catégorie : tout document de cette catégorie classé au-delà du 200ᵉ disparaît, sans aucun signal. |
| H2 ✅ v1.114.0 | **Recherche sémantique : Ollama indisponible = « 0 résultat »** | `routers/search.py:216-219` | Ollama occupé ou arrêté → `_embed_query` rend `None` → 0 résultat, sans champ qui dise que le moteur n'a pas tourné. |
| H3 ✅ v1.115.0 | **Barre de progression d'indexation d'une source figée** (dict de process) | `routers/sources.py:35`, `454-470` ; `services/job_handlers.py:182` | Le process API pose `en_cours`, le worker avance dans SON dict : la barre reste sur « énumération 0/0 » jusqu'au redémarrage, ou vide selon le process qui répond. |
| H4 | **Config divergente entre les 2 process uvicorn** | `services/runtime_config.py:197-205` ; `routers/system.py` | Changer l'URL d'Ollama : un process sur deux garde l'ancienne jusqu'au redémarrage (seuls `connectors.py` et le worker rechargent). |
| H5 | **Synchro SMB : échecs par fichier invisibles** | `services/sync_service.py:371` ; `SourcesManager.tsx:38-52` | 15 fichiers sur 50 échouent (coupure réseau) → l'écran affiche « +50 nouveau(x) ». Rattrapés à la synchro suivante, mais rien ne le dit. |
| H6 | **Scans disque synchrones dans l'API** | `routers/duplicates.py:66` ; `routers/folders.py:85` | Scan de doublons sur un gros volume NAS : l'event loop du process est gelée, flux SSE des rapports compris. |
| H7 | **Synology : TLS non vérifié + mot de passe dans l'URL** | `services/connectors/synology.py:88-198` (`verify=False` ×5), `103-106` | MITM sur le LAN ou via le relais QuickConnect → mot de passe DSM et `sid` interceptés. |
| H8 | **« Effacer » ne coupe pas la génération en cours** | `stores/reportStore.ts:104`, `155` | On efface un rapport qui s'écrit encore : l'ancien flux SSE continue, le texte effacé réapparaît puis devient le rapport final. |
| H9 | **Course entre requêtes sur le filtre rapide de la GED** | `components/ged/AllDocumentsView.tsx:123-150` | Clic catégorie A puis B : si A répond après B, la grille montre A sous le filtre B. |

## MOYENNE — 12

| # | Constat | Où | Note |
|---|---|---|---|
| M1 | Traversée de chemin (`..`) sur l'index/browse des sources locales | `routers/sources.py:99-100`, `615` ; `sync_service.py:68`, `321` | *Recalibré (annoncé CRITIQUE)* : réel, mais `POST /api/sources` accepte déjà n'importe quel `chemin_base` sans auth — le cloisonnement contourné n'existe pas encore. Défense en profondeur ; modèle correct : `duplicate_service.quarantine()`. |
| M2 | HTML du wiki injecté sans nettoyage | `pages/WikiBookReader.tsx:93` | *Recalibré (annoncé CRITIQUE)* : exploitable seulement si BookStack a `ALLOW_CONTENT_SCRIPTS=true` (retire les scripts par défaut). DOMPurify en défense. |
| M3 | Scan de doublons : racine absente = « Aucun doublon 🎉 » | `services/duplicate_service.py:65-67` ; `DuplicatesPage.tsx:97`, `335` | *Recalibré (annoncé CRITIQUE)* : trompeur, mais rien n'est supprimé. |
| M4 | CHECK `documents`/`jobs` supprimés puis recréés à chaque démarrage | `database.py:95-105`, `154-158` | *Recalibré (annoncé HAUTE)* : revalidation sous verrou exclusif, ×3 process ; bon marché au volume actuel. Modèle correct : le bloc `tsv` qui teste le catalogue d'abord. |
| M5 | `GET /api/jobs` sans index sur `created_at`, sondé toutes les 2,5 s par onglet | `routers/jobs.py:62` ; `JobsIndicator.tsx:72` | *Recalibré (annoncé HAUTE)* : croît avec l'historique, jamais purgé automatiquement. |
| M6 | Recherche : `texte_extrait` / `tika_metadata` chargés en entier, deux fois | `routers/search.py:168`, `312` | *Recalibré (annoncé HAUTE)* : performance, pas justesse. `defer()` comme la liste. |
| M7 | N+1 dans le calcul de purge des doublons | `routers/documents.py:997-1020` | Une requête par groupe, texte intégral chargé. |
| M8 | Upload sans plafond de taille ni de nombre | `routers/upload.py:120-184` | Saturation disque possible ; `index_taille_max_mo` ne couvre que SMB. |
| M9 | SSRF faible sur « Vérifier les liens » (URL libre) | `routers/system.py:270-320` | Sonde de services internes ; restreindre au catalogue. |
| M10 | Suivi d'upload : polling qui échoue en silence puis s'arrête | `stores/documentStore.ts:137-154` | Badge « en cours » à vie après une coupure. |
| M11 | Rapport en échec exportable comme valide | `stores/reportStore.ts:106-129` ; `ResultPanel.tsx:31-35` | `data.erreur` parsé mais jamais lu. |
| M12 | Embedding vide stocké en `NULL` sans erreur | `services/embedding_service.py:71-74` | Chunk invisible à la recherche, document marqué enrichi. |

## BASSE — 7

- Préfixe de 8 caractères du secret OAuth Google journalisé — `connectors/gdrive.py:222` (*annoncé HAUTE* : pour `GOCSPX-…`, c'est le préfixe fixe + 1 caractère ; mais c'est une entorse nette à la règle « jamais en clair dans les logs », et la correction tient en une ligne).
- Chemin SMB transmis sans normalisation — `routers/sources.py:627` (borné par le partage côté NAS).
- `GET /api/folders/browse` liste tout le système de fichiers du backend — `routers/folders.py:269-316` (par conception).
- Statut antivirus « Chargement… » à vie sur erreur — `SettingsPage.tsx:367`.
- Dossier surveillé inaccessible : scan sauté sans trace dans l'UI — `services/folder_watcher.py:153-156`.
- Tâche `_matryoshka_scheduler` sans référence ni arrêt propre — `services/job_worker.py:706`.
- Deux implémentations de la recherche hybride, une seule branchée — `services/search_service.py` (seuls les tests l'importent).

Et un chantier de fond : `SettingsPage.tsx` (2 871 lignes) — à découper au fil des modifications.

## Vérifié sain

Zip slip (pas d'extraction locale), noms de fichiers d'upload/templates, quarantaine des
doublons, téléchargement de sauvegardes, masquage des secrets dans les API, injection SQL,
toutes les sorties Internet (confirmées, sans donnée de document), API de contexte sécurisé,
`rel="noopener"`, markdown IA sans HTML brut, flux SSE relu en base, pysmb en thread, CORS,
pagination des documents, timeouts httpx, antivirus (`NON_SCANNE` ≠ sain), enrichissement IA
(pas d'« enrichi à vide »), comparatif (`Échec de l'IA` ≠ `N/A`), migrations `ADD COLUMN`, index
HNSW en `CONCURRENTLY`, clés étrangères, contraintes d'unicité.

## Ordre de correction proposé

1. **Justesse de la recherche** — H1, H2 (le cœur de la GED, et la famille « vide qui a l'air complet »).
2. **État par process** — H3, H4 (la famille déjà payée en v1.110/1.111).
3. **Échecs visibles** — H5, M3, M10, M11, M12.
4. **Gel de l'API** — H6.
5. **Sécurité** — H7, puis M1, M2, M9, secret OAuth.
6. **Frontend** — H8, H9.
7. **Base** — M4, M5, M6, M7.
