# Plan — Qualité de l'OCR (quelle approche ?)

> Consigné le 01/07/2026, à la demande de l'utilisateur. Fait suite à la **Phase 2**
> (OCR via glm-ocr) : le mécanisme marche, mais glm-ocr (2,2 Go) est **léger** → transcription
> **partielle** (ex. attestation scannée : seulement l'en-tête, ~101 caractères).

## ❓ La question

**Comment améliorer la qualité de l'OCR sur les documents scannés (PDF/images), tout en
restant 100 % local ?** Faut-il augmenter le DPI, changer le prompt, prendre un modèle vision
plus lourd, ou utiliser un vrai moteur OCR dédié ?

## ✅ La réponse recommandée (résumé)

**Activer Tesseract dans Tika (image `apache/tika:*-full` + langue `fra`) comme moteur OCR
principal**, et **garder glm-ocr/llava en secours** (images sans couche texte, description de
photos). C'est l'approche la plus **précise, rapide et standard** pour du document scanné, et
elle **réutilise l'infra existante** (Tika est déjà dans la pile et déjà appelé par
`analyze_existing` / `process_file`).

## Comparaison des options

| Option | Gain | Coût / risque | Verdict |
|---|---|---|---|
| **A. ↑ DPI** (150 → 300) sur la rastérisation | Un peu plus net pour glm-ocr | Images base64 plus lourdes, inférence plus lente | Palliatif, insuffisant seul |
| **B. Prompt tuning** (« transcris TOUT, ligne par ligne, jusqu'en bas ») | glm-ocr moins « paresseux » | Résultat non garanti (modèle léger) | Palliatif |
| **C. Tesseract via Tika** (`apache/tika:X-full`, `fra+eng`) | **OCR dédié, précis, multilingue, rapide**, zéro code custom (Tika OCRe pendant l'extraction) | Image Tika plus lourde ; config OCR ; packs langue | **★ Recommandé (principal)** |
| **D. Modèle vision plus lourd** (qwen2-vl / minicpm-v / llava:34b) | Meilleure lecture + compréhension | Pull Go, **lent**, RAM/VRAM | En complément ciblé, pas par défaut |
| **E. Hybride** = Tesseract (texte) + vision (photos/description) | Le meilleur des deux | Un peu plus de logique de routage | **★ Cible finale** |

## Pourquoi Tesseract (via Tika) plutôt que glm-ocr

- **Précision** : Tesseract est un moteur OCR dédié, bien meilleur que glm-ocr (LLM vision léger)
  sur du **texte de document** propre (attestations, formulaires, factures).
- **Vitesse** : OCR déterministe, pas d'inférence LLM par page.
- **Langue** : support **français** natif (pack `fra`).
- **Intégration** : **aucune nouvelle brique** — Tika OCRe automatiquement images et PDF scannés
  pendant l'extraction. `analyze_existing` (et `process_file`) récupèrent alors le texte
  **directement**, sans passer par la vision. glm-ocr devient un **fallback** (rare).
- **Robustesse** : gère les PDF corrompus / non-standard mieux que la rastérisation pymupdf.

## Plan d'action (proposé, à valider)

1. **Docker** : passer le service `tika` de `apache/tika:latest` à **`apache/tika:<version>-full`**
   (inclut Tesseract + parsers étendus). Vérifier la présence du pack langue **`fra`** (sinon
   image custom `FROM apache/tika:*-full` + `apt-get install tesseract-ocr-fra`).
2. **Config Tika OCR** (`storage/tika-config/`) : activer l'OCR (`TesseractOCRConfig`,
   `language=fra+eng`), autoriser l'OCR des **PDF images** (`PDFParser` `ocrStrategy=ocr_and_text`).
3. **Backend** : rien à changer sur le principe — l'appel `self.tika.extract_metadata` rend
   désormais le texte OCR. **Garder** `_ocr_fallback` (glm-ocr) **uniquement** si Tika ne rend
   toujours rien (images pures / photos), + option **llava** pour une **description** de l'image.
4. **Réglages** : timeouts Tika (OCR plus lent), plafond pages, DPI côté Tika.
5. **Test e2e** : ré-analyser `AttestationassurCBC.pdf` et comparer le texte (attendu : **beaucoup
   plus complet** que les 101 car. de glm-ocr) ; vérifier une facture et un formulaire scannés.

## Décision / statut

- **Recommandation** : **Option C → E** (Tesseract via Tika en principal, vision en secours).
- **Statut** : *à valider par l'utilisateur avant implémentation.* La Phase 2 actuelle (glm-ocr)
  reste fonctionnelle en attendant (fallback déjà en place).
- **Alternative rapide si on reste sur glm-ocr** : appliquer A (DPI 300) + B (prompt) — gain
  limité, mais sans changer l'image Tika.
