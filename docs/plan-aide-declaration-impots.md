# Plan — Administration › « Aide à la déclaration d'impôts »

> Branche `Nounou`. Référencé depuis [ROADMAP.md](../ROADMAP.md). Demandé le 09/09/2026, en
> conséquence directe du module [emploi à domicile](plan-nounou.md) : employer une assistante
> maternelle ou une aide ménagère ouvre droit à un crédit d'impôt, et Matothèque détient déjà
> de quoi le justifier.
>
> **État : lots 1, 1 bis et 2 codés le 09/09/2026** (registre, vue par case, questions de
> résolution, contributeur `ged-pieces`) — 17 tests dédiés, suite complète au vert.
> Restent les lots 3 (contributeur `emploi-domicile`) et 4 (export PDF, rappel annuel).

## La question à laquelle l'onglet répond

> **« J'ai payé ça — dans quelle case je le mets ? »**

C'est *la* demande, et elle mérite d'être prise au pied de la lettre. Personne ne bloque sur
« combien ai-je versé à la nounou » : ce chiffre est sur les relevés Pajemploi. On bloque sur
**7GA ou 7GB**, sur **7DB alors que l'aide perçue va en 7DR**, et sur le fait que ces cases
ne sont **pas sur la 2042** mais sur une **annexe (2042-RICI)** dont beaucoup ignorent
l'existence — on la cherche dix minutes avant de la trouver.

L'onglet répond donc dans cet ordre : **la case**, puis le montant, puis la pièce qui le
justifie. Pas l'inverse.

## Conseiller, oui — mais seulement ce qui est sourcé

Mon premier jet écrivait « aucun conseil fiscal ». **C'était trop large, et ça visait le
mauvais risque.** Le danger n'est pas de conseiller : c'est d'affirmer **sans source**.

**Ce que l'onglet dit, et qui est du conseil parfaitement légitime :**

- **Orienter vers la bonne case** — la demande principale. Règle publiée, écrite en dur,
  datée, avec le lien vers la notice officielle.
- **Expliquer un mécanisme** : *« le CMG que vous percevez se déduit de l'assiette du crédit
  d'impôt »*, *« l'avance immédiate déjà versée se retire des dépenses déclarées »*. Ce sont
  les erreurs les plus fréquentes du dispositif, et les signaler est exactement l'utilité.
- **Signaler une incohérence dans VOS données** : *« 3 attestations de dons indexées pour
  2026, mais aucune ligne de dons dans votre synthèse »*. L'alerte naît de vos pièces, pas
  d'une supposition.
- **Comparer deux options quand l'arithmétique tranche seule** (frais réels vs abattement),
  en montrant **la formule et les deux résultats** — pas en choisissant.
- **Rappeler les délais** : dates limites de déclaration, délai de réclamation.

**Ce qu'il ne dit jamais :**

- un **montant lu par l'IA** dans un document — erreur indétectable, recopiée telle quelle ;
- une **recommandation d'optimisation** qui dépend de données que l'application n'a pas
  (*« prenez les frais réels »* sans connaître vos revenus ni votre situation) ;
- une phrase à l'**impératif** : jamais *« déclarez X en 7GA »*, toujours *« d'après vos
  pièces, X semble relever de 7GA — voici pourquoi, voici la notice, vérifiez »*.

La ligne de partage n'est donc pas *conseil / pas conseil*, c'est **sourcé et déterministe /
pas sourcé**. Une règle fiscale publiée, écrite en dur avec sa date et son lien, est du
conseil sûr. Un chiffre deviné ne l'est jamais, même prudent.

## « Dans quelle case ? » — comment l'écran le rend

**Le regroupement principal est la déclaration, pas les modules.** On remplit un formulaire
en le descendant, pas en parcourant ses propres modules — donc :

| Formulaire | Case | Libellé | Montant | Confiance | Pièces |
|---|---|---|---|---|---|
| 2042-RICI | **7GA** | Frais de garde — 1ᵉʳ enfant | 2 340 € | calculé | 11 relevés |
| 2042-RICI | **7DB** | Services à la personne | à saisir | — | 4 factures |
| 2042-RICI | **7DR** | Aides perçues **à déduire** | 1 180 € | calculé | CAF |

Le module d'origine devient une **provenance** affichée sur la ligne, plus un titre de
section. Un basculement « grouper par module » reste possible, mais ce n'est pas la vue par
défaut : elle ne sert qu'au débogage de sa propre situation.

Chaque ligne porte : **le numéro de case en évidence**, le formulaire qui la contient, un
bouton **copier** (via `utils/clipboard.ts` — l'application est en HTTP : le montant s'il est
connu, sinon le numéro de case), et le lien vers la **notice officielle**. Ce lien est une
ancre ordinaire, comme les autres liens d'Administration : c'est l'utilisateur qui ouvre un
onglet, l'application n'émet aucune requête — `netConfirm` couvre les appels que Matothèque
fait elle-même, pas les liens qu'on clique.

### Quand la case dépend de votre situation

C'est le cas le plus fréquent, et **c'est là que l'aide est réelle** : 7GA/7GB/7GC dépendent
du **rang de l'enfant**, la résidence alternée bascule vers d'autres cases, l'âge de l'enfant
à la date de référence conditionne l'éligibilité, 7DB se double de 7DR pour les aides reçues.

Un contributeur a donc le droit de rendre une ligne **`case = None`** accompagnée d'une
**question déterministe** : *« Combien d'enfants de moins de 6 ans avez-vous fait garder en
2026 ? »*, *« Résidence alternée ? »*. La réponse résout la case, **elle est mémorisée pour
l'année**, et la règle appliquée reste visible : *« 2 enfants → 7GA et 7GB »*.

Ces questions sont **codées, pas générées par l'IA** — un arbre de décision daté et sourcé,
relu comme le barème. C'est la différence entre aider et improviser.

## Le vrai sujet technique : « qui devra évoluer dynamiquement »

C'est la partie qui compte, et la seule qui soit un vrai choix d'architecture.

Un onglet fiscal écrit « en dur » vieillirait de la pire façon : chaque nouveau module
touchant à l'argent (emploi à domicile aujourd'hui ; dons, travaux, revenus locatifs, frais
réels demain) obligerait à **rouvrir la page Administration** pour y ajouter une section. Un
jour on oublierait, et l'onglet deviendrait faux par omission — le pire état pour un écran
fiscal, parce que rien à l'écran ne signale ce qui manque.

**Donc l'onglet ne connaît aucun module.** Il affiche ce qu'un **registre de contributeurs**
lui rend. Ajouter un module fiscal = **enregistrer un contributeur**, zéro ligne d'interface.

### Le contrat (une seule chose à implémenter par module)

*Signatures réelles (`services/fiscalite/registre.py`) — ce bloc suit le code, pas l'inverse.*

```python
class ContributeurFiscal(Protocol):
    cle: str            # 'emploi-domicile', 'dons', 'ged-pieces'…
    libelle: str        # « Emploi à domicile »
    async def annees(self, db: AsyncSession) -> list[int]: ...
    async def contributions(self, db: AsyncSession, annee: int,
                            reponses: dict[str, str]) -> list[LigneFiscale]: ...
```

```python
@dataclass
class LigneFiscale:
    formulaire: str         # « 2042-RICI », « 2042 »… — la case seule ne suffit pas à la trouver
    libelle: str
    case: str | None = None        # None tant qu'une `question` n'a pas tranché
    montant: Decimal | None = None # None = « à saisir », et c'est une réponse valable
    nature: str = "piece"          # credit_impot | reduction | revenu | charge | piece | alerte
    confiance: str = "a_saisir"    # calcule | partiel | a_verifier | a_saisir
    sources: list[Source] = ...    # document GED, contrat, fiche — CLIQUABLES
    note: str | None = None        # ce qu'il reste à faire, en français
    question: Question | None = None   # arbre de décision CODÉ, jamais l'IA
    notice_url: str | None = None
    bareme_verifie_le: date | None = None

    def __post_init__(self):
        # La règle n°1 est tenue ICI, pas par la discipline des appelants : un montant
        # qu'on ne peut pas remonter jusqu'à sa pièce ne doit jamais atteindre l'écran,
        # donc jamais être recopié dans une déclaration.
        if self.montant is not None and not self.sources:
            raise ValueError("montant sans source")
```

`GET /api/fiscalite/synthese?annee=2026` parcourt le registre et agrège. L'écran rend
**ce qu'il reçoit** : un contributeur inconnu de lui s'affiche quand même. Un contributeur
qui **lève une exception** est capturé, signalé en pied d'écran, et **ne vide pas** la page.

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
- **Bandeau permanent** : *ce n'est pas une déclaration ; les montants sont à vérifier ; seule
  la notice officielle fait foi.* Rendu par le backend (`millesime.AVERTISSEMENT`), jamais
  optionnel côté écran.

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
- **Aucun montant produit par l'IA**, et **aucune règle de case produite par l'IA** : les
  cases et leurs conditions sont **écrites en dur, datées, sourcées**. L'IA classe et
  retrouve des pièces ; elle ne dit pas où reporter un montant.

> ⚠️ **Le millésime des cases est un contenu daté comme les barèmes.** Les numéros bougent
> peu mais bougent (une case fusionne, une annexe se renomme). Ils vivent donc dans la même
> constante datée, avec le lien vers la notice de l'année, et l'écran affiche **« cases du
> millésime 2026 »**. Une case juste l'an dernier et fausse cette année serait la pire
> erreur de cet onglet — parce qu'elle serait recopiée sans hésiter.

## Phasage

- [x] **Lot 1 — Le registre et la vue par case** *(codé le 09/09)* : `services/fiscalite/registre.py`,
      `GET /api/fiscalite/synthese`, onglet dans Administration **groupé par formulaire puis par
      case** (l'ordre du formulaire, pas celui des modules), bouton copier par ligne, lien notice,
      et correction de la condition d'affichage de la barre latérale. Un contributeur de
      démonstration suffit à prouver le mécanisme.
      *Utile seul : la structure est là, et le jour où un module arrive, il s'affiche.*
- [x] **Lot 1 bis — Résolution de case par questions** *(codé le 09/09)* : arbre de décision codé et daté
      (rang de l'enfant, résidence alternée…), réponses mémorisées pour l'année, règle appliquée
      affichée. C'est ce qui transforme « voici vos montants » en « voici **où** les mettre ».
- [x] **Lot 2 — Contributeur `ged-pieces`** *(codé le 09/09)* : rassembler les pièces fiscales de l'année depuis
      l'indexation existante. Aucune donnée nouvelle à saisir. *Utile seul, et immédiatement.*
- [ ] **Lot 3 — Contributeur `emploi-domicile`** : dépend de la **phase 3** du module (les
      contrats), et surtout de la saisie des montants réellement versés — à cadrer avec la
      phase 4 (simulateur de coût net), qui produit déjà les mêmes chiffres.
- [ ] **Lot 4 — Export PDF récapitulatif** et rappel annuel (jalon, printemps).
