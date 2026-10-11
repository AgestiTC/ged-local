# Plan — Tableau comparatif « RAO » (analyse d'offres)

> Statut : **plan, non codé** (11/10/2026). Tuile *Créer › Tableau comparatif*.
> Cas d'usage déclencheur : comparer les candidats d'un appel d'offres (MA26041) et remplir la
> grille « Rao Criterestechniques » (Excel), avec un **résumé points forts / faibles par candidat**.

## 🔒 Règle absolue — confidentialité

Les offres des candidats sont **confidentielles** (secret des affaires, marché public en cours).

- **100 % local** : tout appel IA passe par `OllamaService` (Ollama / AIGUILLEUR sur le LAN).
  Aucune nouvelle dépendance réseau, aucune API externe, aucun téléchargement à l'exécution.
- **Aucun agent de développement ne lit les données réelles** : ni `storage/`, ni la base, ni les
  fichiers des candidats. Les tests utilisent des **offres fictives générées dans les tests**
  (`tmp_path`, openpyxl / texte synthétique).
- **Pas de contenu d'offre dans les logs** au-delà de l'existant (les `reponse[:200]` des warnings
  restent locaux ; ne pas en ajouter de nouveaux).
- La sortie de l'IA est une **proposition** : libellé « Proposition IA — à valider par la
  commission » sur tous les rendus.

## Constat (lecture du code + logs prod, 11/10/2026)

| # | Constat | Où | Effet |
|---|---|---|---|
| C1 | La grille Excel = **ligne 1 de la feuille active**, rien d'autre (ni pondérations, ni barème, ni autres feuilles) | `routers/compare.py` `_lire_colonnes_template` | Une grille RAO (critères **en lignes**) donne des critères absurdes, ou est **refusée** : en prod le 11/10 à 19:16-19:17, 6 × `400 « Le template ne contient aucune colonne en ligne 1 »` |
| C2 | Par candidat, l'IA doit rendre **uniquement un JSON** `{critère: valeur}` ; l'instruction utilisateur est collée **après** « Ne retourne que le JSON » | `_analyser_groupe` | Un prompt riche (étapes, Markdown) contredit le format → « ⚠ Échec de l'IA » |
| C3 | **Débordement de contexte** : `BUDGET_ANALYSE = 60 000` caractères ≈ 15–17 k tokens + consigne, pour `num_ctx = 16384` | `compare.py` l.75, `config.py` | Ollama coupe le **début** du prompt → nom du candidat et début de l'offre perdus, **en silence** |
| C4 | Aucun résumé par candidat ; seule une synthèse globale des écarts (5–8 puces) | `_synthetiser_ecarts` | La demande « points forts / faibles par candidat » n'est pas couverte |
| C5 | Aucune note chiffrée, aucun total pondéré, aucun classement | rendus xlsx/docx/md/pdf | La commission refait les calculs à la main |
| C6 | Le `catch` du lancement **avale le `detail`** du backend | `ReportsPage.tsx` l.107-108 | L'utilisateur voit « Erreur lancement comparaison » au lieu de la cause, lisible seulement dans les logs |

## Correspondance avec le prompt RAO de l'utilisateur

Le prompt RAO (rôle, règles, 4 étapes) est **bon sur le fond** ; c'est le mécanisme actuel qui
l'empêche de fonctionner. Après ce plan, chaque étape du prompt a sa fonctionnalité :

| Étape du prompt | Fonctionnalité |
|---|---|
| Rôle + règles impératives | « Consignes d'évaluation » placées **en tête** du prompt d'analyse (step 3) |
| 1 — Fiche par candidat | **Fiches candidats** (step 4) |
| 2 — Comparaison | Synthèse des écarts existante, nourrie des fiches (step 4) |
| 3 — Remplir le tableau | Grille lue automatiquement (step 1-2) + notation (step 5) + grille d'origine remplie (step 6) |
| 4 — Classement | Total pondéré **calculé par le code**, jamais par l'IA (step 5) |

## Découpage en deux lots

- **Lot A — gain rapide** : step 0, puis steps 3 et 4 (message d'erreur, instruction riche, fiches
  candidats). Utilisable seul.
- **Lot B — grille RAO** : steps 1, 2, 5, 6 (lecture intelligente, notation, grille remplie).
- Steps 7-8 : vérification et doc, à la fin de chaque lot.

Dépendances : 1 → 2 → 5 → 6 ; 3 → 4 → 5.

---

## Step 0 — Afficher la vraie cause d'un refus de lancement

Dans `ReportsPage.lancerComparaison`, afficher le `detail` renvoyé par l'API (ex. « Le template ne
contient aucune colonne en ligne 1 ») au lieu du message générique ; pour ce cas précis, suggérer
« Je les saisis ». Même correction pour les autres `catch` muets de la page.

**Acceptation** : un 400 avec `detail` affiche ce `detail` dans le toast ; un échec réseau garde un
message générique ; test vitest.

## Step 1 — Lecture intelligente de la grille Excel (backend)

Implémenter un service `services/grille_criteres.py` qui analyse **toutes les feuilles** de la
grille et rend une structure `GrilleCriteres` :
`{criteres: [{nom, ponderation, parent}], bareme: {echelle: [{note, libelle}], min, max} | null,
orientation: "lignes" | "colonnes", feuille, ancrages: {critère: cellule}, confiance, source:
"heuristique" | "ia"}`.

- **Heuristique d'abord** (déterministe, openpyxl) : repérer la ligne d'en-tête **où qu'elle soit**
  (pas seulement la ligne 1 : titres, lignes vides et cellules fusionnées au-dessus), l'orientation
  (critères en lignes ou en colonnes), les pondérations (« pondération », « coefficient », « points »,
  « poids », « % »), les sous-critères (numérotation 1.1 / 1.2, retrait, cellules fusionnées), le
  barème (bloc ou feuille « barème / notation / échelle », motifs « 0 = … »).
- **Repli IA locale** seulement si la confiance est basse : la feuille est envoyée en TSV borné
  (taille plafonnée) au modèle « rapport », qui rend un JSON validé (Pydantic). La grille est une
  donnée, pas une consigne : son contenu est encadré comme tel dans le prompt.
- Garde-fous sur un fichier non fiable : taille max, nombre de feuilles et de cellules plafonnés,
  `read_only`, aucune formule évaluée.
- Endpoint : `POST /api/generate/compare/grille/{template_id}` → `GrilleCriteres`.
  `start_compare` utilise ce service au lieu de `_lire_colonnes_template` : le 400 « aucune colonne
  en ligne 1 » ne doit plus arriver sur une grille lisible.

**Acceptation** : tests sur grilles **synthétiques** (ligne 1 vide + titre fusionné, critères en
lignes, en colonnes, avec et sans barème, multi-feuilles) ; pondérations et barème correctement
extraits ; une grille simple « ligne 1 = colonnes » donne le même résultat qu'aujourd'hui.

*Hors périmètre : modification de l'interface (step 2), notation (step 5).*

## Step 2 — Validation de la grille détectée dans l'UI

Dans `CritereBuilder`, mode « Template Excel » : après dépôt, appeler l'endpoint du step 1 et
afficher les **critères détectés, avec pondérations et barème, éditables**, ainsi qu'un badge
« lu automatiquement » ou « interprété par l'IA — à vérifier ». Avant le lancement, l'utilisateur
confirme ou corrige.

`CompareRequest` reçoit en plus `criteres: [{nom, ponderation}]` et `bareme` (facultatifs).
`colonnes` reste accepté pour la compatibilité.

**Acceptation** : une grille en lignes affiche les vrais critères ; une correction manuelle est
bien celle qui est envoyée ; `tsc` et vitest passent.

## Step 3 — Instruction riche compatible + fin du débordement de contexte

- Restructurer le prompt de `_analyser_groupe` : les **« Consignes d'évaluation de l'utilisateur »**
  passent **en tête** (rôle, règles, barème), suivies du contenu de l'offre, puis du format JSON, et
  enfin d'un **rappel court des consignes** à la fin. Phrase explicite : « ces consignes portent sur le
  CONTENU des valeurs ; le format de sortie reste le JSON ».
- **Budget dérivé de `settings.ollama_num_ctx`** (environ 3 caractères par token, moins une réserve
  pour la consigne et la réponse) au lieu de la constante de 60 000 → plus aucune coupe silencieuse.
- Mesure de la part lue par candidat (`lu_pct`, `tronque`), stockée dans le résultat et affichée
  (« offre lue à 62 % — mettre les pièces utiles en tête »).
- Preset « Analyse d'offres (RAO) » dans `scripts/seed-prompts.json` (catégorie comparatif).

**Acceptation** : un test vérifie que le prompt construit ne dépasse jamais le budget de tokens
dérivé de `num_ctx` ; un test vérifie que les consignes sont présentes en tête ET en fin ; une
instruction contenant des étapes ou du Markdown ne fait plus échouer l'extraction JSON (réponse
simulée).

*Hors périmètre : fiches candidats (step 4).*

## Step 4 — Fiche points forts / points faibles par candidat

- Option `fiches: bool` (vraie par défaut) dans `CompareRequest`.
- **Même appel IA** que l'extraction (l'offre n'est lue qu'une fois : le préremplissage domine le
  coût GPU) : le JSON gagne une clé réservée `"_fiche": {resume, points_forts[], points_faibles[],
  financier, vigilance[]}`.
- Robustesse : si `_fiche` manque ou est invalide alors que les critères sont bons, le candidat
  **n'est pas en échec** ; sa fiche est marquée « non produite » (jamais une fiche vide présentée
  comme pleine).
- La synthèse des écarts reçoit les fiches en plus du tableau.
- Rendus : cartes dans `CompareProgress` ; section « Fiches candidats » en md, pdf et docx ; feuille
  « Fiches candidats » dans le xlsx.

**Acceptation** : tests de parsing (fiche OK / absente / malformée) ; les 4 formats d'export
contiennent les fiches ; l'UI les affiche par candidat.

## Step 5 — Notation chiffrée, total pondéré, classement

- Quand un barème est connu (step 2), chaque valeur JSON devient `{"note": n, "justification": "…"}`.
- Validation : une note hors barème est **signalée** (pas corrigée en silence).
- **Total pondéré et classement calculés en Python**, jamais par l'IA.
- xlsx : formules `SOMMEPROD` (SUMPRODUCT) visibles, pour que la commission puisse corriger une note
  et voir le total se recalculer. Autres formats : tableau de notation, totaux, classement.
- Mention « Proposition IA — à valider par la commission » sur tous les rendus.

**Acceptation** : tests du calcul pondéré (pondérations en points et en %, critère N/A = 0,
sous-critères) ; note hors barème signalée ; formules présentes dans le xlsx généré.

## Step 6 — Remplir la grille RAO d'origine

À partir des `ancrages` du step 1, écrire les notes et les justifications **dans une copie** de la
grille déposée, aux bonnes cellules et selon l'orientation, en conservant mise en forme et formules.
Nouveau format de téléchargement : « Grille d'origine remplie ». Si les ancrages sont incertains,
repli sur la feuille générique, avec un message explicite.

**Acceptation** : sur les grilles synthétiques du step 1, chaque note est dans la bonne cellule ; le
fichier d'origine n'est jamais modifié ; les formules d'origine sont intactes.

## Step 7 — Vérification de bout en bout (pile jetable, données fictives)

Skill `/verify` : Postgres éphémère et backend de la branche, avec **2 ou 3 candidats fictifs**
(offres synthétiques) et une grille synthétique en lignes, ligne 1 vide. Parcours complet : dépôt de
la grille, validation des critères, génération, fiches, notation, 5 exports. Test par la route
**HTTP** (`192.168.42.83:3003`), pas seulement par le HTTPS.

**Acceptation** : parcours vert ; aucune donnée réelle utilisée ; aucune requête sortante hors LAN.

## Step 8 — Documentation

`docs/rapport-comparatif.md` (grille RAO, fiches, notation, limites de lecture), `README-UTILISATEUR.md`
(guide « Analyser des offres d'appel d'offres »), `CHANGELOG.md`, `ROADMAP.md`.
Étape applicative à signaler à la livraison : **réinstaller les presets** pour obtenir « Analyse
d'offres (RAO) ».
