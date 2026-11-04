"""
Handler de job — tableau comparatif multi-groupes (`comparatif`).
=================================================================
Avant le 18/09/2026, la comparaison tournait dans une `asyncio.create_task` du process uvicorn qui
avait reçu la demande, avec son état dans un dict en mémoire. Le backend tourne avec `--workers 2` :
le suivi (SSE) ou le téléchargement arrivait une fois sur deux sur l'AUTRE process → « Job
introuvable ». Désormais : tâche durable du worker, progression écrite dans `jobs.resultat["events"]`,
relue par n'importe quel process. Le calcul (critères → groupes → synthèse) reste dans
routers/compare.py ; ce module ne fait que l'orchestrer.

Module séparé (comme regroupement_jobs.py), importé au démarrage par main.py et worker.py.
"""
import uuid

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from models.job import Job
from services.job_worker import JobContext, register

log = get_logger(__name__)


async def _persister(job_id: str, resultat: dict) -> None:
    """Écrit l'état courant (événements compris) dans `jobs.resultat` — lu par le flux SSE."""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is not None:
            job.resultat = dict(resultat)   # nouvel objet : SQLAlchemy détecte le changement JSONB
            await db.commit()


def _cellules_en_texte(valeurs: dict) -> tuple[dict, int]:
    """
    Remet en texte les cellules stockées en repr Python d'un objet ou d'une liste
    (« {'Frais de séjour': '150% BR'} ») : `(valeurs, nombre de cellules corrigées)`.
    `ast.literal_eval` ne fait que LIRE un littéral — aucun code n'est exécuté.
    """
    import ast
    from routers.compare import _en_cellule

    sorties, nb = {}, 0
    for cle, v in valeurs.items():
        brut = v.strip() if isinstance(v, str) else ""
        if brut[:1] in ("{", "[") and brut[-1:] in ("}", "]"):
            try:
                lu = ast.literal_eval(brut)
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                lu = None
            if isinstance(lu, (dict, list)):
                sorties[cle], nb = _en_cellule(lu), nb + 1
                continue
        sorties[cle] = v
    return sorties, nb


async def _recommandation(etat: dict, grille: dict | None, instructions: str | None,
                          model: str, ollama) -> dict | None:
    """Recommandation de l'IA d'après le tableau rempli (services/recommandation_comparatif.py)."""
    from routers.compare import _construire_markdown
    from services.classement import calculer, classement_markdown
    from services.recommandation_comparatif import recommander

    colonnes = list(etat.get("colonnes") or [])
    groupes = list(etat.get("groupes") or [])
    exploitables = [g for g in groupes if not g.get("echec_ia")]
    classement = calculer(groupes, colonnes, grille)
    tableau = _construire_markdown(colonnes, exploitables, synthese=None, titre=None)
    return await recommander(tableau, groupes, classement_markdown(classement) if classement else None,
                             etat.get("synthese"), instructions, model, ollama)


@register("comparatif")
async def handler_comparatif(ctx: JobContext) -> dict:
    """
    Paramètres : `groupes` [{nom, document_ids}], `colonnes` (vides = déduites par l'IA),
    `model`, `instructions`, `synthese` (bool), `template_id` (repris au téléchargement),
    `grille` (services/grille_analyse.py — critères en lignes, évalués un par un).
    """
    from routers.compare import (
        _analyser_groupe, _budget_analyse, _charger_documents, _contexte_documents, _deduire_colonnes,
        _part_lue, _synthetiser_ecarts,
    )
    from services.fiches_candidats import rediger_fiche
    from services.grille_analyse import (
        AVIS_ECHEC_IA, BUDGET_CRITERE, BUDGET_EXIGENCES, Grille, evaluer_critere, exigences_marche,
        echelle_critere, passages_pertinents, valeur_lisible,
    )
    from services import cause_echec_ia
    from services.ollama_service import OllamaService

    p = ctx.parametres
    groupes = p.get("groupes") or []
    if len(groupes) < 2:
        raise ValueError("Au moins 2 groupes sont nécessaires")
    model = p.get("model")
    instructions = p.get("instructions")
    colonnes: list[str] = list(p.get("colonnes") or [])
    ollama = OllamaService()
    total = len(groupes)
    grille = Grille.from_dict(p["grille"]) if p.get("grille") else None

    etat: dict = {"events": [], "colonnes": colonnes, "groupes": [], "synthese": None,
                  "criteres_par_defaut": False, "groupes_en_echec": []}

    async def emettre(evt: dict) -> None:
        etat["events"].append(evt)
        await _persister(ctx.job_id, etat)

    if p.get("criteres_ignores"):
        await emettre({"statut": "criteres",
                       "message": f"Grille : {p['criteres_ignores']} critère(s) au-delà de {len(colonnes)} "
                                  "non évalué(s) — scindez la grille ou saisissez les critères."})

    # Étape 0 — critères déduits par l'IA (ni template, ni saisie manuelle)
    if not colonnes:
        await emettre({"statut": "criteres", "message": "Détermination des critères de comparaison…"})
        echantillon: list[Document] = []
        for g in groupes:
            echantillon += await _charger_documents(list(g.get("document_ids") or [])[:2])
        colonnes, par_defaut = await _deduire_colonnes(echantillon, instructions, model, ollama)
        etat["colonnes"], etat["criteres_par_defaut"] = colonnes, par_defaut
        await emettre({"statut": "criteres", "colonnes": colonnes})
        if par_defaut:
            await emettre({"statut": "criteres",
                           "message": "L'IA n'a proposé aucun critère exploitable : critères génériques utilisés."})

    # Documents du marché (CCTP, règlement) : chargés une fois ; leurs passages par critère sont
    # gardés en cache — les mêmes exigences valent pour tous les candidats.
    docs_marche = await _charger_documents(list(p.get("documents_marche") or []))
    exigences_cache: dict[int, str | None] = {}

    async def exigences_pour(critere) -> str | None:
        if critere.ligne not in exigences_cache:
            exigences_cache[critere.ligne] = await exigences_marche(critere, docs_marche)
        return exigences_cache[critere.ligne]

    budget_candidat = BUDGET_CRITERE - (BUDGET_EXIGENCES if docs_marche else 0)
    exigences_texte = _contexte_documents(docs_marche, BUDGET_EXIGENCES) if docs_marche and not grille else None
    if docs_marche:
        await emettre({"statut": "criteres",
                       "message": f"Documents du marché : {len(docs_marche)} pièce(s) confrontée(s) aux offres."})

    for idx, g in enumerate(groupes, start=1):
        if ctx.cancelled:
            log.info("Comparatif annulé", job_id=ctx.job_id, groupes_faits=idx - 1)
            return etat
        nom = g.get("nom") or f"Groupe {idx}"
        await ctx.report(int(100 * (idx - 1) / (total + 1)), f"Analyse de « {nom} » ({idx}/{total})…")
        await emettre({"groupe": nom, "statut": "running", "index": idx, "total": total})

        docs = await _charger_documents(list(g.get("document_ids") or []))
        causes: list[str] = []   # raisons LISIBLES des essais ratés (cause_echec_ia, 04/11/2026)
        if grille:
            # Grille d'analyse : UN appel par critère (avis + note), les pièces citées par le
            # critère passant en tête du contexte. Plus long, mais chaque note est motivée.
            valeurs, evaluations, nb_ok = {}, {}, 0
            for critere in grille.criteres:
                if ctx.cancelled:
                    break
                await emettre({"groupe": nom, "statut": "running", "index": idx, "total": total,
                               "message": f"{nom} — {critere.titre}"})
                contexte = await passages_pertinents(critere, docs, budget=budget_candidat)
                avis, note, ok_c = await evaluer_critere(nom, critere, docs, instructions, model, ollama,
                                                         contexte=contexte, note_max=echelle_critere(critere, grille), bareme=grille.bareme,
                                                         exigences=await exigences_pour(critere), causes=causes)
                nb_ok += ok_c
                evaluations[str(critere.ligne)] = {"avis": avis, "note": note}
                valeurs[critere.titre] = valeur_lisible(avis, note, echelle_critere(critere, grille))
            # Seconde chance pour les critères en échec : le GPU est partagé, un pic de charge
            # (504 de la passerelle après 300 s, le 01/10/2026) ne doit pas laisser une case vide.
            for critere in grille.criteres:
                ev = evaluations.get(str(critere.ligne)) or {}
                if ctx.cancelled or ev.get("avis") != AVIS_ECHEC_IA:
                    continue
                await emettre({"groupe": nom, "statut": "running", "index": idx, "total": total,
                               "message": f"{nom} — {critere.titre} (nouvel essai)"})
                contexte = await passages_pertinents(critere, docs, budget=budget_candidat)
                avis, note, ok_c = await evaluer_critere(nom, critere, docs, instructions, model, ollama,
                                                         contexte=contexte, note_max=echelle_critere(critere, grille), bareme=grille.bareme,
                                                         exigences=await exigences_pour(critere), causes=causes)
                if ok_c:
                    nb_ok += 1
                    evaluations[str(critere.ligne)] = {"avis": avis, "note": note}
                    valeurs[critere.titre] = valeur_lisible(avis, note, echelle_critere(critere, grille))
            ok = nb_ok > 0
            ligne = {"nom": nom, "valeurs": valeurs, "evaluations": evaluations}
        else:
            valeurs, ok = await _analyser_groupe(
                nom_groupe=nom, docs=docs, colonnes=colonnes,
                instructions=instructions, model=model, ollama=ollama, exigences=exigences_texte,
                causes=causes,
            )
            ligne = {"nom": nom, "valeurs": valeurs,
                     "lu_pct": _part_lue(docs, _budget_analyse(instructions, colonnes, exigences_texte))}
        if not ok:
            ligne["echec_ia"] = True
            ligne["cause_echec"] = cause_echec_ia.cause_dominante(causes) or "cause inconnue"
            etat["groupes_en_echec"].append(nom)
            etat.setdefault("causes_echec", []).extend(causes)
        # Fiche points forts / faibles, rédigée d'après l'évaluation qu'on vient d'obtenir.
        if p.get("fiches", True) and not ctx.cancelled:
            ligne["fiche"] = None
            if ok:
                await emettre({"groupe": nom, "statut": "running", "index": idx, "total": total,
                               "message": f"{nom} — fiche points forts / faibles"})
                ligne["fiche"] = await rediger_fiche(nom, ligne["valeurs"], instructions, model, ollama)
        etat["groupes"].append(ligne)
        await emettre({"groupe": nom, "statut": "done", "index": idx, "total": total, "echec_ia": not ok,
                       **({"cause": ligne["cause_echec"]} if not ok else {})})

    # Tous les groupes en échec : ce n'est pas un tableau, c'est un échec — on le dit.
    # La cause, pas une supposition : le 04/11/2026, une IA INJOIGNABLE (ConnectTimeout) s'affichait
    # « réponses sans JSON exploitable — vérifier le modèle », ce qui envoyait chercher au mauvais endroit.
    if etat["groupes_en_echec"] and len(etat["groupes_en_echec"]) == total:
        if not await ollama.check_health():
            raise RuntimeError("L'IA locale est injoignable (Ollama / AIGUILLEUR) : aucun groupe n'a pu "
                               "être analysé. Vérifier que le PC de l'IA est allumé et joignable, puis relancer.")
        cause = cause_echec_ia.cause_dominante(etat.get("causes_echec") or [])
        if cause:
            raise RuntimeError(f"Aucun groupe n'a pu être analysé — cause : {cause}. "
                               f"(Modèle : {model or 'modèle par défaut'} ; {len(colonnes)} critère(s).)")
        raise RuntimeError(f"L'IA ({model or 'modèle par défaut'}) a répondu mais n'a rien pu extraire pour "
                           "aucun groupe (réponses sans JSON exploitable, ou délai dépassé quand le GPU est "
                           "très chargé) — relancer, ou changer le modèle « rapport » dans les Paramètres")

    # Synthèse des écarts (facultative — le tableau reste exploitable si elle échoue)
    if p.get("synthese", True):
        await emettre({"statut": "synthese", "message": "Rédaction de la synthèse des écarts…"})
        etat["synthese"] = await _synthetiser_ecarts(colonnes, etat["groupes"], instructions, model, ollama)

    # Candidat recommandé : page 1 des exports (02/11/2026). Un plus — son échec ne casse rien.
    if p.get("recommandation", True) and not ctx.cancelled:
        await emettre({"statut": "synthese", "message": "Recommandation de l'IA…"})
        etat["recommandation"] = await _recommandation(etat, p.get("grille"), instructions, model, ollama)

    log.info("Tableau comparatif généré", job_id=ctx.job_id, nb_groupes=total, nb_criteres=len(colonnes),
             nb_groupes_en_echec=len(etat["groupes_en_echec"]),   # jamais les noms (offres confidentielles)
             criteres_par_defaut=etat["criteres_par_defaut"])
    return etat   # écrit dans jobs.resultat par le worker, avec le statut « completed »


@register("comparatif_reparer")
async def handler_comparatif_reparer(ctx: JobContext) -> dict:
    """
    Répare une comparaison TERMINÉE sans tout relancer (11/10/2026) :
      - notes perdues mais écrites en tête d'avis (« 15/20 — … ») → récupérées ;
      - critères « ⚠ Échec de l'IA » d'une grille → réévalués (documents du candidat relus) ;
      - fiches manquantes (et candidats non en échec) → rédigées d'après l'évaluation.
    Le résultat de la comparaison est réécrit EN PLACE, avec `rev` + 1 : les exports (cache par
    `rev`) sont reconstruits au prochain téléchargement.
    """
    from routers.compare import (
        _analyser_groupe, _budget_analyse, _charger_documents, _contexte_documents, _part_lue,
        _synthetiser_ecarts,
    )
    from services.fiches_candidats import rediger_fiche
    from services.grille_analyse import (
        AVIS_ECHEC_IA, Grille, _note_depuis_avis, evaluer_critere, exigences_marche, passages_pertinents,
        valeur_lisible, BUDGET_CRITERE, BUDGET_EXIGENCES, echelle_critere,
    )
    from services.ollama_service import OllamaService

    cible = (ctx.parametres or {}).get("job_id")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(cible)) if cible else None
        if job is None or job.type != "comparatif" or job.statut != "completed" or not job.resultat:
            raise ValueError("Comparaison introuvable ou pas encore terminée")
        etat, p = dict(job.resultat), dict(job.parametres or {})

    grille = Grille.from_dict(p["grille"]) if p.get("grille") else None
    model, instructions, ollama = p.get("model"), p.get("instructions"), OllamaService()
    docs_marche = await _charger_documents(list(p.get("documents_marche") or []))
    budget = BUDGET_CRITERE - (BUDGET_EXIGENCES if docs_marche else 0)
    bilan = {"notes_recuperees": 0, "criteres_reevalues": 0, "fiches_redigees": 0,
             "candidats_reanalyses": 0, "cellules_remises_en_texte": 0, "recommandation_redigee": 0}
    groupes = [dict(g) for g in etat.get("groupes") or []]

    for i, g in enumerate(groupes):
        if ctx.cancelled:
            break
        await ctx.report(int(100 * i / max(len(groupes), 1)), f"Réparation du candidat {i + 1}/{len(groupes)}…")
        if grille:
            evaluations = {k: dict(v) for k, v in (g.get("evaluations") or {}).items()}
            valeurs = dict(g.get("valeurs") or {})
            docs = None
            for critere in grille.criteres:
                ev = evaluations.get(str(critere.ligne)) or {"avis": AVIS_ECHEC_IA, "note": None}
                if ev.get("avis") == AVIS_ECHEC_IA:
                    if docs is None:
                        ids = (p.get("groupes") or [{}] * len(groupes))[i].get("document_ids") or []
                        docs = await _charger_documents(list(ids))
                    contexte = await passages_pertinents(critere, docs, budget=budget)
                    exigences = await exigences_marche(critere, docs_marche)
                    avis, note, ok = await evaluer_critere(g.get("nom") or f"Candidat {i + 1}", critere, docs,
                                                           instructions, model, ollama, contexte=contexte,
                                                           note_max=echelle_critere(critere, grille), exigences=exigences,
                                                           bareme=grille.bareme)
                    if ok:
                        ev = {"avis": avis, "note": note}
                        bilan["criteres_reevalues"] += 1
                elif ev.get("note") is None:
                    note = _note_depuis_avis(ev.get("avis") or "", echelle_critere(critere, grille))
                    if note is not None:
                        ev["note"] = note
                        bilan["notes_recuperees"] += 1
                evaluations[str(critere.ligne)] = ev
                valeurs[critere.titre] = valeur_lisible(ev.get("avis") or "", ev.get("note"), echelle_critere(critere, grille))
            g["evaluations"], g["valeurs"] = evaluations, valeurs
            echec = all((ev.get("avis") == AVIS_ECHEC_IA) for ev in evaluations.values())
            if echec:
                g["echec_ia"] = True
            else:
                g.pop("echec_ia", None)
                g.pop("cause_echec", None)
        else:
            # Sans grille (02/11/2026) : « Réparer » ne faisait RIEN pour un candidat en échec —
            # il est désormais réanalysé ; et les cellules rendues en objet par le modèle (avant
            # 1.149.3, stockées en repr Python « {'clé': 'valeur'} ») sont remises en texte.
            g["valeurs"], nb = _cellules_en_texte(g.get("valeurs") or {})
            bilan["cellules_remises_en_texte"] += nb
            if g.get("echec_ia"):
                ids = (p.get("groupes") or [{}] * len(groupes))[i].get("document_ids") or []
                docs = await _charger_documents(list(ids))
                colonnes = list(etat.get("colonnes") or [])
                exigences_texte = _contexte_documents(docs_marche, BUDGET_EXIGENCES) if docs_marche else None
                valeurs, ok = await _analyser_groupe(
                    nom_groupe=g.get("nom") or f"Candidat {i + 1}", docs=docs, colonnes=colonnes,
                    instructions=instructions, model=model, ollama=ollama, exigences=exigences_texte)
                if ok:
                    g["valeurs"] = valeurs
                    g["lu_pct"] = _part_lue(docs, _budget_analyse(instructions, colonnes, exigences_texte))
                    g.pop("echec_ia", None)
                    g.pop("cause_echec", None)
                    bilan["candidats_reanalyses"] += 1
        if p.get("fiches", True) and not g.get("fiche") and not g.get("echec_ia"):
            fiche = await rediger_fiche(g.get("nom") or f"Candidat {i + 1}", g.get("valeurs") or {},
                                        instructions, model, ollama)
            g["fiche"] = fiche
            bilan["fiches_redigees"] += fiche is not None

    etat["groupes"] = groupes
    etat["groupes_en_echec"] = [g.get("nom") for g in groupes if g.get("echec_ia")]
    # Un candidat réanalysé change les écarts : la synthèse rédigée sans lui est périmée.
    if bilan["candidats_reanalyses"] and p.get("synthese", True) and not ctx.cancelled:
        await ctx.report(95, "Synthèse des écarts…")
        etat["synthese"] = await _synthetiser_ecarts(list(etat.get("colonnes") or []), groupes,
                                                     instructions, model, ollama)
    # Recommandation (page 1 des exports, 02/11/2026) : rédigée si absente — comparaisons antérieures —
    # ou refaite si un candidat a changé.
    change = bilan["candidats_reanalyses"] or bilan["criteres_reevalues"]
    if (change or not etat.get("recommandation")) and p.get("recommandation", True) and not ctx.cancelled:
        await ctx.report(97, "Recommandation de l'IA…")
        reco = await _recommandation(etat, p.get("grille"), instructions, model, ollama)
        if reco is not None:
            etat["recommandation"] = reco
            bilan["recommandation_redigee"] = 1
    etat["rev"] = int(etat.get("rev") or 0) + 1
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(cible))
        job.resultat = etat
        await db.commit()
    log.info("Comparatif réparé", **bilan, rev=etat["rev"])
    return bilan
