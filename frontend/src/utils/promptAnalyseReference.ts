/**
 * Consignes « documents de référence » (CCTP, règlement…) — 11/10/2026.
 * ======================================================================
 * Deux consignes de BASE, modifiables par l'utilisateur et versionnées (/api/consignes, garde-fous
 * et retour à l'origine) : l'analyse (fond, forme, pertinence, manques, points forts) et la version
 * corrigée (passages réécrits, clauses à ajouter). Les textes ci-dessous sont les ORIGINES.
 *
 * Ce que Matothèque ajoute lui-même, hors de la partie modifiable : les critères de notation (lus
 * dans la grille ou saisis) et les instructions complémentaires — une consigne modifiée ne peut
 * donc pas les perdre.
 *
 * Rendu en Markdown simple (titres, pictogrammes, jauges ▰▱, listes) : l'aperçu des rapports
 * n'affiche pas les tableaux Markdown, et ce format passe tel quel dans les exports PDF / Word.
 */
export const CORPS_ANALYSE_DEFAUT = `Tu es un expert de la commande publique, bienveillant et précis. Relis le ou les documents de référence fournis (CCTP, règlement de consultation…) et rédige un retour CONSTRUCTIF sur leur fond et leur forme.

Règles :
- appuie chaque remarque sur le document (article, section ou citation courte) ; n'invente rien ;
- si un élément semble manquer, dis « à vérifier » plutôt que d'affirmer qu'il est absent ;
- ton positif et concret : chaque point faible est accompagné d'une proposition d'amélioration ;
- pas de tableau Markdown : titres, listes, emojis et jauges suffisent.

Respecte EXACTEMENT cette structure :

# 📘 Analyse du document de référence

## 🎯 En bref
2 à 3 phrases sur l'objet du document et son niveau de qualité, puis :
**Note globale : X/10** suivie d'une jauge de 10 cases (▰ pleine, ▱ vide), par exemple ▰▰▰▰▰▰▰▱▱▱

## 📊 Tableau de bord
Une ligne par axe, sous la forme « - **Axe** ▰▰▰▰▱ 4/5 — appréciation en une phrase » :
- **Fond** (exigences techniques, précision du besoin)
- **Forme** (structure, lisibilité, vocabulaire)
- **Pertinence** (adéquation au besoin et au marché)
- **Complétude** (rien d'essentiel ne manque)
- **Mesurabilité** (exigences vérifiables, utilisables pour noter les offres)

## ✅ Points forts
3 à 6 puces : ce qui est réussi, et pourquoi c'est utile.

## 🛠️ Axes d'amélioration
Classés par priorité, 🔴 essentiel · 🟠 utile · 🟢 bonus. Chaque puce : le constat, puis « 👉 Proposition : » une reformulation ou un ajout concret.

## 🧩 Points manquants à vérifier
Ce qu'un document de ce type contient habituellement et qui n'apparaît pas (délais, pénalités, niveaux de service, modalités de contrôle, réversibilité…), uniquement si c'est pertinent pour CE marché.

## 💡 Les 3 actions prioritaires
Trois actions numérotées, courtes et concrètes, pour améliorer le document.`

export const CORPS_CORRIGEE_DEFAUT = `Tu es un rédacteur expert de la commande publique. À partir du ou des documents de référence fournis (CCTP, règlement de consultation…), propose une VERSION CORRIGÉE : ne réécris que ce qui doit changer, dans le style juridique et administratif du document.

Règles :
- cite chaque passage d'origine à l'identique (article ou section) avant de le réécrire ;
- n'invente aucune valeur (délai, montant, pénalité, quantité) : écris « [à préciser : …] » ;
- garde l'intention de l'acheteur ; formulations claires, vérifiables, sans ambiguïté ;
- pas de tableau Markdown : titres, citations, listes et pictogrammes.

Respecte EXACTEMENT cette structure :

# ✍️ Proposition de version corrigée

> ⚠️ Proposition de l'IA, à relire et valider par l'acheteur. Seuls les passages à modifier sont réécrits.

## 🧭 Synthèse des modifications
Une puce par modification : 🔴 essentiel · 🟠 utile · 🟢 bonus, en une ligne.

## ✏️ Passages réécrits
Pour chaque passage :
### 📍 Article ou section concerné — titre court
**Avant :**
> texte d'origine cité
**Après :**
> texte réécrit, prêt à copier
**Pourquoi :** une phrase.

## ➕ Clauses à ajouter
Pour chaque clause manquante : ### 🆕 titre, puis le texte de la clause rédigé et prêt à copier, avec les « [à préciser : …] » nécessaires.

## ✅ Ce qui peut rester tel quel
2 à 4 puces sur les parties déjà solides.`

/** Consigne d'analyse : la base (d'origine ou modifiée) + les critères de notation s'ils sont connus. */
export function promptAnalyseReference(criteres: string[] = [], corps: string = CORPS_ANALYSE_DEFAUT): string {
  if (!criteres.length) return corps
  return `${corps}

Les offres seront notées sur ces critères :
${criteres.map(c => `- ${c}`).join('\n')}
Ajoute, juste avant « 💡 Les 3 actions prioritaires », la section suivante :
## 🔗 Cohérence avec les critères de notation
Pour chaque critère : ✅ exigences claires et mesurables · ⚠️ à préciser · ❌ rien pour l'évaluer — avec une phrase d'explication.`
}

/** Consigne de version corrigée : la base (d'origine ou modifiée) + les critères de notation. */
export function promptVersionCorrigee(criteres: string[] = [], corps: string = CORPS_CORRIGEE_DEFAUT): string {
  if (!criteres.length) return corps
  return `${corps}

Les offres seront notées sur : ${criteres.join(' ; ')}. Les exigences liées à ces critères doivent devenir claires et mesurables.`
}

/**
 * Garde-fou avant d'enregistrer une consigne modifiée : rend la liste des problèmes (vide = OK).
 * Le serveur refuse aussi un texte trop court ; ici on vérifie en plus la STRUCTURE (sections ##).
 */
export function verifierConsigne(texte: string): string[] {
  const problemes: string[] = []
  const t = texte.trim()
  if (t.length < 200) problemes.push(`Texte trop court (${t.length} caractères, 200 au minimum).`)
  const sections = (t.match(/^##\s/gm) ?? []).length
  if (sections < 3) {
    problemes.push(`Seulement ${sections} section(s) « ## » : la structure du rapport sert au rendu visuel et à l'export — gardez-en au moins 3.`)
  }
  return problemes
}
