# Plan — Routage dynamique du LLM par usage

> Livré le 01/07/2026. Répond à : « le choix du LLM peut-il être choisi automatiquement selon
> l'usage ? » + « avec modification par l'utilisateur » + « que le LLM défini dans les paramètres
> soit pris en compte selon l'usage et le rendu attendu ».

## Principe

Chaque **tâche IA** de Matothèque a un **usage** ; l'utilisateur peut **choisir le modèle** pour
chaque usage (Paramètres → Services & modèles IA → « Modèle par usage »). Le backend **route**
dynamiquement chaque appel vers le modèle configuré, sinon le **modèle par défaut**.

## Mécanisme (100% local)

- Config : clé **`usage_models`** = JSON `{usage: modele}` (persistée en base, éditable UI).
- `runtime_config.usage_model(usage)` → override, ou `None`.
- `runtime_config.model_for(usage)` = **override par usage > `default_model` (runtime)**.
  Remplace `settings.ollama_model_default` (variable d'env) → évite d'appeler un modèle **supprimé**
  (ex. mixtral retiré) et rend le choix **effectif**.

## Usages câblés

| Usage (clé) | Tâche | Fichier |
|---|---|---|
| `rapport` | Génération rapport / template / comparatif / présentation | generate, report_generator, template_filler, compare, presentation_service |
| `enrichissement` | Catégorie/tags/résumé à l'indexation | extraction._enrich |
| `embeddings` | Recherche sémantique (vecteurs) | embedding_service |
| `vision` | OCR de secours / description d'image | extraction._ocr_fallback (> `vision_model`) |
| `resume_modele` | Résumé FR des modèles (catalogue HF) | routers/huggingface |

« Auto » (usage non défini) = **`default_model`**.

## UI

Paramètres → « Modèle par usage » : un **sélecteur éditable** par usage (liste des modèles
installés), + une **recommandation locale** (💡) issue de l'heuristique nom+taille. `Enregistrer`
persiste `usage_models`.

## Validation

Route `enrichissement → ministral-3:14b`, relance IA → logs `modele=ministral-3:14b`. ✅

## Suite possible

- Étendre à d'autres usages (assistant, diff de version).
- Auto-sélection « intelligente » (sans config) : router selon le type de doc / rendu attendu
  (rapide vs qualité) — aujourd'hui basé sur la reco + choix explicite.
