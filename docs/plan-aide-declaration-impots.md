# Plan — Administration › « Aide à la déclaration d'impôts »

> Plan de conception (**à coder**), branche `Nounou`. Référencé depuis
> [ROADMAP.md](../ROADMAP.md). Demandé le 09/09/2026, en conséquence directe du module
> [emploi à domicile](plan-nounou.md) : employer une assistante maternelle ou une aide
> ménagère ouvre droit à un crédit d'impôt, et Matothèque détient déjà de quoi le justifier.

## Ce que l'onglet fait — et ce qu'il ne fait pas

**Il fait** : rassembler, **par année**, ce que Matothèque sait déjà de votre situation
fiscale — montants, cases concernées, et surtout **les pièces qui les justifient** — pour
arriver devant le formulaire avec le dossier prêt plutôt que devant une boîte à chaussures.

**Il ne fait pas** : votre déclaration. Aucun calcul d'impôt, aucun conseil fiscal, aucune
transmission à l'administration. Un montant affiché est **une proposition sourcée à
vérifier**, jamais un résultat. La nuance n'est pas rhétorique : elle décide de l'écran.

## Le vrai sujet : « qui devra évoluer dynamiquement »

C'est la partie qui compte, et la seule qui soit un vrai choix d'architecture.

Un onglet fiscal écrit « en dur » vieillirait de la pire façon : chaque nouveau module
touchant à l'argent (emploi à domicile aujourd'hui ; dons, travaux, revenus locatifs, frais
réels demain) obligerait à **rouvrir la page Administration** pour y ajouter une section. Un
jour on oublierait, et l'onglet deviendrait faux par omission — le pire état pour un écran
fiscal, parce que rien à l'écran ne signale ce qui manque.

**Donc l'onglet ne connaît aucun module.** Il affiche ce qu'un **registre de contributeurs**
lui rend. Ajouter un module fiscal = **enregistrer un contributeur**, zéro ligne d'interface.

### Le contrat (une seule chose à implémenter par module)

```python
# services/fiscalite/registre.py
class ContributeurFiscal(Protocol):
    cle: str            # 'emploi-domicile', 'dons', 'ged-pieces'…
    libelle: str        # « Emploi à domicile »
    async def annees(self) -> list[int]: ...
    async def contributions(self, annee: int) -> list[LigneFiscale]: ...
```

```python
@dataclass
class LigneFiscale:
    case: str | None        # « 7GA », « 7DB »… None si la case dépend de la situation
    libelle: str
    montant: Decimal | None # None = « à saisir », et c'est une réponse valable
    nature: str             # 'credit_impot' | 'reduction' | 'revenu' | 'piece'
    sources: list[Source]   # document GED, contrat, fiche — CLIQUABLES
    confiance: str          # 'calcule' | 'partiel' | 'a_verifier' | 'a_saisir'
    note: str | None        # ce qu'il reste à faire, en français
    barème_verifie_le: date | None
```

`GET /api/fiscalite/synthese?annee=2026` parcourt le registre et agrège. L'écran rend
**ce qu'il reçoit** : un contributeur inconnu de lui s'affiche quand même.

### Trois règles qui font la différence entre utile et dangereux

1. **Aucun montant sans source cliquable.** Chaque ligne dit d'où elle vient et le clic
   ouvre la pièce (document GED, contrat, fiche intervenant). Un chiffre non traçable
   n'est pas affiché — il devient une ligne `a_saisir` avec sa raison.
2. **`confiance` est visible, pas décorative.** « calculé à partir de 11 déclarations
   Pajemploi » et « estimé sur un contrat, paies non saisies » ne se recopient pas dans un
   formulaire avec la même main.
3. **Ce qui manque s'affiche.** Un contributeur sans donnée pour l'année rend une section
   « rien pour 2026, voici pourquoi », jamais rien du tout. *(Application directe de la
   leçon v1.84.3 déjà inscrite en ROADMAP : ne plus masquer faute de donnée.)*

## Les contributeurs du premier jour

### 1. `emploi-domicile` — celui qui motive l'onglet

- **Profil `assmat` / `garde_domicile`** → crédit d'impôt **frais de garde d'un enfant de
  moins de 6 ans** (cases 7GA/7GB/7GC selon l'enfant). Calculé depuis les contrats et les
  montants déclarés, **net des aides perçues** : le CMG **se déduit** de l'assiette, et
  l'oublier est l'erreur la plus fréquente du dispositif.
- **Profil `aide_domicile` / `autre_sap`** → crédit d'impôt **services à la personne**
  (7DB et suivantes), **net de l'avance immédiate déjà versée** — même piège, autre case.
- L'année de l'enfant compte : le passage des 6 ans fait **changer de case en cours de
  route**. La ligne le signale plutôt que de choisir à votre place.

### 2. `ged-pieces` — ce que la GED sait déjà

L'enrichissement IA pose déjà catégorie, tags et entités sur chaque document. Ce
contributeur ne **calcule rien** : il **rassemble les pièces** de l'année dont la nature est
fiscale (attestations de dons, factures de travaux, relevés, attestations annuelles
d'organismes) et les présente en liste `piece` / `a_verifier`.

C'est volontairement modeste, et c'est déjà ce qui fait gagner la soirée : ces papiers
existent, ils sont indexés, et on les cherche un par un chaque printemps.

⚠️ **Jamais de montant lu par l'IA dans un document.** Un LLM local qui se trompe d'un
chiffre sur une attestation produit une erreur **indétectable** et recopiée telle quelle dans
une déclaration. L'IA classe et retrouve ; elle ne chiffre pas. *(Même refus que le socle
réglementaire du module emploi à domicile.)*

### Ensuite, sans toucher à l'interface

Dons aux associations · travaux et rénovation énergétique · revenus fonciers · frais réels ·
scolarité. Chacun = un contributeur enregistré, le jour où le module existe.

## L'écran

- **Sélecteur d'année** en tête (l'impôt se déclare l'année suivante : proposer N-1 par
  défaut, pas N).
- Une **section pliable par contributeur** (`CollapsibleSection`, déjà en place), une ligne
  par contribution : case · libellé · montant · pastille de confiance · sources.
- **Bouton « copier le montant »** — via `utils/clipboard.ts`, **jamais**
  `navigator.clipboard` : l'application est servie en HTTP *(règle CLAUDE.md)*.
- **Export PDF récapitulatif** par les briques existantes — l'objet qu'on emporte devant le
  formulaire, sources incluses.
- **Bandeau permanent** : *ce n'est pas une déclaration ni un conseil fiscal ; les montants
  sont à vérifier ; seul impots.gouv.fr fait foi.* Le lien sort par `netConfirm`.

### ⚠️ Le piège d'intégration, à traiter en premier

Aujourd'hui `AdminPage` **n'est qu'une liste de liens**, et la barre latérale ne l'affiche
que si `adminCount > 0` (`Sidebar.tsx`). En l'état, **un utilisateur sans aucun lien
administratif n'aurait jamais accès à l'onglet fiscal** — une fonctionnalité livrée,
invisible, pour une raison sans rapport.

La page passe donc à **deux onglets** (« Liens » · « Aide à la déclaration ») et sa condition
d'affichage devient `adminCount > 0 || fiscaliteDisponible`. C'est exactement la leçon
v1.84.3 déjà payée une fois : *ne plus conditionner une commande à une donnée annexe*.

## Ce qu'on ne fait pas

- **Aucun appel à impots.gouv, à la DGFiP, à FranceConnect.** Matothèque reste locale ; les
  liens s'ouvrent après confirmation, comme partout.
- **Aucun calcul d'impôt** (barème, quotient, plafonnement) : ce n'est pas un simulateur, et
  un simulateur faux est pire que pas de simulateur.
- **Aucun pré-remplissage automatique de formulaire.**
- **Aucun montant produit par l'IA.**

## Phasage

- [ ] **Lot 1 — Le registre et l'onglet vide mais vivant** : `services/fiscalite/registre.py`,
      `GET /api/fiscalite/synthese`, onglet dans Administration, correction de la condition
      d'affichage de la barre latérale. Un seul contributeur bidon pour prouver le mécanisme.
      *Utile seul : la structure est là, et le jour où un module arrive, il s'affiche.*
- [ ] **Lot 2 — Contributeur `ged-pieces`** : rassembler les pièces fiscales de l'année depuis
      l'indexation existante. Aucune donnée nouvelle à saisir. *Utile seul, et immédiatement.*
- [ ] **Lot 3 — Contributeur `emploi-domicile`** : dépend de la **phase 3** du module (les
      contrats), et surtout de la saisie des montants réellement versés — à cadrer avec la
      phase 4 (simulateur de coût net), qui produit déjà les mêmes chiffres.
- [ ] **Lot 4 — Export PDF récapitulatif** et rappel annuel (jalon, printemps).
