# Étude de faisabilité — Publier un tuto sur le wiki BookStack depuis Matothèque

**Date :** 2026-06-29
**Périmètre :** ajouter à Matothèque (projet GED-LOCAL) une fonction « Créer / publier
un tuto dans le wiki BookStack ».
**Verdict :** ✅ **Faisable**, effort estimé **2 à 3 jours** pour un MVP testable.

---

## 1. Contexte technique

| Élément | État |
|---|---|
| Wiki cible | BookStack, **API REST** disponible (`https://wiki.agesti.fr/api`) |
| Auth API | header `Authorization: Token <id>:<secret>` (jeton lié à un utilisateur) |
| Création de contenu | `POST /api/books`, `/api/chapters`, `/api/pages` (corps `{book_id|chapter_id, name, markdown}`) |
| Format | **markdown accepté directement** (le wiki est 100 % markdown) |
| Matothèque backend | FastAPI/Python async, Postgres + SQLAlchemy 2.0, structlog |
| Matothèque frontend | React 18 + Vite + TypeScript + axios + zustand + Tailwind |

L'API BookStack a été **testée en conditions réelles** (lecture + écriture de pages
existantes) : le canal est opérationnel.

## 2. Pourquoi c'est simple : la plomberie existe déjà

Matothèque intègre déjà plusieurs services externes selon un pattern réutilisable
tel quel :

| Besoin | Déjà présent | Fichier de référence |
|---|---|---|
| Client HTTP async + retry | `httpx` 0.27 + `tenacity` | `services/tika_service.py`, `services/ollama_service.py` |
| Stockage chiffré d'un secret | Fernet | `services/crypto.py` (utilisé pour mots de passe SMB) |
| Config modifiable à chaud (DB > env) | `runtime_config.effective()` | `services/runtime_config.py` |
| Endpoint + validation | Pydantic + `APIRouter` | `routers/sources.py`, `routers/export.py`, `routers/system.py` |
| Test de connectivité d'un service | `POST /api/system/test/{service}` | `routers/system.py` |
| UI (bouton → modale → appel API) | axios + composants | `frontend/src/api/index.ts`, `components/common/*` |

➡️ Aucune nouvelle dépendance, aucune nouvelle brique d'architecture.

## 3. Conception proposée

### Backend
1. **`services/bookstack_service.py`** (NOUVEAU) — calqué sur `tika_service.py` :
   - `check_health()` → `GET /api/books?count=1`
   - `list_books()` / `list_chapters()` → pour alimenter le sélecteur de cible
   - `create_page(book_id|chapter_id, name, markdown)` → `POST /api/pages`
   - `update_page(id, markdown)` → `PUT /api/pages/{id}` (si republication)
2. **`routers/bookstack.py`** (NOUVEAU) :
   - `GET /bookstack/targets` → livres/chapitres disponibles
   - `POST /bookstack/publish` → publie un document/rapport en page
3. **Config** : ajouter `bookstack_url`, `bookstack_token_id`, `bookstack_token_secret`
   dans `config.py` + `runtime_config._DEFAULTS` ; **secret chiffré Fernet** en base.
4. **`routers/system.py`** : ajouter le cas `bookstack` au test de connectivité.
5. **`main.py`** : monter le router.

### Frontend
1. `frontend/src/api/index.ts` : `bookstackApi.getTargets()` / `.publish()`.
2. Composant `PublishBookStackModal.tsx` : choix livre/chapitre + titre + aperçu.
3. Bouton **« Publier sur le wiki »** sur la fiche document / l'écran rapport.
4. Section **BookStack** dans `SettingsPage.tsx` (URL + jeton + bouton « Tester »).

### Flux fonctionnel (MVP)
```
Document indexé / Rapport généré (markdown)
        │  bouton "Publier sur le wiki"
        ▼
POST /api/bookstack/publish {document_id|markdown, book_id|chapter_id, title}
        │  bookstack_service.create_page(...)
        ▼
POST https://wiki.agesti.fr/api/pages  → page créée
        ▼
Retour { page_url } affiché (lien cliquable) + toast succès
```

## 4. Points d'attention / risques

| Point | Recommandation |
|---|---|
| Jeton API **lié à un utilisateur** → la page créée lui appartient | Créer un **compte de service** BookStack dédié (ex. `matotheque-bot`) et son jeton |
| Expiration du jeton (403 "expired") | Date d'expiration lointaine + test de connectivité dans Settings |
| Choix de la cible (livre/chapitre) | Endpoint `GET /bookstack/targets` pour éviter les ID en dur |
| Matothèque **sans authentification** | Garder l'accès réseau restreint (déjà le cas) ; le secret reste chiffré côté serveur |
| Qualité du markdown publié | MVP = texte/rapport tel quel ; v2 = gabarit « Modèle de tuto » du wiki |
| Doublons (republier) | Stocker l'`external_id` de la page (option : petite table `publications`) |

## 5. Plan / estimation

| Phase | Tâches | Charge |
|---|---|---|
| Backend cœur | service + router + config | 0,5 j |
| Backend intégration | test connectivité, gestion erreurs, logs | 0,5 j |
| Frontend | modale + appel API + bouton | 1,0 j |
| Admin config | section Settings + test | 0,5 j |
| Tests E2E & finitions | cas limites, doc | 0,5 j |
| **Total** | | **~3 j** |

## 6. Conclusion

L'intégration est **directe** : elle réutilise intégralement les patterns existants
(httpx/tenacity, crypto Fernet, runtime_config, routers, axios). Le principal choix
produit n'est pas technique mais organisationnel : **compte de service dédié** côté
wiki et **gabarit de page** (réutiliser la page « Modèle de tuto » nouvellement créée
pour homogénéiser les tutos publiés depuis Matothèque).

---

## 7. Implémentation réalisée (MVP)

Statut : **fait et vérifié** — backend importé sans erreur + test de connexion live
OK (`POST /api/system/test/bookstack` → `ok: true`) ; frontend `tsc && vite build` OK.

### Backend
- **`services/bookstack_service.py`** (nouveau) — client async : `check_health`,
  `list_books`, `list_chapters`, `create_page`, `update_page`, `page_url`. Secret
  déchiffré (Fernet) à la lecture.
- **`routers/bookstack.py`** (nouveau) — `GET /api/bookstack/targets`,
  `POST /api/bookstack/publish` (markdown direct **ou** `document_id`).
- **`config.py`** — `bookstack_url`, `bookstack_token_id`, `bookstack_token_secret`,
  `bookstack_timeout_ms` (+ propriété `bookstack_timeout`).
- **`services/runtime_config.py`** — clés ajoutées à `_DEFAULTS` + ensemble `SECRET_KEYS`.
- **`routers/system.py`** — `ConfigUpdate` étendu ; secret **chiffré à l'écriture**,
  **masqué à la lecture** ; `bookstack` ajouté au statut et au test de connexion.
- **`main.py`** — router monté.

### Frontend
- **`api/index.ts`** — `bookstackApi` (`targets`, `publish`) + types ; `ConfigUpdate`,
  `SystemConfig`, `ServicesStatus` étendus ; `testService` accepte `bookstack`.
- **`components/common/PublishBookStackModal.tsx`** (nouveau) — modale de publication.
- **`pages/SettingsPage.tsx`** — section **« Wiki BookStack »** (URL + Token ID +
  Secret + Tester + Enregistrer).
- **`components/reports/ReportPreview.tsx`** — bouton **« Wiki »** → publie le rapport
  généré comme tuto.

### Reste à faire (hors MVP)
- Créer un **compte de service** BookStack dédié + saisir le jeton dans Réglages.
- Optionnel : table `publications` (traçabilité/republication) ; bouton « Publier »
  aussi depuis la fiche document.
