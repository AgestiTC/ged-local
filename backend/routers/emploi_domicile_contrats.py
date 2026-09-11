"""
Router Contrats — /api/emploi-domicile (contrats de travail)
============================================================
Phase 3 du module : produire un **document opposable**. C'est le geste que ni les fiches ni
les entretiens ne rendaient, et celui pour lequel tout le reste existait.

  GET    /emploi-domicile/intervenants/{iid}/contrats  → les contrats d'une personne
  POST   /emploi-domicile/intervenants/{iid}/contrats  → créer, pré-rempli depuis la fiche
  GET    /emploi-domicile/contrats/{cid}               → contrat + calculs + alertes
  PATCH  /emploi-domicile/contrats/{cid}               → champs, statut, texte corrigé
  POST   /emploi-domicile/contrats/{cid}/generer       → (re)génère le texte Markdown
  DELETE /emploi-domicile/contrats/{cid}

## Deux principes qui décident du reste

**Le formulaire calcule, il ne fait pas saisir.** Le salaire d'une assistante maternelle est
*mensualisé* — lissé sur douze mois — et le demander directement reviendrait à faire faire
le calcul par l'utilisateur, là où les contrats se trompent le plus. Chaque montant sort
donc avec **sa formule en toutes lettres** (voir `services/emploi_domicile/calcul`).

**Le texte généré est un brouillon, pas un verdict.** Il se relit et se corrige à l'écran ;
`PATCH` avec `texte` enregistre la version corrigée, et une régénération ultérieure ne
l'écrase **que si on la demande explicitement**. Un contrat amendé ne doit pas se faire
réécrire par un recalcul — surtout pas après signature.

⚠️ **Aucun montant réglementaire n'est livré en dur.** Le SMIC et le minimum garanti
viennent des Paramètres, saisis et datés par l'utilisateur. Sans eux, les calculs
fonctionnent ; seuls les **contrôles de plancher** sont désactivés — et l'API rend alors une
alerte disant que le contrôle n'a **pas eu lieu**, plutôt que de se taire.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.config import Config
from models.emploi_domicile import Contrat, Intervenant
from services.emploi_domicile import annexes, calcul, contrat as gabarit, cout
from services.emploi_domicile.profils import profil as get_profil

log = get_logger(__name__)
router = APIRouter()

STATUTS = ("brouillon", "a_signer", "signe", "termine")


class ContratIn(BaseModel):
    titre: str | None = None
    champs: dict = Field(default_factory=dict)


class ContratPatch(BaseModel):
    titre: str | None = None
    statut: str | None = None
    champs: dict | None = None
    # Le texte corrigé à la main. Fourni seul, il ne déclenche aucun recalcul.
    texte: str | None = None


class GenererIn(BaseModel):
    # Garde-fou explicite : régénérer efface les corrections manuelles. On refuse de le faire
    # par accident sur un contrat déjà relu.
    ecraser: bool = False


def _dec(valeur, defaut: Decimal | None = None) -> Decimal | None:
    """Décimal tolérant : « 4,20 » comme « 4.20 ». Un champ vide vaut `defaut`, pas zéro."""
    if valeur is None or str(valeur).strip() == "":
        return defaut
    try:
        return Decimal(str(valeur).strip().replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return defaut


def _entier(valeur, defaut: int = 0) -> int:
    d = _dec(valeur)
    return int(d) if d is not None else defaut


async def _bareme(db: AsyncSession) -> dict:
    """Le barème saisi dans les Paramètres. Absent = contrôles désactivés, pas contrôles OK."""
    cles = ("bareme_smic_horaire", "bareme_minimum_garanti", "bareme_verifie_le")
    lignes = (await db.execute(select(Config).where(Config.cle.in_(cles)))).scalars().all()
    brut = {l.cle: l.valeur for l in lignes}
    return {
        "smic_horaire": _dec(brut.get("bareme_smic_horaire")),
        "minimum_garanti": _dec(brut.get("bareme_minimum_garanti")),
        "verifie_le": brut.get("bareme_verifie_le") or None,
    }


async def _profil_employeur(db: AsyncSession) -> gabarit.Partie:
    """Les coordonnées de l'utilisateur (Paramètres → Vos coordonnées) — l'en-tête du contrat."""
    cles = ("profil_adresse", "profil_code_postal", "profil_ville",
            "profil_email", "profil_telephone", "profil_nom")
    lignes = (await db.execute(select(Config).where(Config.cle.in_(cles)))).scalars().all()
    c = {l.cle: (l.valeur or "").strip() for l in lignes}
    adresse = ", ".join(x for x in (c.get("profil_adresse"),
                                    " ".join(x for x in (c.get("profil_code_postal"),
                                                         c.get("profil_ville")) if x)) if x)
    return gabarit.Partie(
        nom=c.get("profil_nom") or None,
        adresse=adresse or None,
        telephone=c.get("profil_telephone") or None,
        email=c.get("profil_email") or None,
    )


async def _get_contrat(db: AsyncSession, cid: str) -> Contrat:
    try:
        c = await db.get(Contrat, uuid.UUID(cid))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if c is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    return c


async def _get_intervenant(db: AsyncSession, iid: str) -> Intervenant:
    try:
        i = await db.get(Intervenant, uuid.UUID(iid))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if i is None:
        raise HTTPException(status_code=404, detail="Intervenant introuvable")
    return i


def _calculer(champs: dict, bareme: dict) -> tuple:
    """
    Mensualisation, frais et alertes à partir des champs saisis.

    Un champ manquant ne fait pas échouer l'écran : on rend `None` pour le calcul concerné
    et une alerte qui dit **ce qui manque**. Un formulaire qui refuse de s'afficher tant
    qu'il n'est pas complet ne se remplit jamais.
    """
    taux = _dec(champs.get("taux_horaire"))
    heures = _dec(champs.get("heures_semaine"))
    annee_complete = bool(champs.get("annee_complete", True))
    semaines = _entier(champs.get("semaines"), 0)
    majoration = _dec(champs.get("majoration_pct"))
    alertes: list[calcul.Alerte] = []

    mensualisation = None
    if taux and heures:
        try:
            mensualisation = calcul.mensualiser(
                taux_horaire=taux, heures_semaine=heures, annee_complete=annee_complete,
                semaines=semaines or None,
                majoration=(majoration / 100) if majoration is not None else None,
            )
        except ValueError as e:
            alertes.append(calcul.Alerte(cle="calcul", message=str(e), bloquant=True))
    else:
        alertes.append(calcul.Alerte(
            cle="incomplet",
            message="Renseignez le taux horaire et la durée hebdomadaire pour obtenir le "
                    "salaire mensualisé.",
        ))

    frais = None
    if mensualisation is not None:
        frais = calcul.estimer_frais(
            jours_semaine=_entier(champs.get("jours_semaine"), 0),
            semaines=mensualisation.semaines,
            entretien_jour=_dec(champs.get("entretien_jour")),
            repas_jour=_dec(champs.get("repas_jour")),
            km_semaine=_dec(champs.get("km_semaine")),
            tarif_km=_dec(champs.get("tarif_km")),
        )

    if taux:
        alertes += calcul.controler(
            taux_horaire=taux,
            heures_jour=_dec(champs.get("heures_jour")),
            entretien_jour=_dec(champs.get("entretien_jour")),
            smic_horaire=bareme["smic_horaire"],
            minimum_garanti=bareme["minimum_garanti"],
        )

    return mensualisation, frais, alertes


def _serialiser(c: Contrat, mensualisation=None, frais=None,
                alertes: list | None = None) -> dict:
    return {
        "id": str(c.id), "intervenant_id": str(c.intervenant_id), "profil": c.profil,
        "titre": c.titre, "statut": c.statut, "champs": c.champs or {},
        "texte": c.texte,
        "genere_le": c.genere_le.isoformat() if c.genere_le else None,
        "bareme_verifie_le": c.bareme_verifie_le.isoformat() if c.bareme_verifie_le else None,
        "document_id": str(c.document_id) if c.document_id else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "calcul": None if mensualisation is None else {
            "regime": mensualisation.regime,
            "semaines": mensualisation.semaines,
            "heures_mensualisees": str(mensualisation.heures_mensualisees),
            "salaire_mensuel": str(mensualisation.salaire_mensuel),
            "heures_majorees_semaine": str(mensualisation.heures_majorees_semaine),
            "formule": mensualisation.formule,
            "detail": mensualisation.detail,
        },
        "frais": None if frais is None else {
            "entretien_mensuel": str(frais.entretien_mensuel),
            "repas_mensuel": str(frais.repas_mensuel),
            "km_mensuel": str(frais.km_mensuel),
            "total_mensuel": str(frais.total_mensuel),
            "detail": frais.detail,
        },
        "alertes": [
            {"cle": a.cle, "message": a.message, "bloquant": a.bloquant}
            for a in (alertes or [])
        ],
    }


@router.get("/emploi-domicile/intervenants/{iid}/contrats", tags=["Emploi à domicile"])
async def lister(iid: str, db: AsyncSession = Depends(get_db)) -> dict:
    i = await _get_intervenant(db, iid)
    contrats = (await db.execute(
        select(Contrat).where(Contrat.intervenant_id == i.id).order_by(Contrat.created_at)
    )).scalars().all()
    bareme = await _bareme(db)
    return {
        "intervenant": {"id": str(i.id), "nom": i.nom, "prenom": i.prenom, "profil": i.profil},
        "bareme": {"renseigne": bareme["smic_horaire"] is not None,
                   "verifie_le": bareme["verifie_le"]},
        "contrats": [_serialiser(c) for c in contrats],
        # Les sources qui font foi, servies avec la liste : l'écran ne code aucun lien en
        # dur, et la trame générée n'est PAS un modèle officiel — il faut pouvoir comparer.
        "sources": gabarit.SOURCES_OFFICIELLES,
        "avertissement": gabarit.AVERTISSEMENT_PIED,
    }


@router.post("/emploi-domicile/intervenants/{iid}/contrats", status_code=201,
             tags=["Emploi à domicile"])
async def creer(iid: str, body: ContratIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Crée un contrat, **pré-rempli depuis la fiche** de la personne : agrément, tarif annoncé,
    adresse. Retaper ce que l'application connaît déjà est le meilleur moyen d'introduire une
    coquille dans un document qui engage.
    """
    i = await _get_intervenant(db, iid)
    champs = {
        "agrement_numero": i.agrement_numero,
        "agrement_echeance": i.agrement_echeance.isoformat() if i.agrement_echeance else None,
        "places": i.places,
        "lieu_accueil": i.adresse,
        "annee_complete": True,
        **body.champs,   # ce qui vient de l'écran prime sur le pré-remplissage
    }
    c = Contrat(intervenant_id=i.id, profil=i.profil, champs=champs,
                titre=body.titre or f"Contrat de travail — {i.prenom or ''} {i.nom}".strip())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    log.info("Contrat créé", intervenant=i.nom, profil=c.profil)
    bareme = await _bareme(db)
    return _serialiser(c, *_calculer(c.champs, bareme))


@router.get("/emploi-domicile/contrats/{cid}", tags=["Emploi à domicile"])
async def detail(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Le contrat, ses calculs et ses alertes — recalculés à chaque lecture, jamais figés."""
    c = await _get_contrat(db, cid)
    bareme = await _bareme(db)
    return _serialiser(c, *_calculer(c.champs or {}, bareme))


@router.patch("/emploi-domicile/contrats/{cid}", tags=["Emploi à domicile"])
async def modifier(cid: str, body: ContratPatch, db: AsyncSession = Depends(get_db)) -> dict:
    c = await _get_contrat(db, cid)
    if body.statut is not None and body.statut not in STATUTS:
        raise HTTPException(status_code=400,
                            detail=f"statut invalide : {body.statut!r} (attendu : {', '.join(STATUTS)})")

    if body.titre is not None:
        c.titre = body.titre
    if body.statut is not None:
        c.statut = body.statut
    if body.champs is not None:
        # Fusion et non remplacement : l'écran envoie le champ modifié, pas le formulaire
        # entier — un remplacement effacerait tout ce qui n'a pas été retouché.
        c.champs = {**(c.champs or {}), **body.champs}
    if body.texte is not None:
        c.texte = body.texte

    await db.commit()
    await db.refresh(c)
    bareme = await _bareme(db)
    return _serialiser(c, *_calculer(c.champs or {}, bareme))


@router.post("/emploi-domicile/contrats/{cid}/generer", tags=["Emploi à domicile"])
async def generer(cid: str, body: GenererIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    (Re)génère le texte du contrat depuis les champs et les calculs.

    **Refuse d'écraser un texte déjà corrigé** sans `ecraser: true`. Une régénération
    silencieuse ferait perdre les amendements relus — et c'est exactement le moment où l'on
    régénère sans y penser, juste après avoir ajusté un chiffre.
    """
    c = await _get_contrat(db, cid)
    if c.texte and not body.ecraser:
        raise HTTPException(
            status_code=409,
            detail="Ce contrat a déjà un texte, possiblement corrigé à la main. Relancez avec "
                   "« écraser » pour le régénérer depuis les champs.",
        )
    if c.statut in ("signe", "termine") and not body.ecraser:
        raise HTTPException(status_code=409,
                            detail="Ce contrat est signé : le régénérer effacerait le document "
                                   "qui fait foi.")

    i = await _get_intervenant(db, str(c.intervenant_id))
    bareme = await _bareme(db)
    champs = dict(c.champs or {})
    champs["bareme_verifie_le"] = bareme["verifie_le"]
    mensualisation, frais, _ = _calculer(champs, bareme)

    texte = gabarit.generer(
        profil=get_profil(c.profil),
        employeur=await _profil_employeur(db),
        salariee=gabarit.Partie(
            nom=" ".join(x for x in (i.prenom, i.nom) if x),
            adresse=i.adresse, telephone=i.telephone, email=i.email,
        ),
        champs=champs, mensualisation=mensualisation, frais=frais,
    )

    c.texte = texte
    c.genere_le = datetime.now(tz=timezone.utc)
    if bareme["verifie_le"]:
        try:
            c.bareme_verifie_le = date.fromisoformat(bareme["verifie_le"])
        except ValueError:
            c.bareme_verifie_le = None
    await db.commit()
    await db.refresh(c)
    log.info("Contrat généré", contrat=str(c.id), nb_chars=len(texte))
    return _serialiser(c, *_calculer(c.champs or {}, bareme))


@router.delete("/emploi-domicile/contrats/{cid}", tags=["Emploi à domicile"])
async def supprimer(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await _get_contrat(db, cid)
    await db.delete(c)
    await db.commit()
    return {"supprime": True}


@router.post("/emploi-domicile/contrats/{cid}/exemple", tags=["Emploi à domicile"])
async def remplir_exemple(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Remplit les champs **encore vides** avec un jeu de valeurs plausibles, pour voir le
    contrat rendu d'un coup sans avoir à tout saisir.

    **Ne remplace jamais ce qui est déjà renseigné** : un bouton d'exemple qui écraserait une
    saisie serait un piège, et c'est justement quand le formulaire est à moitié rempli qu'on
    a envie de voir à quoi ça ressemble.

    Les valeurs sont là pour être remplacées : les champs qui engagent (assurances, contacts
    d'urgence, lieu de signature) portent explicitement « à compléter », pour qu'un exemple
    oublié produise un contrat visiblement inachevé plutôt qu'un contrat faux.
    """
    c = await _get_contrat(db, cid)
    if c.statut in ("signe", "termine"):
        raise HTTPException(status_code=409,
                            detail="Ce contrat est signé : ses champs ne se remplissent plus.")

    champs = dict(c.champs or {})
    ajoutes = 0
    for cle, valeur in gabarit.EXEMPLE.items():
        actuel = champs.get(cle)
        if actuel is None or str(actuel).strip() == "":
            champs[cle] = valeur
            ajoutes += 1
    c.champs = champs
    await db.commit()
    await db.refresh(c)
    log.info("Exemple appliqué au contrat", contrat=cid, champs_remplis=ajoutes)

    bareme = await _bareme(db)
    return {**_serialiser(c, *_calculer(c.champs, bareme)), "champs_remplis": ajoutes}


# ─── Annexes ──────────────────────────────────────────────────────────────────────────
# Ce que le contrat ne règle pas, et qui décide pourtant d'un mardi à 16 h : autorisations,
# personnes autorisées à venir chercher l'enfant, fiche de renseignements. Elles sont des
# DOCUMENTS SÉPARÉS et non des articles : une autorisation se retire du jour au lendemain,
# une clause se renégocie. Les mêler rendrait chaque changement d'habitude solennel — donc
# jamais fait.

@router.get("/emploi-domicile/contrats/{cid}/annexes", tags=["Emploi à domicile"])
async def lister_annexes(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Les annexes proposées pour ce contrat, avec ce à quoi chacune sert."""
    c = await _get_contrat(db, cid)
    return {"contrat_id": str(c.id),
            "annexes": annexes.disponibles(get_profil(c.profil))}


@router.get("/emploi-domicile/contrats/{cid}/annexes/{cle}", tags=["Emploi à domicile"])
async def generer_annexe(cid: str, cle: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Le texte d'une annexe, en Markdown — même chaîne d'export que le contrat.

    Elle est **rendue à la volée** et non stockée : contrairement au contrat, qui se relit et
    se corrige, une annexe n'a pas de version amendée à préserver. La figer en base
    obligerait à la régénérer quand le prénom de l'enfant change dans le contrat, et c'est
    exactement la divergence qu'on remarque le jour du désaccord.
    """
    c = await _get_contrat(db, cid)
    i = await db.get(Intervenant, c.intervenant_id)
    qui = " ".join(x for x in ((i.prenom if i else None), (i.nom if i else None)) if x)
    try:
        a = annexes.generer(cle, profil=get_profil(c.profil), champs=c.champs or {},
                            salariee_nom=qui)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"cle": a.cle, "titre": a.titre, "resume": a.resume, "texte": a.texte,
            "nom_fichier": f"{a.titre} - {qui or 'annexe'}".strip()}


# ─── Dépôt en GED ─────────────────────────────────────────────────────────────────────

@router.post("/emploi-domicile/contrats/{cid}/deposer", tags=["Emploi à domicile"])
async def deposer_en_ged(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Dépose le contrat dans la GED pour qu'il soit **retrouvable comme le reste**.

    Un contrat qui ne vit que dans son écran est introuvable le jour où on le cherche par
    « contrat 2026 » dans la recherche globale — c'est-à-dire précisément le jour où on en a
    besoin, des mois après l'avoir écrit.

    Le texte déposé est **celui qui a été relu et corrigé** (`contrat.texte`), pas une
    régénération : déposer autre chose que ce qui a été signé serait pire que ne rien
    déposer.

    **Idempotent** : `contrat.document_id` garde le lien. Redéposer met à jour le document
    existant au lieu d'en créer un second — deux versions d'un contrat dans une GED, on ne
    sait plus laquelle fait foi.
    """
    import hashlib

    from models.document import Document

    c = await _get_contrat(db, cid)
    if not c.texte:
        raise HTTPException(
            status_code=400,
            detail="Ce contrat n'a pas encore de texte : générez-le avant de le déposer.",
        )

    i = await db.get(Intervenant, c.intervenant_id)
    qui = " ".join(x for x in ((i.prenom if i else None), (i.nom if i else None)) if x)
    nom = f"{c.titre}.md" if not qui else f"{c.titre} — {qui}.md"
    chemin = f"matotheque://contrats/{c.id}.md"
    contenu = c.texte

    doc = await db.get(Document, c.document_id) if c.document_id else None
    if doc is None:
        # Le chemin sert aussi de clé de dédoublonnage : un contrat redéposé après que son
        # `document_id` a été perdu (document supprimé de la GED puis recréé) ne doit pas
        # semer un second exemplaire.
        doc = (await db.execute(
            select(Document).where(Document.chemin == chemin))).scalar_one_or_none()
        if doc is None:
            doc = Document(chemin=chemin, nom=nom, extension="md")
            db.add(doc)

    doc.nom = nom
    doc.type_mime = "text/markdown"
    doc.taille_octets = len(contenu.encode("utf-8"))
    doc.hash_sha256 = hashlib.sha256(contenu.encode("utf-8")).hexdigest()
    # Le texte est posé directement : il est DÉJÀ du texte, donc le faire passer par Tika
    # n'apporterait rien qu'un aller-retour et une dépendance à un service qui peut être
    # arrêté. Statut « extracted » et non « enriched » : l'enrichissement IA (catégorie,
    # tags, résumé) reste à faire, et prétendre le contraire priverait le document du
    # passage qui le rend trouvable par la recherche sémantique.
    doc.texte_extrait = contenu
    doc.statut = "extracted"
    doc.source = "interne"
    doc.date_modification_fichier = c.genere_le or datetime.now(tz=timezone.utc)

    await db.flush()
    c.document_id = doc.id
    await db.commit()
    log.info("Contrat déposé en GED", contrat=cid, document=str(doc.id), octets=doc.taille_octets)
    return {"document_id": str(doc.id), "nom": doc.nom, "chemin": doc.chemin,
            "octets": doc.taille_octets}


@router.delete("/emploi-domicile/contrats/{cid}/deposer", tags=["Emploi à domicile"])
async def retirer_de_ged(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Retire le document de la GED et coupe le lien.

    Laisser `document_id` pointer vers un document supprimé ferait afficher « déposé » à
    l'écran pour un document que la recherche ne trouve plus.
    """
    from models.document import Document

    c = await _get_contrat(db, cid)
    if c.document_id:
        doc = await db.get(Document, c.document_id)
        if doc is not None:
            await db.delete(doc)
        c.document_id = None
        await db.commit()
    return {"retire": True}


# ─── Reste à charge ───────────────────────────────────────────────────────────────────
# « Combien ça me coûte à la fin du mois ? » — la question qu'on pose en premier, et à
# laquelle rien ne répondait. Le contrat donne un salaire ; il ne dit ni ce que la CAF verse,
# ni ce que le crédit d'impôt rend.

@router.get("/emploi-domicile/contrats/{cid}/cout", tags=["Emploi à domicile"])
async def reste_a_charge(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Ce qui sort réellement du compte chaque mois.

    Le salaire et les indemnités sont **recalculés depuis le contrat** ; le CMG, l'avance
    immédiate et les cotisations sont **saisis** dans les champs du contrat, parce qu'ils
    viennent de documents que Matothèque n'a pas — une notification CAF et un bulletin.

    Aucun taux n'est inventé : cf. `services/emploi_domicile/cout`.
    """
    c = await _get_contrat(db, cid)
    champs = c.champs or {}
    mensualisation, frais, _ = _calculer(champs, await _bareme(db))

    resultat = cout.calculer(
        salaire_mensuel=mensualisation.salaire_mensuel if mensualisation else None,
        frais_mensuels=frais.total_mensuel if frais else None,
        cmg=_dec(champs.get("cmg_mensuel")),
        avance_immediate=_dec(champs.get("avance_immediate")),
        cotisations=_dec(champs.get("cotisations_mensuelles")),
    )
    return {
        "contrat_id": str(c.id),
        "postes": [
            {"cle": p.cle, "libelle": p.libelle, "sens": p.sens, "origine": p.origine,
             "saisi": p.saisi,
             "montant": str(p.montant) if p.montant is not None else None}
            for p in resultat.postes
        ],
        "sorties": str(resultat.sorties),
        "entrees": str(resultat.entrees),
        "total": str(resultat.total),
        "complet": resultat.complet,
        "remarques": resultat.remarques,
    }


# ─── Jalons de suivi ──────────────────────────────────────────────────────────────────

@router.post("/emploi-domicile/contrats/{cid}/rappels", tags=["Emploi à domicile"])
async def poser_les_rappels(cid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Pose au planning les échéances qui reviennent : déclaration mensuelle, régularisation
    annuelle, échéance d'agrément.

    **Pas d'abonnement, pas de récurrence automatique.** Un jalon posé pour les cinq
    prochaines années encombrerait le planning de rendez-vous qu'on cesse de lire — et
    l'employeur change, le contrat s'arrête. On pose **les trois prochaines échéances**, et
    on repose quand on revient.

    Idempotent par titre : reposer ne duplique pas.
    """
    from datetime import timedelta

    from models.jalon import Jalon
    from routers.dossiers import _ancre_courante, _mois_depuis_date

    c = await _get_contrat(db, cid)
    i = await db.get(Intervenant, c.intervenant_id)
    if i is None:
        raise HTTPException(status_code=404, detail="Fiche introuvable")
    profil = get_profil(c.profil)
    qui = " ".join(x for x in (i.prenom, i.nom) if x) or "votre salarié(e)"

    aujourdhui = date.today()
    echeances: list[tuple[date, str, str]] = []

    # Déclaration mensuelle : le geste qui revient, et le seul dont l'oubli coûte de l'argent
    # (pas de CMG sans déclaration). On pose les trois prochains mois.
    for n in range(3):
        mois = aujourdhui.replace(day=1) + timedelta(days=32 * n)
        jour = mois.replace(day=1)
        echeances.append((
            jour,
            f"Déclarer {qui} à {profil.guichet}",
            f"Heures, jours d'accueil, repas et kilomètres du mois précédent. "
            f"Le journal du contrat les tient à jour. Sans déclaration, pas de "
            f"{profil.aide.split('(')[0].strip()}.",
        ))

    # Régularisation annuelle : le rendez-vous qu'on découvre en décembre, trop tard pour
    # étaler l'écart sur plusieurs mois.
    fin = date(aujourdhui.year, 12, 1)
    if fin < aujourdhui:
        fin = date(aujourdhui.year + 1, 12, 1)
    echeances.append((
        fin,
        f"Régularisation annuelle — {qui}",
        "Comparer les heures payées (mensualisées × 12) aux heures réellement faites, et "
        "solder l'écart. Le journal du contrat donne les deux.",
    ))

    # Échéance d'agrément : sans agrément valide, il n'y a ni aide ni accueil légal. On
    # prévient deux mois avant — un renouvellement ne se fait pas la veille.
    if i.agrement_echeance:
        alerte = i.agrement_echeance - timedelta(days=60)
        if alerte > aujourdhui:
            echeances.append((
                alerte,
                f"Renouvellement d'agrément à vérifier — {qui}",
                f"L'agrément expire le {i.agrement_echeance.strftime('%d/%m/%Y')}. "
                "Sans agrément valide, il n'y a ni aide ni accueil légal.",
            ))

    ancre = _ancre_courante()
    poses, existants = [], 0
    for jour, titre, detail in echeances:
        deja = (await db.execute(
            select(Jalon).where(Jalon.dossier_id == i.dossier_id, Jalon.titre == titre,
                                Jalon.date_reelle == jour)
        )).scalar_one_or_none()
        if deja is not None:
            existants += 1
            continue
        mois = _mois_depuis_date(jour, ancre) if ancre else 0
        position = ((await db.execute(
            select(func.max(Jalon.position)).where(Jalon.dossier_id == i.dossier_id,
                                                   Jalon.mois == mois)
        )).scalar() or 0) + 1
        db.add(Jalon(dossier_id=i.dossier_id, mois=mois, position=position,
                     categorie="garde", titre=titre, detail=detail, date_reelle=jour))
        poses.append({"titre": titre, "date": jour.isoformat()})

    await db.commit()
    log.info("Rappels posés", contrat=cid, poses=len(poses), deja=existants)
    return {"poses": poses, "deja_presents": existants,
            "note": ("Les rappels couvrent les trois prochains mois : revenez poser les "
                     "suivants. Un planning rempli sur cinq ans cesse d'être lu.")}
