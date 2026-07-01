# Plan — Connecteur HuggingFace (identifiants dans Paramètres)

> Consigné le 01/07/2026, à la demande de l'utilisateur : « ajoute dans les paramètres la
> possibilité d'ajouter un token API HuggingFace et/ou identifiant / mot de passe ».

## ❓ Question / besoin

Pouvoir **enregistrer des identifiants HuggingFace** dans Matothèque (Paramètres) pour, à terme,
**récupérer des modèles gated/privés** (ex. certains abliterated, embeddings, vision) et
préparer de futures intégrations HF (recherche/téléchargement de modèles depuis l'app).

Format demandé : **token API** (recommandé par HF) **et/ou** **identifiant + mot de passe**.

## ✅ Décision / réponse

Stocker **3 clés de config chiffrées** (même mécanisme que le token BookStack — Fernet, masquage
en lecture) :

| Clé | Type | Rôle |
|---|---|---|
| `huggingface_token` | secret (chiffré) | **Jeton d'accès HF** (`hf_...`) — moyen **recommandé** |
| `huggingface_user` | texte | Identifiant HF (optionnel, legacy) |
| `huggingface_password` | secret (chiffré) | Mot de passe HF (optionnel, legacy) |

- Chiffrement : réutilise `crypto` (Fernet) via `runtime_config.SECRET_KEYS` (comme
  `bookstack_token_secret`). Jamais renvoyé en clair par l'API (`_mask_secrets`).
- Édition : section **« HuggingFace »** dans Paramètres (comme BookStack), `PUT /system/config`.

## ⚠️ Nuance importante (où le token est *réellement* utilisé)

- **Ollama tourne sur l'HÔTE**, pas dans la pile Matothèque. Un `ollama pull hf.co/...` gated lit
  `HF_TOKEN` **de l'environnement d'Ollama sur l'hôte**, pas la config Matothèque.
  → Stocker le token dans Matothèque **ne suffit pas** à lui seul pour un pull gated côté Ollama.
- **Ce que le stockage apporte dès maintenant** : un **coffre central chiffré** pour l'identifiant
  HF (plus besoin de le retaper), réutilisable par les futures features **côté backend** :
  - recherche/consultation de modèles via l'API HF (`https://huggingface.co/api/...` avec
    `Authorization: Bearer <token>`) ;
  - téléchargement direct de fichiers modèles (GGUF) par le backend ;
  - éventuel **helper « pousser le token vers Ollama »** (écrire `HF_TOKEN` pour Ollama) — à
    étudier selon l'install (hôte Windows).

## Plan d'action

1. **Backend**
   - `runtime_config._DEFAULTS` : `huggingface_token`, `huggingface_user`, `huggingface_password`
     (défauts `""`). `SECRET_KEYS` += `huggingface_token`, `huggingface_password`.
   - `routers/system.py` `ConfigUpdate` : 3 champs optionnels. (`_mask_secrets` couvre déjà les
     `SECRET_KEYS`.)
2. **Frontend**
   - Type `ConfigUpdate` + state `config` : 3 champs.
   - `getConfig` : mappe `huggingface_token`→(masqué, champ vide), `huggingface_user`→valeur,
     `huggingface_password`→(masqué, champ vide).
   - **Section « HuggingFace »** (carte repliable) : Token (password), Identifiant (text),
     Mot de passe (password), bouton Enregistrer.
3. **Test** : PUT puis GET → vérifier persistance + **masquage** des secrets.
4. **Plus tard (hors périmètre immédiat)** : bouton « Tester » (appel `GET /api/whoami-v2` HF avec
   le token) ; helper de synchro `HF_TOKEN` vers Ollama ; UI de recherche/pull de modèles HF.

## Statut

- **À implémenter maintenant** : stockage chiffré + UI (points 1–3).
- Le « vrai » usage (pull gated côté Ollama) dépend de l'hôte → tracé comme suite (point 4).
