"""
Bilan « idées d'évolution » — la cloche de l'en-tête (11/10/2026)
=================================================================
Demande de l'utilisateur : chaque mois (ou trimestre), un retour d'idées d'évolution de Matothèque
tiré des INSTRUCTIONS COMPLÉMENTAIRES qu'il a données pour analyser ses documents de référence
(CCTP, règlement…). Rien à saisir : ces consignes sont déjà archivées avec chaque rapport
(table `rapports`, colonne `prompt`), derrière le marqueur posé par la page Créer.

  - `extraire_consignes` / `collecter` : retrouver les consignes de la période ;
  - `est_du` : le bilan est-il dû (fonction pure) ;
  - `planifier_si_du` : appelé par le worker, met en file la tâche quand c'est dû ;
  - handler `idees_evolution` : l'IA locale rédige le bilan → une notification.

100 % local : Ollama du LAN, la notification reste en base.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from logger import get_logger
from services.job_worker import JobContext, register

log = get_logger(__name__)

TYPE = "idees_evolution"
# Posé par la page Créer (ReportsPage.analyserReference) devant les consignes de l'acheteur.
MARQUEUR = "Instructions complémentaires de l'acheteur"
FREQUENCES_MOIS = {"mensuel": 1, "trimestriel": 3}
JOURS_PAR_MOIS = 30
MAX_CHARS_CONSIGNES = 12_000
TOKENS_BILAN_MAX = 1_800


def extraire_consignes(prompt: str | None) -> str | None:
    """Les consignes de l'acheteur dans un prompt archivé (ce qui suit la ligne du marqueur), ou None."""
    if not prompt or MARQUEUR not in prompt:
        return None
    apres = prompt.split(MARQUEUR, 1)[1]
    apres = apres.split("\n", 1)[1] if "\n" in apres else ""
    return apres.strip() or None


def mois_frequence(frequence: str | None) -> int | None:
    """« mensuel » → 1, « trimestriel » → 3, « desactive » ou inconnu → None."""
    return FREQUENCES_MOIS.get((frequence or "").strip().lower())


def est_du(derniere: datetime | None, mois: int, maintenant: datetime) -> bool:
    """Dû si aucun bilan encore, ou si le dernier date d'au moins la période. Fonction PURE."""
    return derniere is None or maintenant - derniere >= timedelta(days=JOURS_PAR_MOIS * mois)


async def collecter(debut: datetime, fin: datetime) -> list[tuple[datetime, str]]:
    """(date, consignes) des rapports de la période qui portent des instructions complémentaires."""
    from database import AsyncSessionLocal
    from models.rapport import Rapport

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Rapport.created_at, Rapport.prompt)
            .where(Rapport.created_at >= debut, Rapport.created_at < fin,
                   Rapport.prompt.contains(MARQUEUR))
            .order_by(Rapport.created_at)
        )).all()
    resultat = []
    for date, prompt in rows:
        consignes = extraire_consignes(prompt)
        if consignes:
            resultat.append((date, consignes))
    return resultat


def construire_prompt(consignes: list[tuple[datetime, str]], periode: str) -> str:
    lignes, reste = [], MAX_CHARS_CONSIGNES
    for date, texte in consignes:
        ligne = f"- [{date:%d/%m}] {texte}"[:reste]
        lignes.append(ligne)
        reste -= len(ligne) + 1
        if reste <= 200:
            break
    demandes = "\n".join(lignes)
    return f"""Tu es conseiller produit de Matothèque, une GED 100 % locale qui aide un acheteur public à analyser ses documents de référence (CCTP, règlement de consultation) et les offres des candidats.

Voici les instructions complémentaires que l'acheteur a données sur la période « {periode} » ({len(consignes)} demande(s)) :
{demandes}

Rédige un bilan court, clair et visuel, en t'appuyant UNIQUEMENT sur ces demandes (n'invente aucun besoin).
Pas de tableau Markdown : titres, listes et pictogrammes. Respecte EXACTEMENT cette structure :

# 🔔 Idées d'évolution — {periode}

## 🧭 En bref
Deux phrases : ce que l'acheteur cherche le plus à contrôler.

## 🔁 Ce qui revient souvent
3 à 5 puces : le sujet, puis « ×N » (nombre de demandes qui l'abordent).

## 💡 Idées d'évolution pour Matothèque
3 à 5 idées, classées 🔴 forte valeur · 🟠 utile · 🟢 bonus. Chacune : un titre en gras, puis le bénéfice concret pour l'acheteur.

## 📋 Prompts à enregistrer
1 à 3 consignes réutilisables, rédigées et prêtes à copier, chacune dans un bloc de citation (> …)."""


async def generer_bilan(force: bool = False, model: str | None = None, ollama=None) -> dict:
    """
    Rédige le bilan de la période écoulée et l'enregistre. Rend {statut: cree | rien, …}.
    `force` : à la demande (Paramètres) — la période est alors le mois/trimestre glissant.
    """
    from database import AsyncSessionLocal
    from models.notification import Notification
    from services import runtime_config
    from services.ollama_service import OllamaService

    mois = mois_frequence(runtime_config.effective("notif_idees_frequence")) or 1
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=JOURS_PAR_MOIS * mois)
    periode = f"{debut:%d/%m/%Y} → {fin:%d/%m/%Y}"
    consignes = await collecter(debut, fin)
    if not consignes:
        log.info("Bilan idées d'évolution : aucune instruction complémentaire sur la période", force=force)
        return {"statut": "rien", "message": "Aucune instruction complémentaire sur la période : rien à analyser."}

    model = model or runtime_config.model_for("rapport")
    contenu = (await (ollama or OllamaService()).generate(
        construire_prompt(consignes, periode), model=model, num_predict=TOKENS_BILAN_MAX) or "").strip()
    if not contenu:
        raise RuntimeError("L'IA n'a rien rédigé — réessayez plus tard (Ollama ?)")

    async with AsyncSessionLocal() as db:
        n = Notification(type=TYPE, titre=f"💡 Idées d'évolution — {periode}", contenu=contenu,
                         periode_debut=debut, periode_fin=fin)
        db.add(n)
        await db.commit()
        log.info("Bilan idées d'évolution enregistré", demandes=len(consignes), modele=model)
        return {"statut": "cree", "notification_id": str(n.id), "demandes": len(consignes)}


async def planifier_si_du() -> bool:
    """
    Appelé périodiquement par le worker : met en file le bilan quand il est dû ET qu'il y a matière
    (sinon on relirait la base à chaque tick sans rien produire). Rend True si mis en file.
    """
    from database import AsyncSessionLocal
    from models.job import Job
    from models.notification import Notification
    from services import job_worker, runtime_config

    mois = mois_frequence(runtime_config.effective("notif_idees_frequence"))
    if not mois:
        return False
    maintenant = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        derniere = (await db.execute(
            select(func.max(Notification.created_at)).where(Notification.type == TYPE))).scalar()
        if not est_du(derniere, mois, maintenant):
            return False
        en_cours = (await db.execute(select(func.count()).select_from(Job).where(
            Job.type == TYPE, Job.statut.in_(("pending", "running"))))).scalar()
        if en_cours:
            return False
    if not await collecter(maintenant - timedelta(days=JOURS_PAR_MOIS * mois), maintenant):
        return False
    async with AsyncSessionLocal() as db:
        await job_worker.enqueue(db, TYPE, {"force": False})
        await db.commit()
    log.info("Bilan idées d'évolution mis en file", frequence_mois=mois)
    return True


@register(TYPE)
async def handler_idees_evolution(ctx: JobContext) -> dict:
    await ctx.report(10, "Rédaction du bilan d'idées d'évolution…")
    return await generer_bilan(force=bool((ctx.parametres or {}).get("force")))
