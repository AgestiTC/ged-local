# Transcription audio — mise en route

Matothèque peut **transcrire les fichiers audio** (dictaphone **Plaud/openplaud**, mémos vocaux,
enregistrements de réunion…) pour les rendre **recherchables** dans la GED, exactement comme un
document texte : la parole est convertie en texte, puis **enrichie** (catégorie, tags, résumé) et
**vectorisée** (recherche sémantique) par le pipeline habituel.

100 % local : l'audio n'est envoyé qu'à **ton** serveur de transcription — aucun tiers.

## 1. Un serveur de transcription (compatible OpenAI)

Il faut un serveur exposant l'API **`POST /v1/audio/transcriptions`** (le standard OpenAI). Options
auto-hébergeables courantes :

- **faster-whisper-server / Speaches** (recommandé, léger, GPU/CPU) —
  `docker run -p 8001:8000 fedirz/faster-whisper-server:latest-cuda` (ou `-cpu`).
- **LocalAI** (multi-modèles) — expose la même route.
- **whisper.cpp** en mode serveur, **vLLM**, etc.

Modèles Whisper conseillés (français) : `Systran/faster-whisper-large-v3` (qualité) ou
`Systran/faster-whisper-medium` (plus rapide).

## 2. Configurer dans Matothèque

**Paramètres → Sources & indexation → Transcription audio (parole → texte)** :

| Champ | Rôle | Exemple |
|-------|------|---------|
| **URL serveur** | Base du serveur (vide = désactivé) | `http://localhost:8001` |
| **Modèle** | Modèle de transcription | `Systran/faster-whisper-large-v3` |
| **Langue** | Indice de langue (améliore la précision) | `fr` |
| **Clé API** | Facultative (souvent inutile en local) | — |

Clique **« Tester »** (pastille verte = joignable) puis **« Enregistrer »**.

## 3. Utilisation

Une fois activé, **tout fichier audio** indexé (upload, NAS/SMB, WebDAV, Google Drive…) est
**transcrit automatiquement** au lieu d'être simplement catalogué :

1. Le fichier audio est rapatrié puis envoyé au serveur de transcription.
2. Le texte obtenu devient le **texte du document** → enrichissement IA + embeddings.
3. Il apparaît dans la **GED**, **recherchable** en plein texte **et** en sémantique.

> Sans serveur configuré, les fichiers audio restent **catalogués** (nom/taille) sans texte,
> comme les autres médias — aucun changement de comportement.

## Notes

- **Formats** : mp3, wav, flac, aac, ogg, m4a, opus, wma, aiff, alac, amr, 3ga.
- **Vidéo** : non transcrite ici (piste audio non extraite) — à envisager plus tard.
- **Gros fichiers** : au-delà du plafond `index_taille_max_mo`, l'audio n'est pas rapatrié
  (référencé seulement) — augmente le plafond si besoin pour de longues dictées.
