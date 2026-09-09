"""
Contributeur « emploi-domicile » — ce que vos contrats et votre journal savent déjà
===================================================================================
Le lot 3 du plan fiscal, resté en attente du **journal mensuel** — parce qu'il attendait une
réponse à une question précise, écrite en toutes lettres dans la ROADMAP :

> *D'où viennent les montants réellement versés ? Le contrat donne un prévisionnel
> mensualisé ; la déclaration veut le réalisé de l'année.*

Le journal y répond. Ce contributeur n'invente donc rien : il additionne des mois **saisis
par l'utilisateur** et multiplie par des tarifs **écrits dans son contrat**.

## Ce qu'il apporte, et qui manquait

`ged-pieces` sait retrouver une attestation Pajemploi et dire dans quelle case elle va. Il ne
sait pas **quelle case pour QUI** : c'est le **lieu de travail** qui décide, pas le métier —
une garde chez l'assistante maternelle va en 7GA, la même garde chez vous va en 7DB. Le
profil du contrat porte déjà cette information (`Profil.lieu`), et personne ne l'utilisait.

## Trois refus qui font la valeur du module

1. **Aucun montant sur une année incomplète.** Onze mois saisis donnent un total qui *a l'air*
   d'une année — et c'est celui-là qu'on recopierait. Tant que les douze mois n'y sont pas,
   la ligne dit la case et compte les mois manquants, sans chiffre.
2. **Le total n'est pas le montant à déclarer**, et la ligne le dit : les aides perçues (CMG,
   avance immédiate du crédit d'impôt) s'en déduisent, et c'est l'oubli le plus fréquent du
   dispositif. L'**attestation fiscale** annuelle de Pajemploi ou du CESU donne le chiffre
   exact ; ce total sert à la **contrôler**, pas à la remplacer.
3. **On ne devine pas l'âge de l'enfant.** Le passage des 6 ans change de case en cours
   d'année ; la ligne le signale au lieu de choisir à la place de l'utilisateur.

⚠️ Comme partout dans cet onglet : aucun appel à l'IA, aucun montant lu dans un document.
Seulement de l'arithmétique sur des données saisies, avec ses sources à portée de clic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.dossier import DossierThematique
from models.emploi_domicile import Contrat, Intervenant, MoisTravaille
from services.emploi_domicile import profils
from services.fiscalite import millesime
from services.fiscalite.registre import LigneFiscale, Option, Question, Source

log = get_logger(__name__)

# La question du rang de l'enfant est **la même clé** que celle de `ged-pieces` : c'est la
# même question, posée à la même personne pour la même année. Deux clés distinctes la feraient
# poser deux fois, et autoriseraient deux réponses contradictoires sur le même écran.
QUESTION_RANG = Question(
    cle="nb_enfants_garde_hors_domicile",
    intitule="Combien d'enfants avez-vous fait garder hors de votre domicile ?",
    options=[Option("1", "1 enfant"), Option("2", "2 enfants"), Option("3", "3 enfants et plus")],
    aide="Il y a une case par enfant (7GA, puis 7GB, puis 7GC). Seuls les enfants de moins "
         "de 6 ans ouvrent droit au crédit d'impôt.",
)

CASES_HORS_DOMICILE = ("7GA", "7GB", "7GC")
CASE_A_DOMICILE = "7DB"
CASE_AIDES = "7DR"


def _dec(valeur) -> Decimal | None:
    """Décimal tolérant sur les champs libres du contrat (« 4,20 » comme « 4.20 »)."""
    if valeur is None or str(valeur).strip() == "":
        return None
    try:
        return Decimal(str(valeur).strip().replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def _euros(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Verse:
    """
    Ce qu'un contrat a coûté sur une année, d'après le journal.

    Décomposé plutôt que rendu en un seul total : c'est la décomposition qui permet de
    confronter le chiffre à l'attestation fiscale, ligne à ligne, quand les deux diffèrent.
    """

    def __init__(self) -> None:
        self.salaire = Decimal("0")
        self.entretien = Decimal("0")
        self.repas = Decimal("0")
        self.km = Decimal("0")
        self.mois_saisis = 0
        self.detail: list[str] = []

    @property
    def total(self) -> Decimal:
        return _euros(self.salaire + self.entretien + self.repas + self.km)

    @property
    def complet(self) -> bool:
        return self.mois_saisis == 12


def _cumuler(contrat: Contrat, mois: list[MoisTravaille]) -> Verse:
    """
    Additionne l'année, aux tarifs du contrat.

    Les indemnités sont comptées **au réel** (jours d'accueil × entretien, repas × tarif),
    pas au forfait mensuel du contrat : le forfait est une estimation faite avant de
    commencer, le journal dit ce qui a eu lieu. C'est toute la raison d'être du journal.
    """
    champs = contrat.champs or {}
    taux = _dec(champs.get("taux_horaire"))
    entretien_jour = _dec(champs.get("entretien_jour"))
    repas_jour = _dec(champs.get("repas_jour"))
    tarif_km = _dec(champs.get("tarif_km"))

    v = Verse()
    heures = sum((m.heures for m in mois if m.heures is not None), Decimal("0"))
    jours = sum(m.jours_accueil or 0 for m in mois)
    repas = sum(m.repas or 0 for m in mois)
    kms = sum((m.km for m in mois if m.km is not None), Decimal("0"))
    v.mois_saisis = sum(1 for m in mois
                        if any(x is not None for x in (m.heures, m.jours_accueil, m.repas, m.km)))

    if taux and heures:
        v.salaire = _euros(heures * taux)
        v.detail.append(f"Salaire : {heures} h × {taux} € = {v.salaire} €")
    if entretien_jour and jours:
        v.entretien = _euros(Decimal(jours) * entretien_jour)
        v.detail.append(f"Entretien : {jours} jours × {entretien_jour} € = {v.entretien} €")
    if repas_jour and repas:
        v.repas = _euros(Decimal(repas) * repas_jour)
        v.detail.append(f"Repas : {repas} × {repas_jour} € = {v.repas} €")
    if tarif_km and kms:
        v.km = _euros(kms * tarif_km)
        v.detail.append(f"Kilomètres : {kms} km × {tarif_km} € = {v.km} €")
    return v


def _resoudre_rang(reponses: dict[str, str]) -> tuple[list[str], Question | None]:
    """Cases de garde hors domicile retenues, ou la question qui les tranche."""
    reponse = (reponses.get(QUESTION_RANG.cle) or "").strip()
    if not reponse:
        return [], QUESTION_RANG
    if reponse.isdigit():
        n = max(1, min(int(reponse), len(CASES_HORS_DOMICILE)))
        return list(CASES_HORS_DOMICILE[:n]), None
    if reponse in CASES_HORS_DOMICILE:
        return [reponse], None
    return [], QUESTION_RANG


class EmploiDomicile:
    """Contributeur fiscal : les contrats d'emploi à domicile et leur journal."""

    cle = "emploi-domicile"
    libelle = "Contrats d'emploi à domicile"

    async def _contrats(self, db: AsyncSession) -> list[tuple[Contrat, Intervenant, str | None]]:
        """
        Les contrats, avec la personne et le slug du dossier qui les porte.

        Le slug sert à **fabriquer le lien de retour** vers l'écran du contrat : une ligne
        fiscale qui cite un contrat sans permettre de l'ouvrir oblige à le retrouver à la
        main, exactement ce que cet onglet prétend éviter.
        """
        lignes = (await db.execute(
            select(Contrat, Intervenant, DossierThematique.slug)
            .join(Intervenant, Contrat.intervenant_id == Intervenant.id)
            .join(DossierThematique, Intervenant.dossier_id == DossierThematique.id)
        )).all()
        return [(c, i, slug) for c, i, slug in lignes]

    async def annees(self, db: AsyncSession) -> list[int]:
        """Les années où le journal a quelque chose à dire — aucune autre n'apporterait rien."""
        annees = (await db.execute(select(MoisTravaille.annee).distinct())).scalars().all()
        return sorted({a for a in annees if a}, reverse=True)

    async def contributions(
        self, db: AsyncSession, annee: int, reponses: dict[str, str]
    ) -> list[LigneFiscale]:
        contrats = await self._contrats(db)
        if not contrats:
            return []

        mois_par_contrat: dict = {}
        for m in (await db.execute(
            select(MoisTravaille).where(MoisTravaille.annee == annee)
        )).scalars().all():
            mois_par_contrat.setdefault(m.contrat_id, []).append(m)

        # Deux destinations, décidées par le LIEU du profil — pas par le métier. C'est la
        # distinction que le formulaire fait et qu'on rate le plus souvent.
        hors_domicile: list[tuple] = []
        a_domicile: list[tuple] = []
        for contrat, intervenant, slug in contrats:
            profil = profils.profil(contrat.profil or intervenant.profil)
            verse = _cumuler(contrat, mois_par_contrat.get(contrat.id, []))
            # **C'est le journal qui rattache un contrat à une année, pas son statut.** Un
            # contrat signé en 2025 n'a rien à dire de 2024, et le statut ne porte aucune date
            # qui permettrait de le savoir. Un brouillon jamais alimenté disparaît de même :
            # une simulation affichée parmi des montants réels serait indiscernable d'un
            # versement. Le silence, lui, reste visible — l'onglet affiche « rien pour cette
            # année » plutôt que de masquer le contributeur.
            if verse.mois_saisis == 0:
                continue
            (hors_domicile if profil.lieu == "chez elle" else a_domicile).append(
                (contrat, intervenant, slug, profil, verse))

        lignes: list[LigneFiscale] = []
        lignes += self._lignes_hors_domicile(annee, hors_domicile, reponses)
        lignes += self._lignes_a_domicile(annee, a_domicile)
        return lignes

    # ─── Garde hors domicile : 7GA / 7GB / 7GC ────────────────────────────────────────

    def _lignes_hors_domicile(self, annee: int, groupe: list[tuple],
                              reponses: dict[str, str]) -> list[LigneFiscale]:
        if not groupe:
            return []
        cases, question = _resoudre_rang(reponses)
        sources, note_montants, montant = self._synthese(annee, groupe)

        rappel = (
            " Le passage des 6 ans de l'enfant change de case en cours d'année : Matothèque "
            "ne connaît pas cet âge et ne tranche donc pas à votre place."
        )

        if question is not None:
            return [LigneFiscale(
                formulaire=millesime.formulaire_de(CASES_HORS_DOMICILE[0]),
                case=None,
                libelle="Frais de garde hors domicile — d'après vos contrats",
                nature="piece",
                confiance="a_verifier",
                sources=sources,
                note=note_montants + " La case dépend du nombre d'enfants gardés — "
                     "répondez ci-dessous." + rappel,
                question=question,
                notice_url=millesime.URL_IMPOTS,
                bareme_verifie_le=millesime.VERIFIE_LE,
            )]

        lignes = []
        for i, code in enumerate(cases):
            c = millesime.case(code)
            lignes.append(LigneFiscale(
                formulaire=millesime.formulaire_de(code),
                case=code,
                libelle=c.libelle if c else "Frais de garde hors domicile",
                # Le montant n'est porté que par la PREMIÈRE case : le répartir entre les
                # enfants demanderait de savoir lequel a été gardé combien, ce que le journal
                # ne dit pas — un contrat ne nomme pas l'enfant.
                montant=montant if i == 0 else None,
                nature="credit_impot",
                confiance=("calcule" if montant is not None else "a_saisir") if i == 0 else "a_saisir",
                sources=sources if i == 0 else [],
                note=(note_montants + rappel) if i == 0
                     else "Répartissez selon l'enfant concerné.",
                notice_url=millesime.URL_IMPOTS,
                bareme_verifie_le=millesime.VERIFIE_LE,
            ))
        return lignes

    # ─── Emploi à votre domicile : 7DB, et les aides en 7DR ───────────────────────────

    def _lignes_a_domicile(self, annee: int, groupe: list[tuple]) -> list[LigneFiscale]:
        if not groupe:
            return []
        sources, note_montants, montant = self._synthese(annee, groupe)
        c = millesime.case(CASE_A_DOMICILE)
        cc = millesime.case(CASE_AIDES)
        return [
            LigneFiscale(
                formulaire=millesime.formulaire_de(CASE_A_DOMICILE),
                case=CASE_A_DOMICILE,
                libelle=c.libelle if c else "Sommes versées pour un salarié à domicile",
                montant=montant,
                nature="credit_impot",
                confiance="calcule" if montant is not None else "a_saisir",
                sources=sources,
                note=note_montants,
                notice_url=millesime.URL_IMPOTS,
                bareme_verifie_le=millesime.VERIFIE_LE,
            ),
            LigneFiscale(
                formulaire=millesime.formulaire_de(CASE_AIDES),
                case=CASE_AIDES,
                libelle=cc.libelle if cc else "Aides perçues — à déduire",
                nature="credit_impot",
                confiance="a_saisir",
                note="Matothèque ne connaît pas les aides que vous avez perçues (CMG, APA, "
                     "PCH, comité d'entreprise, avance immédiate du crédit d'impôt). Elles se "
                     "reportent ici, et se déduisent de la somme déclarée ci-dessus.",
                notice_url=millesime.URL_IMPOTS,
                bareme_verifie_le=millesime.VERIFIE_LE,
            ),
        ]

    # ─── Le cœur : additionner, et dire ce que le total vaut ──────────────────────────

    def _synthese(self, annee: int, groupe: list[tuple]
                  ) -> tuple[list[Source], str, Decimal | None]:
        """
        Sources, note et montant d'un groupe de contrats.

        **Le montant n'est rendu que si TOUS les contrats du groupe ont leurs douze mois.**
        Un seul contrat incomplet suffit à retirer le chiffre : un total à onze mois ressemble
        à une année, et c'est celui-là qu'on recopierait sans y penser.
        """
        sources: list[Source] = []
        detail: list[str] = []
        manquants: list[str] = []
        total = Decimal("0")
        tout_complet = True

        for contrat, intervenant, slug, profil, verse in groupe:
            qui = " ".join(x for x in (intervenant.prenom, intervenant.nom) if x) or contrat.titre
            sources.append(Source(
                libelle=f"{qui} — {profil.libelle}",
                type="contrat",
                ref=str(contrat.id),
                # L'écran du contrat se choisit par la PERSONNE, pas par le contrat : le lien
                # doit parler la langue de l'écran d'arrivée, sinon il ouvre le bon dossier
                # au mauvais endroit.
                lien_interne=(f"/dossiers/{slug}?onglet=contrat&personne={intervenant.id}"
                              if slug else None),
                annee=annee,
                annee_confirmee=True,   # l'année vient du journal, pas d'une date de fichier
            ))
            if verse.complet and verse.total > 0:
                total += verse.total
                detail.append(f"{qui} : {verse.total} € ({' · '.join(verse.detail)})")
            else:
                tout_complet = False
                manquants.append(f"{qui} ({verse.mois_saisis}/12 mois saisis)")

        if tout_complet and total > 0:
            note = (
                f"Total versé en {annee} d'après votre journal : {_euros(total)} €. "
                + " ".join(detail)
                + " ⚠️ Ce n'est pas forcément le montant à déclarer : les aides perçues "
                "(CMG, avance immédiate du crédit d'impôt) s'en déduisent, et l'attestation "
                "fiscale annuelle de Pajemploi ou du CESU donne le chiffre qui fait foi. "
                "Ce total sert à la contrôler."
            )
            return sources, note, _euros(total)

        note = (
            "Aucun montant n'est calculé : le journal n'est pas complet pour "
            f"{annee} — " + ", ".join(manquants) + ". Un total à onze mois ressemble à une "
            "année entière, et c'est celui-là qui serait recopié. Complétez le journal dans "
            "l'onglet du contrat, ou reportez le montant de votre attestation fiscale."
        )
        return sources, note, None


def installer() -> None:
    from services.fiscalite.registre import enregistrer
    enregistrer(EmploiDomicile())
