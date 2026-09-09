# Plan — Onglet « Nounou » du dossier « Devenir parent »

> Plan de conception (**à coder**), branche `Nounou`. Référencé depuis
> [ROADMAP.md](../ROADMAP.md). But : accompagner **le seul acte où un parent devient
> employeur** — recruter une assistante maternelle, l'interroger, la contracter, la
> déclarer — sans quitter Matothèque et sans sortir sur Internet.
>
> ⚠️ **Le module s'appelle `emploi-domicile`, pas `nounou`.** « Nounou » est le **libellé de
> son premier profil**, celui qui s'affiche dans « Devenir parent ». La raison tient en une
> ligne : employer une **aide ménagère** relève de la **même convention collective** que
> l'assistante maternelle, avec le **même contrat**, les **mêmes obligations** — et un
> **guichet différent** (CESU au lieu de Pajemploi). Voir « Le CESU » plus bas.

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
| 4 | « Pas chez CESU, emploi service ? » | Fiche « Quel guichet ? » : **Pajemploi** ici, **CESU** pour l'aide à domicile |
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

## Le CESU — l'autre moitié du sujet, et où elle s'intègre

Le CESU n'est pas seulement le mauvais guichet de l'assistante maternelle. C'est **le bon
guichet d'un autre besoin, tout aussi réel** : aide ménagère, femme de ménage, repassage,
jardinage, soutien scolaire, aide aux personnes âgées, bricolage — tout ce qu'on appelle
**services à la personne**, exécuté **chez soi**. Ce jour-là, on redevient particulier
employeur, avec les mêmes obligations et un contrat très proche.

**Le fait structurant qui décide de l'architecture** : les deux relèvent de la **même
convention collective**, celle des *particuliers employeurs et de l'emploi à domicile*, qui
porte **deux socles** — « salariés du particulier employeur » (aide ménagère, garde
d'enfants à domicile…) et « assistants maternels ». Contrat de travail, période d'essai,
congés payés, préavis, fin de contrat, obligations déclaratives : **la charpente est la
même**. Ne changent vraiment que le **guichet**, le **barème**, l'**aide** et quelques
clauses (les indemnités d'entretien n'existent que chez l'assmat, l'agrément PMI non plus).

Écrire deux modules serait donc dupliquer 70 % du travail pour 30 % de différence — et
condamner l'un des deux à vieillir seul.

### Où ça s'intègre, concrètement — trois décisions

**1. Le module se nomme `emploi-domicile` dès la première ligne de code.** L'onglet porte le
libellé de son **profil** (« Nounou » dans « Devenir parent »), jamais le nom du module.
Renommer plus tard une table, une route et un composant coûte bien plus qu'un bon nom tout
de suite — et l'onglet, lui, ne change pas de nom aux yeux de l'utilisateur.

**2. Le `profil` est une donnée, pas un écran** :

| Profil | Lieu | Guichet | Aide |
|---|---|---|---|
| `assmat` | chez elle | **Pajemploi** | CMG |
| `garde_domicile` | chez vous, enfant < 6 ans | **Pajemploi** | CMG |
| `aide_domicile` | chez vous | **CESU** | Crédit d'impôt SAP (avance immédiate) |
| `autre_sap` | chez vous | **CESU** | Crédit d'impôt SAP |

C'est cette table — et elle seule — qui pilote le guichet, le barème, le gabarit de contrat
et les clauses optionnelles. Ajouter un profil = ajouter une ligne.

**3. La fiche « Quel guichet ? » est générique DÈS la phase 1.** C'est le meilleur endroit,
et il ne coûte rien : la question se pose **dans les deux sens** (un foyer qui prend une
nounou prend souvent aussi une aide ménagère), elle se pose **au moment où on lit la
fiche**, et une fiche qui ne parlerait que de Pajemploi laisserait croire que le CESU n'a
jamais sa place. Un tableau de décision **lieu × âge × nature du service** répond aux deux
publics en un écran.

### Ce que le profil `aide_domicile` apporte de spécifique (à ne pas oublier le jour venu)

- **Emploi direct / mandataire / prestataire** — *la* décision structurante, et elle vient
  avant toutes les autres : on n'est **particulier employeur qu'en direct ou en mandataire**.
  En prestataire, on achète une prestation à une société : pas de contrat de travail, pas de
  déclaration, pas de licenciement à gérer. Beaucoup de gens croient employer quelqu'un alors
  qu'ils sont clients d'une entreprise — ou l'inverse, ce qui est plus grave.
- **Crédit d'impôt services à la personne** — 50 % des dépenses, plafond annuel propre
  (distinct de celui de la garde d'enfant), et **avance immédiate** via le CESU : le crédit
  se déduit à chaque paie au lieu d'être remboursé l'année suivante.
- **CESU déclaratif ≠ CESU préfinancé** — le premier est le service de déclaration URSSAF,
  le second un titre payé par un employeur ou un organisme social. Deux choses différentes
  sous un même sigle, source de confusion garantie.
- **Aides à l'autonomie** — APA, PCH, caisse de retraite, mutuelle : quand l'aide ménagère
  accompagne une perte d'autonomie, le financement ne passe plus par le seul crédit d'impôt.
- **Cumul d'employeurs** — une aide ménagère travaille presque toujours pour plusieurs
  foyers : le temps partiel, ses contraintes de planning et le plafond d'heures s'anticipent
  au contrat, pas après.

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
  Le tronc commun (contrat, essai, congés, préavis, fin) est écrit **une fois pour tous les
  profils** ; ce qui est propre à l'assmat (agrément, indemnité d'entretien) est marqué comme tel.
- **Fiche « Quel guichet ? » — générique** : tableau de décision **lieu × âge × nature du
  service** → Pajemploi ou CESU, CMG ou crédit d'impôt SAP, Pajemploi+ / avance immédiate,
  et le rappel emploi direct / mandataire / prestataire. Couvre **les deux publics** (cf. « Le
  CESU » ci-dessus) : c'est là que la question se pose, et elle se pose dans les deux sens.
- **Fiche « Comparer les modes de garde »**.
- **Checklist d'entretien** — imprimable, sans état encore.

Contenu livré dans `backend/services/emploi_domicile_contenu.py` (structures Python, comme
`jalon_seed`), servi par `GET /api/emploi-domicile/fiches?profil=assmat`. **Aucune
migration**, aucune écriture. Les liens officiels sortent par `netConfirm`, comme partout
ailleurs. Seul le profil `assmat` est rempli en phase 1 — les autres existent dans la table
des profils et affichent honnêtement « pas encore documenté » plutôt que rien.

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
- **Un gabarit par profil**, bâti sur un **tronc commun** (identité des parties, essai,
  horaires, salaire, congés, préavis, rupture) + des **blocs optionnels** activés par le
  profil (agrément et indemnité d'entretien pour `assmat` ; lieu d'exécution et tâches
  détaillées pour `aide_domicile`). Le contrat gèle aussi le **profil** utilisé, pas
  seulement la date du barème — un contrat ne se relit pas avec les règles d'un autre métier.
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

### Phase 5 — Le profil `aide_domicile` (CESU), quand le besoin est là

Rien de neuf à construire : remplir le contenu du profil (fiches, checklist d'embauche,
blocs de contrat, barème et aides) et lui donner un dossier hôte. **Aucun dossier « vie
pratique » n'existe aujourd'hui** — seuls `mon-bebe` et `devenir-parent` sont livrés — donc
la phase inclut un seed léger **« Employer chez soi »** portant la capacité avec le profil
`aide_domicile`, et l'onglet s'y appelle « Aide à domicile ».

C'est la vérification que l'architecture tient : si la phase 5 demande plus que du contenu
et un seed, c'est que les phases 1 à 3 ont codé « nounou » là où elles devaient coder
« emploi à domicile ».

## Ce qu'on ne fait pas

- **Aucun appel à Pajemploi, à la CAF ou à un service en ligne.** Matothèque reste locale ;
  les liens s'ouvrent dans le navigateur après confirmation, comme le reste du produit.
- **Aucune signature électronique.** Le contrat s'imprime et se signe.
- **Aucun conseil juridique généré par l'IA.** L'IA peut aider à *rédiger une clause
  particulière* ou *résumer une fiche* — jamais à produire le socle réglementaire, qui est
  du contenu livré, daté et relu. Un LLM local qui invente un préavis est indétectable.
- **Pas de paie.** On produit un contrat et un coût prévisionnel ; les bulletins sont
  émis par Pajemploi, et le refaire serait faux.

## Décision actée — où vit l'onglet (validé le 09/09/2026)

**Capacité déclarée sur le dossier**, en base : `dossiers_thematiques.modules`
(`['planning', 'emploi-domicile']`) + le **profil** retenu pour ce dossier. Une colonne, une
migration.

Écartées : le `if slug === 'devenir-parent'` (littéral, mais il faut y revenir dès le
deuxième dossier concerné — et la phase 5 est précisément ce deuxième dossier, donc la dette
serait contractée en sachant déjà quand on la paierait) ; et le sous-dossier « Mode de
garde », cohérent avec la hiérarchie mais incapable de produire un contrat.

Même raison qui a fait du planning un mécanisme générique plutôt qu'un écran « Devenir
parent » : l'onglet apparaît **là où le dossier le déclare**, et « Employer chez soi » (phase
5) n'aura qu'à déclarer la même capacité avec un autre profil.

## Briques réutilisées (rien d'exotique)

Onglets de `DossierDetailPage` · pattern de seed daté (`jalon_seed`) · suivi porté par la
ligne (`fait` / `note_perso`) · export DOCX/PDF existant · `docxtpl` déjà en dépendance ·
dépôt GED · `netConfirm` pour les liens officiels · helpers `utils/uuid` et
`utils/clipboard` (l'app est servie en **HTTP** : `crypto.randomUUID` et
`navigator.clipboard` sont absents).
