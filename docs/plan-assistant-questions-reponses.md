# Plan — Assistant « Questions → Réponse ancrée » (Q&R sur la GED)

> **Statut : à coder** (plan validé à confirmer). Demande utilisateur 2026-08-04.
> 100 % local (Ollama). Épic proposé : **E8 — Recherche conversationnelle / Q&R**.

**✅ Décisions verrouillées (2026-08-04)**

- **Approche = A** : extraction des faits **à la volée + cache** (MVP, aucun changement de schéma).
  Phase 2 = index structuré `faits_emploi` (persistance du cache) pour vitesse + frise.
- **Périmètre initial = emploi** (fiches de paie / contrats) : cas « où / combien de temps a travaillé X ».
- **Emplacement = sous-mode d'« Assistant IA »**, PAS un 3ᵉ onglet. La barre du haut reste
  `Simple | Assistant IA`. Sous « Assistant IA », un **sélecteur explicite** :
  **`📁 Constituer un dossier` | `❓ Poser une question`**. Choix explicite → **aucune auto-détection**
  d'intention (fragile), chaque sous-mode garde son propre rendu (groupes de fichiers vs carte-réponse).

## 1. Le besoin (mots de l'utilisateur)

Poser une **question en langage naturel** et obtenir une **réponse synthétique** + les documents
justificatifs, avec du **raisonnement sur les entités et les dates** :

- **Question directe** : « Où travaillait Thomas en juillet 2018 ? »
  → l'IA reconnaît « travaillait » ⇒ **fiche de paie / contrat**, cible la **période** (juillet 2018),
  et extrait le **nom de l'entreprise**.
- **Question inverse** : « Combien de temps Thomas a-t-il travaillé chez LApp Muller ? »
  → l'IA retrouve **la première et la dernière fiche de paie** de cet employeur → **durée**.
- **Zone de rendu textuelle** sous la barre `Simple | Assistant IA | …`, réponse simple du type :
  > **Chez [Entreprise], de [date] à [date]** — X documents trouvés.

## 2. Pourquoi l'existant ne suffit pas

| Mode actuel | Comportement | Limite pour une question |
|---|---|---|
| **Hybride / Sémantique** (`routers/search.py`) | recherche la **phrase brute** | le **gate de pertinence** (`services/pertinence.py`) rejette « Où travaillait Thomas… » : la question ne partage pas le vocabulaire des fiches de paie → **« Aucun document pertinent »** (cf. capture 1). |
| **Assistant IA** (`routers/assistant.py::/assistant/pieces`) | décompose un **besoin** en **pièces attendues** puis hybride chaque pièce | mauvaise **abstraction** : invente « CV de Thomas », « Dossier personnel »… et remonte des fichiers bruités (icônes, zips). **Ne répond pas** à la question (cf. capture 2). |

**Idée clé** : il ne faut PAS chercher la question ; il faut d'abord la **comprendre** (entités + dates +
type de pièce + intention), **récupérer par ces signaux** (vocabulaire documentaire), **extraire les faits
des documents trouvés**, puis **synthétiser** une réponse — en n'affirmant QUE ce qui est dans les documents.

## 3. Architecture cible (RAG agentique local)

```
Question NL
   │
   ▼  ① COMPRÉHENSION (LLM, format=json)  → intent structuré
   │      {intent, personnes[], organisations[], periode{debut,fin}, type_piece[], champ_cible}
   ▼  ② RÉCUPÉRATION CIBLÉE (pas la phrase brute)
   │      recherche par entités + type de pièce  +  FILTRE TEMPOREL  +  FILTRE par catégorie/tags
   ▼  ③ EXTRACTION PAR DOCUMENT (LLM, format=json, ancrage)
   │      pour chaque candidat (fiche de paie) → {employeur, salarie, periode_paie, net…}  [MIS EN CACHE]
   ▼  ④ RAISONNEMENT / AGRÉGATION (code pur, testable)
   │      employeur_a_date → paie couvrant la date ;  duree_emploi → min/max période par employeur
   ▼  ⑤ SYNTHÈSE (LLM, ancrée sur les FAITS uniquement)
          → {reponse_texte, faits[], documents[], confiance}   (« je ne sais pas » si insuffisant)
```

### ① Compréhension de la question
Prompt LLM (modèle rapide : `runtime_config.model_for("enrichissement")`, ex. llama3.1/ministral),
`format="json"`. Sortie normalisée :
```json
{
  "intent": "employeur_a_date | duree_emploi | liste_documents | fait_ponctuel",
  "personnes": ["Thomas"],
  "organisations": ["LApp Muller"],
  "periode": {"debut": "2018-07-01", "fin": "2018-07-31", "granularite": "mois"},
  "type_piece": ["fiche de paie", "contrat de travail"],
  "champ_cible": "employeur"
}
```
Le mapping sémantique (« travaillait » → fiche de paie ; « combien de temps » → durée = min/max période)
est porté par le prompt + une petite table de synonymes FR (métier → types de pièces).

### ② Récupération ciblée
On construit la requête à partir des **signaux**, jamais de la phrase :
- **Lexical + sémantique** sur `personnes` + `type_piece` (ex. « fiche de paie Thomas », « bulletin de
  salaire ») via `_recherche_fulltext` / `_recherche_semantique` (réutilise `routers/search.py`).
- **Filtre par type** : `metadonnees_ia.categorie` / `tags` (paie, bulletin, contrat).
- **Filtre TEMPOREL** — plusieurs sources de date, par ordre d'autorité :
  1. **période lue dans le texte** de la paie (autoritaire, extraite en ③) ;
  2. `metadonnees_ia.entites->'dates'` (JSONB) ;
  3. motif de date dans le **nom de fichier** (« 7-Juillet », « 2018 ») — parseur FR pur ;
  4. `tika_metadata` (created/modified) — dernier recours.
> Ce ciblage **contourne** le problème du gate : on cherche avec le **vocabulaire des documents**.

### ③ Extraction structurée par document (ancrage)
Pour chaque candidat retenu (top N, borné), un appel LLM `format="json"` lit `texte_extrait` et renvoie
les **faits** : `{employeur, salarie, periode_paie (AAAA-MM), net, brut}`. **Mise en cache** de ces
extractions (cf. §5 : table `faits_emploi`) → réponses instantanées ensuite + index réutilisable.

### ④ Raisonnement / agrégation (fonctions PURES, testables sans IA)
- `employeur_a_date(faits, date)` → la paie dont la période couvre la date → employeur.
- `duree_emploi(faits, employeur)` → `min(periode)`/`max(periode)` → durée (mois), nb de docs.
- Déduplication (même paie via plusieurs chemins), gestion des conflits, tolérance aux trous.

### ⑤ Synthèse ancrée
LLM reçoit **uniquement les faits agrégés** (pas le corpus brut) + consigne stricte : « réponds en
français, une phrase simple, **n'invente rien**, cite les documents, dis “je n'ai pas trouvé” si les faits
sont insuffisants ». Sortie : `{reponse, faits, documents, confiance}`.

## 4. UX (zone de réponse sous la barre de modes)

- **Nouveau mode** dans la barre GED : `Simple | Assistant IA | **Question**` (ou sous-onglet de
  l'Assistant : « Constituer un dossier » vs « Poser une question »).
- **Carte de réponse** juste sous la barre (comme demandé) :
  > 🧠 **Thomas travaillait chez _[Entreprise]_ en juillet 2018.**
  > _Basé sur 1 fiche de paie · confiance Élevée_
  >
  > **Chez [Entreprise] — du 07/2018 au 11/2018 · 5 fiches de paie** (question inverse)
- Sous la carte : **documents justificatifs** (réutilise les cartes Aperçu / Fiche / Télécharger existantes).
- **Repli honnête** : si aucun fait ancré → « Je n'ai pas trouvé de document permettant de répondre » +
  bouton « Voir les N documents approchants » (comme l'actuel « Afficher quand même »).
- (Option) **streaming SSE** de la réponse.

## 5. Données / pré-requis (le point dur = la PRÉCISION)

Deux stratégies, livrables en phases :

- **A — À la volée (MVP)** : extraction ③ au moment de la question, **mise en cache**. Aucun changement de
  schéma lourd. Plus lent au 1ᵉʳ appel, instantané ensuite.
- **B — Index structuré des faits d'emploi** : à l'enrichissement, extraire employeur + période des fiches
  de paie dans une table **`faits_emploi(document_id, salarie, employeur, periode_debut, periode_fin,
  net, source)`**. Rend la **question inverse** (durée, frise) triviale et rapide. Alimente aussi une
  future **timeline**. → Migration Alembic + hook dans `services/extraction.py` (uniquement sur
  catégorie = paie/bulletin).

Plan : **livrer A d'abord**, concevoir **B** comme phase 2 (le cache de A ⇒ B est une simple persistance).

## 6. Garde-fous (anti-hallucination)

- La réponse ne cite QUE des faits **présents dans un document** (grounding strict, sources affichées).
- **Confiance** explicite (Élevée / Moyenne / Faible) selon nb de docs concordants + qualité OCR.
- Jamais d'entreprise / de date inventée : si absente des documents → « je ne sais pas ».
- Journalisation `correlation_id` (audit) de la chaîne question → docs → réponse.

## 7. API

```
POST /api/assistant/question            # {question, model?} → {intent, reponse, faits[], documents[], confiance}
POST /api/assistant/question/stream      # (option) SSE de la réponse
```
Réutilise `OllamaService`, `routers/search.py` (récupération), `services/pertinence.py`.
Nouveau module suggéré : `services/qa_service.py` (compréhension, extraction, agrégation, synthèse) +
`services/qa_temporal.py` (parsing dates FR — fonctions pures) pour la testabilité.

## 8. Découpage en phases

- **Phase 1 — MVP « emploi »** (sans changement de schéma) : intents `employeur_a_date` + `duree_emploi`,
  récupération ciblée + extraction à la volée (cache mémoire LRU) + agrégation pure + synthèse ancrée ;
  carte de réponse + repli honnête. Tests des fonctions pures (temporel, agrégation) + mocks LLM.
- **Phase 2 — Index `faits_emploi`** : extraction à l'enrichissement (paies), migration Alembic, question
  inverse instantanée, **frise d'emploi** (timeline) dans la fiche personne.
- **Phase 3 — Généralisation** : autres intentions (montants « combien ai-je payé chez X en 2023 »,
  échéances, « quand… »), **questions de suivi** conversationnelles (contexte de la question précédente).

## 9. Risques & mitigations

| Risque | Mitigation |
|---|---|
| OCR pauvre sur paies scannées → extraction faible | s'appuyer sur nom de fichier + entités déjà extraites ; confiance basse assumée ; `qwen2.5vl` en secours |
| Hallucination LLM | grounding strict (faits only), sources obligatoires, « je ne sais pas » |
| Perf (plusieurs appels LLM/question) | candidats bornés (top N), **cache** des extractions, modèle rapide, parallélisme par doc |
| Corpus de test bruité (icônes/zips, cf. captures) | valider sur de **vraies fiches de paie** ; le bruit actuel ⇒ précision de la récupération = priorité |
| Ambiguïté d'entité (« Thomas » qui ?) | demander précision si plusieurs personnes ; désambiguïsation par organisation/période |

## 10. Fichiers pressentis

- **Backend** : `services/qa_service.py` (neuf), `services/qa_temporal.py` (neuf, pur),
  `routers/assistant.py` (+ endpoint `/assistant/question`), `services/extraction.py` (Phase 2 : hook
  faits_emploi), `models/fait_emploi.py` + migration Alembic (Phase 2),
  `tests/test_qa_temporal.py` / `tests/test_qa_aggregation.py` (neufs).
- **Frontend** : barre de modes GED (nouveau « Question »), `components/ged/AnswerCard.tsx` (neuf),
  `api/index.ts` (`assistantApi.question`), `pages/GEDPage.tsx` (zone de réponse + repli).

## 11. Questions de cadrage (à trancher avec l'utilisateur avant de coder)

- **A ou B d'abord ?** (extraction à la volée vs index structuré) → recommandation : **A (MVP)** pour
  valider l'UX vite, puis B pour la vitesse et la question inverse.
- **Périmètre initial** = fiches de paie / emploi uniquement, ou d'emblée plus large (factures, contrats) ?
- **Le mode** = nouvel onglet « Question » ou sous-mode de l'Assistant IA ?
