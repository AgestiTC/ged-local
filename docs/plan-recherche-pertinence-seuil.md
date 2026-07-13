# Plan — Recherche : seuil de pertinence + « aucun document / afficher quand même »

> **Statut : à coder** (plan validé, non implémenté). Répond au retour utilisateur 02/07/2026 :
> « les résultats ne me semblent pas pertinents. En cas de doute je préférerais *"pas de document"*
> et un bouton pour afficher tout de même les fichiers proposés. »
>
> Lié à : ROADMAP → *Retours d'usage 02/07* · `[ref] Fonctionnement de la recherche` ·
> Phase 1 « Valider la recherche hybride (pertinence) ; ajuster la pondération si besoin ».

---

## 1. Le besoin

En recherche GED, l'utilisateur voit **toujours** une liste bien remplie (« 70 résultats »), même
quand rien ne correspond vraiment à sa demande (ex. « documents nécessaires à un dossier de mariage »
→ factures CDOS, adhérents, mots de passe Chrome…). C'est **anxiogène et trompeur** : on ne sait pas
si l'un de ces fichiers est réellement pertinent.

**Comportement voulu :**
- Quand **aucun** document n'est réellement pertinent → afficher **« Aucun document pertinent »**
  (état vide clair), **pas** une liste de faux positifs.
- Fournir un **bouton « Afficher quand même »** qui révèle les fichiers proposés (les meilleurs, même
  peu pertinents), avec un **avertissement** discret « résultats peu pertinents ».

---

## 2. Pourquoi c'est faux aujourd'hui — le piège du score normalisé

⚠️ **Point clé de conception.** Le pourcentage affiché (60 %, 56 %…) **n'est pas** une mesure absolue
de pertinence : c'est un score **normalisé par le meilleur résultat du lot**.

Aux deux endroits qui calculent le score :

| Couche | Fichier | Ce qu'elle fait |
|---|---|---|
| Endpoint GED live | `backend/routers/search.py` (`_recherche_fulltext` / `_recherche_semantique` + fusion l.183-207) | `score_norm = score / max_text` et `/ max_sem`, puis `0.4·texte + 0.6·sémantique` |
| Service (assistant, réutilisable) | `backend/services/search_service.py` (l.116, 150, 163-167) | `r.score / max_score` par sous-recherche, puis fusion 0.40/0.60 |

**Conséquence : le meilleur résultat vaut TOUJOURS ~100 %**, même s'il est mauvais. Le « 60 % »
affiché signifie juste « 60 % du meilleur d'un lot médiocre ». **Poser un seuil sur ce score
relatif ne détecterait jamais « aucun document pertinent »** — le top survit toujours.

> Rappel : le live GED (`GET /api/search`) passe par les **fonctions du routeur**, pas par la classe
> `SearchService` (utilisée par l'**Assistant** « Trouver des documents »). Les deux ont le même
> défaut → le plan traite le live d'abord, l'assistant en réutilisation (Phase 4).

### La bonne mesure : le signal ABSOLU

Il faut un signal **indépendant du lot** :

- **Sémantique** : la **similarité cosinus brute** `1 - (embedding <=> requête)` (avant toute
  normalisation), déjà calculée dans `_recherche_semantique` (`search.py` / `search_service.py`).
  C'est une vraie mesure « à quel point le sens est proche », typiquement dans **[0, 1]** pour ces
  embeddings. → **C'est le gate de pertinence recommandé** pour les modes *hybride* et *sémantique*.
- **Texte (full-text)** : `ts_rank` est **non borné et dépendant du corpus** → mauvais candidat pour
  un seuil absolu fixe. Le simple fait de **matcher** `plainto_tsquery` (opérateur `@@`) est déjà un
  signal binaire fort (les mots sont présents). → En mode *texte pur*, rester **permissif** (un match
  = pertinent) ; option d'un `ts_rank` minimal à calibrer plus tard.

**⚠️ Affiné par la calibration (§3.3) : le cosinus seul NE SUFFIT PAS.** Le modèle
`qwen3-embedding:8b` a un **plancher élevé et compressé** (une requête hors-sujet totale — « recette de
tarte aux pommes » — rend déjà 0.51) et il y a **chevauchement** : un vrai match (« contrat de
location », 0.618) score **plus bas** qu'un faux positif (« dossier de mariage », 0.657). Aucun seuil
unique sur le cosinus ne sépare les deux.

**Décision de conception (validée sur corpus réel) — gate à DEUX niveaux :**

> **pertinent = (cosinus ≥ SEUIL_HAUT)  OU  (cosinus ≥ SEUIL_BAS  ET  match full-text présent)**

Le **match full-text** (`plainto_tsquery @@`, sémantique ET entre les mots) est le **discriminant** qui
manquait : les requêtes sans réponse (« dossier de mariage », « recette… ») rendent **0 match** →
rejetées ; les vraies requêtes moyennes (« location », « adhérents ») ont un match lexical → acceptées
même à 0.60. Le score % affiché reste relatif ; on ajoute la **pertinence absolue** (cosinus) + le flag
`pertinent` (issu du gate) + une **étiquette** (Élevée/Moyenne/Faible).

---

## 3. Conception cible

### 3.1 Backend

**Capter le signal absolu.** Aujourd'hui la similarité cosinus brute est perdue après division par
`max_sem`. On la **conserve** par document (`pertinence` = cosinus brut du meilleur chunk), en plus du
score relatif normalisé existant.

**Gate de pertinence (à deux niveaux, cf. §2 & §3.3).** Après fusion/tri, calculer par résultat :
- `a_match_texte` = le doc est présent dans le résultat full-text (`plainto_tsquery @@`) ;
- `pertinent = (cosinus >= SEUIL_HAUT) or (cosinus >= SEUIL_BAS and a_match_texte)` ;
- mode texte pur : `pertinent = True` si match full-text (permissif).
- **étiquette** : `Élevée` si `cos ≥ SEUIL_HAUT` ; `Moyenne` si `cos ≥ SEUIL_BAS (+ lexical)` ;
  sinon `Faible` (→ masqué par défaut).

**Ne pas jeter les non-pertinents.** On **renvoie quand même** les meilleurs résultats sous le seuil
(jusqu'à `limit`), mais **marqués** `pertinent=false`. → Le bouton « Afficher quand même » est
**instantané** (pas de second appel réseau), et on connaît le nombre de masqués.

**Paramètres d'API** (`GET /api/search`) :
- `seuil` (float, optionnel) : surcharge le seuil ; défaut = valeur de config (cf. 3.3).
- `inclure_non_pertinents` (bool, défaut `false`) : quand `true`, l'appel est neutre (comportement
  actuel) — utile pour l'Assistant ou un futur mode « tout ».

**Réponse enrichie** :
```jsonc
{
  "query": "...", "type": "hybrid",
  "total": 70,              // total candidats (inchangé)
  "nb_pertinents": 0,       // 🆕 combien passent le seuil
  "nb_masques": 70,         // 🆕 combien sont sous le seuil (proposables)
  "seuil": 0.55,            // 🆕 seuil effectif appliqué
  "resultats": [
    {
      "id": "...", "nom": "...", "score": 0.60, // score relatif (affichage %, inchangé)
      "pertinence": 0.41,     // 🆕 similarité cosinus absolue [0-1]
      "pertinent": false,     // 🆕 >= seuil ?
      "metadonnees_ia": { ... }
    }
  ]
}
```
> `resultats` contient **tout** (pertinents + proposés), triés par score ; le **front** décide
> d'afficher les non-pertinents seulement sur clic. Alternative (à trancher) : ne renvoyer que les
> pertinents + un compteur `nb_masques`, et **re-fetch** avec `inclure_non_pertinents=true` au clic
> (1 requête de plus, mais réponse plus légère par défaut). **Recommandé : tout renvoyer + masquer
> côté front** (instantané, pas de re-fetch, corpus déjà plafonné à `limit`).

### 3.2 Frontend (`pages/GEDPage.tsx`, `stores/gedStore.ts`, `api/index.ts`)

- Filtrer l'affichage sur `pertinent === true` par défaut.
- **`nb_pertinents === 0`** → nouvel **état vide** :
  > **Aucun document pertinent pour « … »**
  > *La recherche n'a rien trouvé qui corresponde vraiment.*
  > `[ Afficher quand même les N fichiers proposés ]`
  (remplace / complète le « Aucun résultat pour … » existant, l.329-331 — qui reste pour le cas
  0 candidat réel).
- Clic « Afficher quand même » → état local `afficherProposes=true` → on montre tous les
  `resultats` **avec un bandeau** : « ⚠️ Résultats peu pertinents — affichés à votre demande ».
- Chaque carte non pertinente peut porter un liseré/atténuation discret + le % reste affiché.
- Types `SearchResponse` étendus (`nb_pertinents`, `nb_masques`, `seuil`, `pertinence`, `pertinent`).

### 3.3 Calibration — RÉALISÉE le 02/07/2026 (corpus dev ~520 docs, `qwen3-embedding:8b`)

Sonde read-only (embed requête + cosinus brut par doc + comptage full-text). Résultats :

| Requête témoin | cosinus top1 | matches full-text | verdict voulu | gate |
|---|---|---|---|---|
| dossier de mariage | 0.657 | 0 | ❌ rien | rejeté ✅ |
| documents nécessaires…mariage | 0.627 | 0 | ❌ rien | rejeté ✅ |
| recette tarte aux pommes | 0.511 | 0 | ❌ rien | rejeté ✅ |
| contrat de location immobilière | 0.618 | 3 | ✅ | accepté ✅ |
| liste des adhérents du club | 0.686 | 1 | ✅ | accepté ✅ |
| manuel utilisation windows | 0.754 | 3 | ✅ | accepté ✅ |
| facture | 0.830 | 59 | ✅ | accepté ✅ |
| attestation assurance | 0.933 | 34 | ✅ | accepté ✅ |

**Enseignements clés :**
- Plancher cosinus **élevé** (~0.51 même hors-sujet total) → un seuil « ~0.5 » naïf laisserait TOUT
  passer. La cible pertinente commence plutôt vers **0.60**.
- **Chevauchement** cosinus entre faux positifs (jusqu'à 0.657) et vrais positifs (dès 0.618) → seuil
  unique impossible ; d'où le **gate à deux niveaux + corroboration lexicale** (§2/§3.1).

**Valeurs retenues (provisoires, configurables) :**
- `SEUIL_HAUT = 0.72` (haute confiance, sémantique seule suffit) ;
- `SEUIL_BAS  = 0.60` (accepté seulement **avec** match full-text).
- Ces deux valeurs séparent **parfaitement** les 8 requêtes témoins (colonne « gate »).

**Config & suite :**
- Les 2 seuils **configurables en base** via `runtime_config` (clés ex. `search_cos_haut` /
  `search_cos_bas`) → réglables sans redeploy. Pattern identique à `usage_models`.
- ⚠️ **À re-valider sur le vrai corpus NAS** (bien plus gros) : le plancher/les échelles peuvent
  bouger. La sonde de calibration est réutilisable (script jetable dans le scratchpad de session).
- UI (option, Phase 3) : curseur « Exigence : souple ↔ stricte » qui mappe sur ces 2 seuils.

---

## 4. Phasage

> Calibration **déjà faite** (§3.3) → les seuils `0.72 / 0.60` sont connus ; plus de phase de
> calibration bloquante. Périmètre **GED + Assistant** dès le cœur (décision §5.6).

- [ ] **Phase 1 — Backend : gate à deux niveaux + réponse enrichie** (`search.py` **et**
      `search_service.py`)
  - exposer la `pertinence` (cosinus brut) + le flag `a_match_texte` par doc (déjà calculés, il suffit
    de ne pas les perdre à la normalisation) ;
  - gate `(cos ≥ HAUT) or (cos ≥ BAS and a_match_texte)` ; champs `pertinent`, `etiquette`,
    `nb_pertinents`, `nb_masques`, `seuils` ; **renvoyer tous les résultats marqués** ;
  - params `inclure_non_pertinents` (bypass) ; seuils lus depuis `runtime_config`
    (`search_cos_haut=0.72` / `search_cos_bas=0.60`, défauts en dur en fallback) ;
  - **appliquer le même gate à l'Assistant** (`SearchService` → pièces non pertinentes écartées) ;
  - tests `backend/tests/test_search_service.py` : « mariage » → `nb_pertinents=0` ; « location »/
    « facture » → `nb_pertinents>0` ; `inclure_non_pertinents=true` = comportement actuel.
- [ ] **Phase 2 — Frontend : état vide + « Afficher quand même » + étiquette**
  - filtre `pertinent`, **état vide dédié** (« Aucun document pertinent »), bouton, bandeau
    d'avertissement, atténuation des cartes masquées ;
  - **remplacer le % relatif par l'étiquette** Élevée/Moyenne/Faible sur les cartes ;
  - types (`SearchResponse`) + store (`gedStore`) : `nb_masques`, `etiquette`, flag `afficherProposes` ;
  - côté Assistant : message « aucune pièce pertinente trouvée » quand le gate vide la proposition.
- [ ] **Phase 3 — Réglage UI (option)** : curseur « Exigence : souple ↔ stricte » (Paramètres) mappant
      sur `search_cos_haut/bas` ; re-validation des seuils sur le **corpus NAS** (sonde réutilisable).

---

## 5. Décisions (arbitrées le 02/07)

Décisions techniques (recommandations retenues) :

1. ✅ **Renvoyer tout marqué** (pas de re-fetch au clic) — cf. 3.1. Réponse plus lourde mais bornée à
   `limit` ; « Afficher quand même » **instantané**, un seul appel réseau.
2. ✅ **Seuil unique** (pas par type) pour démarrer ; on affinera par type seulement si la calibration
   montre des échelles trop différentes entre hybride et sémantique.
3. ✅ **Mode texte pur = permissif** (tout match `@@` = pertinent) au départ ; seuil `ts_rank` optionnel
   plus tard si nécessaire.

Décisions produit/UX (choix utilisateur) :

4. ✅ **Exigence par défaut = « Équilibré »** — montre les résultats raisonnablement proches, cache le
   clairement hors-sujet. Le bouton « Afficher quand même » rattrape les cas limites → pas besoin
   d'être « strict » d'entrée. *(Cible de calibration §3.3 = trouver le seuil qui sépare bons ↔ faux
   positifs sur les requêtes témoins.)*
5. ✅ **Affichage carte = étiquette de pertinence** « Élevée / Moyenne / Faible » (dérivée de la
   pertinence **absolue**), **à la place du % relatif trompeur**. Plus honnête, moins anxiogène.
   *(Impl. : mapping seuils → 3 paliers ; le % relatif peut rester en info-bulle/debug si utile.)*
6. ✅ **Périmètre = GED + Assistant ensemble** dès la Phase 1/2 : le même gate s'applique à
   `GET /api/search` **et** à `SearchService` (Assistant « Trouver des documents ») → l'Assistant
   cesse aussi de proposer des pièces hors-sujet. *(Fusionne l'ex-Phase 4 dans le cœur ; cf. §4.)*

Calibration (résolue le 02/07) :

7. ✅ **Seuils calibrés** (§3.3) : la sonde a montré qu'un **seuil unique est impossible** (plancher
   cosinus ~0.51, chevauchement bons/faux positifs) → **gate à deux niveaux** validé sur 8 requêtes
   témoins : `SEUIL_HAUT = 0.72`, `SEUIL_BAS = 0.60` (+ corroboration full-text). Provisoires,
   configurables en base, **à re-valider sur le corpus NAS**.

## 6. Garde-fous / non-régressions

- Aucun changement du calcul du **score % affiché** (reste relatif) → pas de régression visuelle sur
  les résultats pertinents.
- `inclure_non_pertinents=true` reproduit **exactement** le comportement actuel (filet de sécurité).
- 100 % local, aucune sortie réseau — le seuil est un simple filtre calculé en base/back.
