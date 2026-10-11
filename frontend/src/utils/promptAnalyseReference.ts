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
