# Plan — Onglet « Nounou » du dossier « Devenir parent »

> Plan de conception (**à coder**), branche `Nounou`. Référencé depuis
> [ROADMAP.md](../ROADMAP.md). But : accompagner **le seul acte où un parent devient
> employeur** — recruter une assistante maternelle, l'interroger, la contracter, la
> déclarer — sans quitter Matothèque et sans sortir sur Internet.

## Pourquoi un onglet, et pas des ressources de plus

Le dossier « Devenir parent » sait aujourd'hui faire deux choses : **lire** (onglet
Ressources : podcasts, livres, articles) et **se situer dans le temps** (onglet Planning :
67 jalons, dont 3 de catégorie `garde`). Le mode de garde n'entre proprement dans ni l'un
ni l'autre, parce qu'il demande un troisième geste : **produire un document opposable**.

Un contrat de travail n'est ni une ressource à lire ni une case à cocher. Il se remplit,
se calcule (la mensualisation est une formule, pas un texte), s'exporte, se signe et se
conserve. Les trois jalons `garde` existants (`-6` lancer les démarches, `+1` confirmer et
demander le CMG, `+30` école maternelle) disent **quand** ; l'onglet dit **comment** — et
c'est là que se joue le passage de parent à **particulier employeur**, avec les obligations
qui vont avec.

## Ce que l'onglet couvre (les 5 demandes, plus ce qui manquait)

| # | Demande | Réponse |
|---|---|---|
| 1 | Droits et devoirs assmat / parents | Fiche « Qui doit quoi » — deux colonnes en vis-à-vis |
| 2 | Questions à poser à l'assistante maternelle | Checklist d'entretien, **cochable par candidate** |
| 3 | Créer un contrat | Formulaire → contrat type **éditable, calculé, téléchargeable** |
| 4 | « Pas chez CESU, emploi service ? » | Fiche déclaration : **Pajemploi**, pas CESU (voir ci-dessous) |
| 5 | Ce qui a été oublié | Assurances · agrément · rupture · régularisation · fin de contrat |

### Sur le point 4 — la réponse courte, parce qu'elle est contre-intuitive

**Non, pas le CESU.** Le CESU (chèque emploi service universel) couvre l'emploi **à
domicile** — ménage, garde d'enfant **chez vous**. Une **assistante maternelle agréée**
garde l'enfant **chez elle** : elle relève de **Pajemploi** (URSSAF), le service dédié aux
modes de garde individuels de la PAJE. C'est Pajemploi qui édite le bulletin de salaire,
calcule les cotisations et sert de porte d'entrée au **CMG** (complément de libre choix du
mode de garde). Les deux dispositifs se ressemblent, ne se substituent pas, et se tromper
de guichet fait perdre le CMG. **La fiche doit énoncer ce contraste en premier** — c'est
l'erreur la plus probable, et elle coûte de l'argent.

> ⚠️ Une **garde à domicile** (la nounou vient chez vous) ou une **garde partagée**
> relèvent bien de Pajemploi aussi (pas du CESU) dès lors qu'il y a un enfant de moins de
> 6 ans et une demande de CMG. Le CESU ne revient que hors CMG. La fiche doit donc trancher
> selon **le lieu de garde et l'âge**, pas selon le mot « nounou ».

### Le point 5 — ce qui manquait à la liste

Rassemblé ici parce que c'est la vraie valeur de l'onglet : ce sont les oublis qui coûtent.

- **Agrément PMI** — délivré par le conseil départemental, durée limitée, **nombre de
  places** et tranches d'âge précisés dessus. À demander et à **photographier dès le
  premier entretien** : sans agrément valide, pas de CMG, et l'accueil est illégal.
- **Assurances** — responsabilité civile professionnelle de l'assmat, **assurance auto
  avec transport d'enfants** si elle conduit, et attestation de l'employeur pour la sienne.
  Pièces à réclamer, pas à supposer.
- **Période d'essai et période d'adaptation** — deux choses distinctes qu'on confond :
  l'adaptation (quelques jours de présence progressive, rémunérée) et l'essai (durée légale
  pendant laquelle chacun peut rompre sans motif).
- **Mensualisation et régularisation** — le salaire est **lissé sur 12 mois**, pas payé à
  l'heure faite. Année **complète** (l'assmat travaille les mêmes semaines que vous)
  ou **incomplète** (moins de semaines) : la formule diffère, et c'est la première source
  d'erreur de paie. À calculer, pas à saisir.
- **Absences, maladie, jours fériés, congés** — qui paie quoi quand l'enfant est absent,
  quand l'assmat l'est, qui pose ses congés et quand (les dates de congés se décident
  souvent avant le 1ᵉʳ mars).
- **Indemnités** — entretien (obligatoire, minimum légal, couvre jeux/eau/électricité),
  repas, kilométriques. Ce ne sont **pas** du salaire, elles ne se cotisent pas.
- **Documents à échanger** — carnet de vaccination, autorisations (sortie, transport,
  photos, soins d'urgence), **PAI** si allergie ou traitement.
- **Fin de contrat** — « retrait de l'enfant », préavis, **indemnité de rupture**,
  régularisation du lissé, solde de tout compte, certificat de travail, attestation
  France Travail. La fin se prépare dans le contrat, pas au moment de la rupture.
- **Le coût réel** — brut, net, cotisations prises en charge, CMG, **crédit d'impôt** : le
  chiffre qui décide entre crèche, MAM et assmat n'est aucun de ceux affichés isolément.
- **Les alternatives** — crèche, micro-crèche, MAM, garde à domicile (partagée ou non) :
  une comparaison honnête, avec le fait que les délais d'inscription en crèche tombent bien
  avant que la question ne se pose.

## Contenu réglementaire : la règle qui tient tout

**Tout chiffre affiché porte sa date et sa source, ou n'est pas affiché.**

Les montants (SMIC, minimum d'entretien, plafond du crédit d'impôt, barème CMG), les
durées de préavis et les formules changent au moins une fois par an — et le CMG est en
cours de réforme. Un contrat généré à partir d'un chiffre périmé est pire qu'un contrat
vide : il a l'air juste.

Donc, dans le code :

- Les valeurs numériques vivent dans **une seule constante datée** (`BAREME_2026` avec un
  champ `verifie_le` et un lien officiel par ligne), pas dispersées dans les fiches.
- L'écran affiche en tête **« Barème vérifié le JJ/MM/AAAA »** et **vieillit visiblement**
  au-delà de 12 mois, comme l'agenda affiche déjà l'âge de ses données *(v1.74.1)*.
- Le contrat exporté **imprime cette date** dans son pied de page.
- Bandeau permanent : **ce n'est pas un conseil juridique**, la convention collective et le
  code du travail font foi.

Cela rejoint le point déjà ouvert dans la ROADMAP : *« Vérifier le contenu réglementaire à
chaque rentrée »*. L'onglet Nounou le rend enfin **mesurable** — une date à l'écran.

## Découpage en phases

### Phase 1 — Savoir (lecture seule, aucune table)

Onglet **Nounou** dans `DossierDetailPage`, à côté de Ressources et Planning. Affiché
uniquement quand le dossier le mérite (voir « Question ouverte » plus bas).

- **Fiche « Droits et devoirs »** — deux colonnes en vis-à-vis (employeur / assistante
  maternelle), sections : avant l'accueil · au quotidien · paie · absences · fin de contrat.
- **Fiche « Déclarer et payer »** — Pajemploi vs CESU, CMG, crédit d'impôt, Pajemploi+.
- **Fiche « Comparer les modes de garde »**.
- **Checklist d'entretien** — imprimable, sans état encore.

Contenu livré dans `backend/services/nounou_contenu.py` (structures Python, comme
`jalon_seed`), servi par `GET /api/nounou/fiches`. **Aucune migration**, aucune écriture.
Les liens officiels sortent par `netConfirm`, comme partout ailleurs.

*Livrable : on peut lire et imprimer. Utile seul.*

### Phase 2 — Comparer (checklist par candidate)

- Table `nounou_candidats` : nom, contact, commune, agrément (n°, validité, places),
  tarif annoncé, disponibilité, statut (`a_contacter` | `entretien` | `retenue` | `ecartee`),
  note libre.
- Réponses de la checklist en **JSONB sur le candidat** (`reponses: {cle: {ok, texte}}`) —
  pas de table de réponses : Matothèque est mono-utilisateur, une jointure de plus
  n'apporterait rien (même raisonnement que le suivi porté par la ligne `jalons`).
- Écran : une colonne par candidate, une ligne par question, **comparaison à l'œil**.
- Export de la comparaison (markdown → PDF via l'existant).

*Livrable : on choisit sur des faits notés pendant l'entretien, pas de mémoire.*

### Phase 3 — Contracter (le cœur)

- Table `contrats_garde` : `candidat_id`, `champs` JSONB, `statut` (`brouillon` | `signe`),
  `genere_le`, `barème_utilise` (la date du barème, gelée à la génération).
- **Formulaire calculant**, pas formulaire de saisie :
  - année complète / incomplète → **mensualisation calculée** et montrée avec sa formule ;
  - heures hebdo + semaines → heures mensualisées, majorations au-delà de 45 h ;
  - indemnités d'entretien / repas / km calculées depuis le barème daté ;
  - contrôle du **plancher légal** du salaire horaire, avec message explicite si en dessous.
- **Contrat type éditable** : le texte se relit et se modifie à l'écran avant export
  (même geste que le résumé IA d'une ressource — l'application propose, l'humain assume).
- **Export DOCX et PDF** par les briques déjà en place (`docxtpl`, WeasyPrint,
  `POST /api/export/{docx,pdf}`) — rien de neuf à installer.
- **Dépôt en GED** du contrat généré, pour qu'il soit retrouvable comme le reste.
- Annexes générées avec : autorisations, engagement réciproque, fiche de renseignements.

*Livrable : la demande n°3, entière.*

### Phase 4 — Déclarer et suivre

- **Simulateur de coût net** : brut → net → cotisations → CMG → crédit d'impôt, en une
  colonne, avec le reste à charge mensuel réel. C'est le chiffre qui décide.
- **Jalons ajoutés au planning** (catégorie `garde`, mécanisme existant) : déclaration
  Pajemploi du mois, dates de congés à arrêter, renouvellement d'agrément, régularisation
  annuelle.
- **Rappel de fraîcheur** du barème (rejoint le point ROADMAP ouvert).

## Ce qu'on ne fait pas

- **Aucun appel à Pajemploi, à la CAF ou à un service en ligne.** Matothèque reste locale ;
  les liens s'ouvrent dans le navigateur après confirmation, comme le reste du produit.
- **Aucune signature électronique.** Le contrat s'imprime et se signe.
- **Aucun conseil juridique généré par l'IA.** L'IA peut aider à *rédiger une clause
  particulière* ou *résumer une fiche* — jamais à produire le socle réglementaire, qui est
  du contenu livré, daté et relu. Un LLM local qui invente un préavis est indétectable.
- **Pas de paie.** On produit un contrat et un coût prévisionnel ; les bulletins sont
  émis par Pajemploi, et le refaire serait faux.

## Question ouverte à trancher avant de coder

**Où vit l'onglet ?** Trois lectures possibles :

1. **Onglet du dossier `devenir-parent`** (affiché si `slug === 'devenir-parent'`) —
   le plus simple, le plus littéral vis-à-vis de la demande, mais un `if` sur un slug est
   une dette : le jour où le sujet vaut pour un autre dossier, il faut y revenir.
2. **Capacité déclarée sur le dossier** (`modules: ['planning', 'nounou']` en base) — même
   rendu, mais le mécanisme reste générique comme l'est déjà le planning.
3. **Sous-dossier « Mode de garde »** avec ses propres ressources — cohérent avec la
   hiérarchie existante, mais un sous-dossier ne sait pas produire un contrat.

**Recommandation : (2)**, pour la même raison qui a fait du planning un mécanisme générique
plutôt qu'un écran « Devenir parent ». Coût : une colonne et une migration. À valider.

## Briques réutilisées (rien d'exotique)

Onglets de `DossierDetailPage` · pattern de seed daté (`jalon_seed`) · suivi porté par la
ligne (`fait` / `note_perso`) · export DOCX/PDF existant · `docxtpl` déjà en dépendance ·
dépôt GED · `netConfirm` pour les liens officiels · helpers `utils/uuid` et
`utils/clipboard` (l'app est servie en **HTTP** : `crypto.randomUUID` et
`navigator.clipboard` sont absents).
