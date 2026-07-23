# Plan — Page « Créer » : panneau de résultat (Aperçu / Rendu / Source / Éditer)

> **Origine** : retour user 23/07 — « je le vois où ? à quoi sert *Votre rapport* ? ».
> La check-list de préparation (« VOTRE RAPPORT : Documents ✅ / Mode / Instruction ✅ ») est
> confondue avec le rapport lui-même. L'utilisateur veut séparer clairement **préparation** et
> **rendu**, et voir le document se construire en direct dans un onglet dédié.
>
> Statut : **plan** — ne rien coder sans validation. Recoupe l'entrée ROADMAP ④ (« les onglets
> Aperçu/Source/Éditer s'affichent trop tôt »).

---

## 0. État actuel (`frontend/src/components/reports/ReportPreview.tsx`)

- **Onglets** : `Aperçu | Source | Éditer` (états `preview | source | edit`).
- **État vide** (avant génération) : l'onglet Aperçu affiche la check-list **« VOTRE RAPPORT »**
  (Documents / Mode / Instruction) — c'est un **récap de préparation**, pas le rapport.
- **Pendant/après génération** : le même onglet Aperçu affiche le Markdown streamé (`rapportEnCours`
  puis `rapportFinal`).
- **Boutons** : Copier · PDF · DOCX · Wiki (publier) · Effacer. **Pas de Markdown (.md)**.

**Problèmes** :
1. La check-list occupe la place du rapport → « je le vois où ? ».
2. Les onglets Source/Éditer sont présents même quand il n'y a **rien** à afficher.
3. Aucun repère de ce qui se passe pendant la « réflexion » silencieuse (`think:false` → le modèle
   réfléchit sans streamer, l'écran reste vide plusieurs secondes → impression de blocage).

---

## 1. Cible demandée par l'utilisateur

### 1a. Onglet **Aperçu** = préparation + état d'avancement

- Garder la check-list **« Votre rapport »** (Documents / Mode / Instruction) comme **récap figé**.
- **Sous** la ligne « ✅ Instruction : défini », ajouter un bloc **« Réflexion / avancement »** :
  - avant génération : rien (ou « Prêt — cliquez sur Générer ») ;
  - pendant : indicateur vivant — « ⏳ Le modèle réfléchit… » puis « ✍️ Rédaction en cours
    (N caractères) », modèle utilisé, temps écoulé ;
  - le récap Documents/Mode/Instruction **reste figé** au-dessus (ne se recalcule pas pendant
    la génération).
- **But** : l'Aperçu devient le « tableau de bord » de la génération ; le rendu part ailleurs.

### 1b. Nouvel onglet **Rendu** — `Aperçu | Rendu | Source | Éditer`

- Affiche le **document rendu en streaming** (Markdown → HTML via `ReactMarkdown`), au fil de l'eau.
- **Barre d'outils du rendu** : boutons de téléchargement multi-formats
  - **PDF** (existant) · **DOCX** (existant) · **Markdown `.md`** *(à ajouter)* ·
  - **Envoyer au Wiki** (existant `exportWiki`, à déplacer ici) ;
  - Copier.
- **Bascule automatique** : au clic sur « Générer », on ouvre l'onglet **Rendu** (l'utilisateur voit
  le document se construire sans avoir à changer d'onglet).

### 1c. Onglets Source / Éditer

- **Source** : Markdown brut (déjà là).
- **Éditer** : édition inline avant export (déjà là).
- **Masquer Rendu/Source/Éditer tant qu'aucune génération n'a démarré** (corrige ROADMAP ④ :
  onglets affichés trop tôt). Seul **Aperçu** est visible à l'état initial.

---

## 2. Découpage technique

| Étape | Fichier(s) | Détail |
|-------|-----------|--------|
| **1. Export Markdown** | `stores/reportStore.ts` (+ `routers/export.py` si besoin) | Bouton `.md` : le contenu EST déjà du Markdown → simple `Blob`/téléchargement côté front, aucun appel backend. Le plus rapide, à livrer en premier. |
| **2. Onglet Rendu** | `ReportPreview.tsx` | Ajouter l'état `'rendu'` aux onglets ; y déplacer le rendu `ReactMarkdown` + la barre d'export. Aperçu ne garde que la check-list + bloc avancement. |
| **3. Bloc « Réflexion / avancement »** | `ReportPreview.tsx`, `stores/reportStore.ts` | Dériver de `isGenerating` + `rapportEnCours.length` : « réfléchit… » tant que 0 car., « rédaction (N car.) » ensuite. Chrono simple. |
| **4. Figer la check-list** | `ReportPreview.tsx` | Calculer Documents/Mode/Instruction une fois à `startGeneration`, ne pas recalculer pendant le stream. |
| **5. Onglets conditionnels** | `ReportPreview.tsx` | Rendu/Source/Éditer visibles seulement si `rapportEnCours || rapportFinal`. Bascule auto sur Rendu au lancement. |

## 3. Points de vigilance

- **`think:false` = silence initial** : le bloc « avancement » (1a) est justement là pour couvrir
  ce temps mort — sans lui, l'utilisateur croit que rien ne se passe (constaté 23/07).
- **Wiki** : le bouton « Envoyer au Wiki » existe déjà (`exportWiki` → BookStack). On le **déplace**
  dans la barre du Rendu, on ne le recrée pas.
- **Cohérence des autres modes** : Template / Classement / Comparatif / Tuto wiki partagent ce
  panneau — vérifier que « Rendu » a du sens pour chacun (le mode Template produit un `.docx`, pas
  du Markdown : y adapter la barre d'export).
- **Streaming réel jusqu'à l'écran** : si le rendu n'apparaît pas au fil de l'eau derrière NPMplus,
  ajouter `proxy_buffering off;` sur l'hôte `ged.tclement.fr` (déjà fait pour `ollama.tclement.fr`).
- **Zéro logique métier** : pur remaniement d'affichage du panneau existant.
