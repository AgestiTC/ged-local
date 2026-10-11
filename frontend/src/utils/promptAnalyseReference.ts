/**
 * Consigne du rapport « Analyser les documents de référence » (CCTP, règlement…) — 11/10/2026.
 * ===========================================================================================
 * Fond, forme, pertinence, manques, points positifs : un retour CONSTRUCTIF, clair et visuel.
 * Rendu en Markdown simple (titres, emojis, jauges ▰▱, listes) : l'aperçu des rapports n'affiche
 * pas les tableaux Markdown, et ce format passe tel quel dans les exports PDF / Word.
 * Les critères de notation, s'ils sont connus, servent à vérifier que le document permet de
 * noter les offres sur chacun d'eux (exigences mesurables).
 */
export function promptAnalyseReference(criteres: string[] = []): string {
  const blocCriteres = criteres.length
    ? `\nLes offres seront notées sur ces critères :\n${criteres.map(c => `- ${c}`).join('\n')}\n` +
      `Pour chacun, vérifie que le document fixe des exigences claires et mesurables qui permettront de noter les offres.\n`
    : ''
  return `Tu es un expert de la commande publique, bienveillant et précis. Relis le ou les documents de référence fournis (CCTP, règlement de consultation…) et rédige un retour CONSTRUCTIF sur leur fond et leur forme.
${blocCriteres}
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
${criteres.length ? '\n## 🔗 Cohérence avec les critères de notation\nPour chaque critère : ✅ exigences claires et mesurables · ⚠️ à préciser · ❌ rien pour l\'évaluer — avec une phrase d\'explication.\n' : ''}
## 💡 Les 3 actions prioritaires
Trois actions numérotées, courtes et concrètes, pour améliorer le document.`
}

/**
 * Consigne « Proposer une version corrigée » du document de référence (11/10/2026).
 * Un CCTP entier ne tient pas dans ce qu'un modèle local peut réécrire en une fois : on rend les
 * passages à MODIFIER (avant → après, pourquoi) et les clauses à AJOUTER, prêts à copier.
 */
export function promptVersionCorrigee(criteres: string[] = []): string {
  const blocCriteres = criteres.length
    ? `\nLes offres seront notées sur : ${criteres.join(' ; ')}. Les exigences liées doivent devenir claires et mesurables.\n`
    : ''
  return `Tu es un rédacteur expert de la commande publique. À partir du ou des documents de référence fournis (CCTP, règlement de consultation…), propose une VERSION CORRIGÉE : ne réécris que ce qui doit changer, dans le style juridique et administratif du document.
${blocCriteres}
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
}
