"""
Diagnostic IA — l'installation Ollama passée au crible
======================================================
Répond à « mon IA locale est-elle bien réglée pour ma machine ? » sans rien envoyer sur Internet.

Trois temps, volontairement séparés :

1. **Collecte** (`collecter`) — uniquement l'API d'Ollama : `/api/version`, `/api/tags`, `/api/ps`
   et `/api/show` pour chaque modèle. Ollama n'expose ni la VRAM totale ni la RAM : c'est
   l'utilisateur qui les saisit.
2. **Analyse** (`analyser`) — des règles DÉTERMINISTES. Le LLM local n'intervient pas ici : un
   modèle de 8B qui « devine » qu'un modèle déborde de la VRAM se tromperait une fois sur deux,
   alors qu'une comparaison de tailles ne se trompe jamais.
3. **Prompts** — un prompt pour faire rédiger une synthèse par l'IA locale, et un prompt à COPIER
   dans une IA connectée au web, pour ce qu'on ne peut pas savoir hors ligne (modèles plus
   récents, nouvelles versions). L'application n'envoie rien : l'utilisateur copie.

Chaque règle vient d'un cas réel constaté sur PC-GAME le 15/09/2026 : un 35B-A3B en Q8_0 (43 Go,
−58 % de débit par rapport au Q4_K_M), importé sans template de chat ni projecteur vision, et un
usage « vision » pointant vers un modèle supprimé.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime

import httpx

from logger import get_logger

log = get_logger(__name__)

# Ordre d'affichage des constats (le plus grave d'abord).
NIVEAUX = ("critique", "important", "conseil", "info")

# Quantisations « lourdes » : sur un modèle qui déborde, le Q4_K_M divise la taille par ~2 à ~3.
_BITS_PAR_QUANT = {"Q8_0": 8.5, "F16": 16.0, "FP16": 16.0, "BF16": 16.0, "F32": 32.0}
_BITS_Q4_K_M = 4.85

# Au-delà de cette date d'expiration, Ollama a reçu `keep_alive: -1` : le modèle ne part jamais.
_ANNEE_PERMANENT = 2200

_TEMPLATES_BRUTS = {"", "{{ .Prompt }}"}


@dataclass
class Constat:
    """Un point relevé par l'analyse, formulé pour être lu tel quel dans l'interface."""
    niveau: str        # critique | important | conseil | info
    titre: str
    detail: str
    action: str = ""
    modele: str = ""


# ─── Collecte (API Ollama uniquement) ─────────────────────────────────────────

def _normaliser_modele(tag: dict, show: dict | None) -> dict:
    """Fusionne l'entrée `/api/tags` et la réponse `/api/show` d'un modèle en un dict plat."""
    details = tag.get("details") or {}
    show = show or {}
    info = show.get("model_info") or {}
    architecture = info.get("general.architecture") or details.get("family") or ""

    def _champ(suffixe: str):
        return info.get(f"{architecture}.{suffixe}") if architecture else None

    experts = _champ("expert_count") or 0
    capacites = list(show.get("capabilities") or [])
    template = (show.get("template") or "").strip()
    modelfile = show.get("modelfile") or ""
    quantisation = (details.get("quantization_level") or "").upper()
    if quantisation == "UNKNOWN":   # certains GGUF importés de Hugging Face
        quantisation = ""
    return {
        "nom": tag.get("name") or "",
        "taille_go": round((tag.get("size") or 0) / 1e9, 1),
        "parametres": details.get("parameter_size") or "",
        "quantisation": quantisation,
        "architecture": architecture,
        "moe": bool(experts),
        "experts": int(experts),
        "experts_actifs": int(_champ("expert_used_count") or 0),
        "contexte_max": int(_champ("context_length") or 0),
        "capacites": capacites,
        "projecteur": bool(show.get("projector_info")),
        # Ollama récent formate le chat par RENDERER/PARSER ; les plus anciens par un TEMPLATE Go.
        # `TEMPLATE {{ .Prompt }}` SANS renderer = texte brut, sans balises de tour.
        "template_ok": ("RENDERER" in modelfile) or (template not in _TEMPLATES_BRUTS),
        "analyse_complete": bool(show),
    }


def _normaliser_charge(entree: dict) -> dict:
    """Entrée `/api/ps` → modèle chargé, avec sa part en VRAM et son caractère permanent."""
    taille = entree.get("size") or 0
    vram = entree.get("size_vram") or 0
    expire = entree.get("expires_at") or ""
    try:
        permanent = int(expire[:4]) >= _ANNEE_PERMANENT
    except ValueError:
        permanent = False
    return {
        "nom": entree.get("name") or "",
        "taille_go": round(taille / 1e9, 1),
        "part_gpu": round(100 * vram / taille) if taille else 0,
        "contexte": int(entree.get("context_length") or 0),
        "permanent": permanent,
    }


async def collecter(base_url: str, timeout: float = 15.0,
                    transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """
    Interroge Ollama et rend les faits bruts normalisés. Chaque appel est indépendant : un
    `/api/show` en échec n'empêche pas d'analyser le reste (le modèle est marqué incomplet).
    `transport` ne sert qu'aux tests.
    """
    faits: dict = {"ollama_version": "", "modeles": [], "charges": [], "erreurs": []}
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(timeout, connect=5.0),
                                 transport=transport) as client:
        try:
            faits["ollama_version"] = (await client.get("/api/version")).json().get("version", "")
        except Exception as exc:  # noqa: BLE001 — la version n'est qu'un renseignement
            faits["erreurs"].append(f"version : {exc}")

        resp = await client.get("/api/tags")   # celui-là est indispensable : on laisse remonter
        resp.raise_for_status()
        tags = resp.json().get("models", [])

        try:
            ps = await client.get("/api/ps")
            ps.raise_for_status()
            faits["charges"] = [_normaliser_charge(m) for m in ps.json().get("models", [])]
        except Exception as exc:  # noqa: BLE001
            faits["erreurs"].append(f"modèles chargés : {exc}")

        # `/api/show` renvoie aussi les tenseurs : quelques centaines de Ko par modèle. On borne
        # la concurrence pour ne pas saturer le proxy devant Ollama.
        verrou = asyncio.Semaphore(4)

        async def _show(nom: str) -> dict | None:
            async with verrou:
                try:
                    r = await client.post("/api/show", json={"model": nom})
                    r.raise_for_status()
                    return r.json()
                except Exception as exc:  # noqa: BLE001
                    faits["erreurs"].append(f"détail de {nom} : {exc}")
                    return None

        shows = await asyncio.gather(*(_show(t.get("name", "")) for t in tags))
    faits["modeles"] = sorted(
        (_normaliser_modele(t, s) for t, s in zip(tags, shows)), key=lambda m: m["nom"])
    return faits


# ─── Analyse (règles déterministes) ───────────────────────────────────────────

def _est_embedding(m: dict) -> bool:
    return "embedding" in m["capacites"] or any(h in m["nom"].lower() for h in ("embed", "nomic"))


def _meme_famille(nom: str, installes: list[dict]) -> list[str]:
    """Modèles installés vers lesquels Matothèque peut se replier (même famille que `nom`)."""
    from services.runtime_config import _famille_modele
    fam = _famille_modele(nom)
    return [m["nom"] for m in installes if _famille_modele(m["nom"]) == fam and m["nom"] != nom]


def _taille_q4(m: dict) -> float | None:
    bits = _BITS_PAR_QUANT.get(m["quantisation"])
    return round(m["taille_go"] * _BITS_Q4_K_M / bits, 1) if bits else None


def analyser(faits: dict, usages: dict[str, str], vram_go: float, modele_epingle: str = "",
             num_ctx: int = 0) -> list[Constat]:
    """
    Applique les règles et rend les constats, du plus grave au moins grave.

    `usages` : {usage: modèle} tel que Matothèque le résout réellement (`model_for`).
    `vram_go` : VRAM du GPU, saisie par l'utilisateur (Ollama ne l'expose pas).
    `num_ctx` : contexte que Matothèque envoie à chaque génération (`OLLAMA_NUM_CTX`, 0 = aucun).
    """
    constats: list[Constat] = []
    modeles: list[dict] = faits.get("modeles", [])
    par_nom = {m["nom"]: m for m in modeles}
    epingle = (modele_epingle or "").split(":")[0].lower()

    def _est_epingle(nom: str) -> bool:
        return bool(epingle) and nom.split(":")[0].lower() == epingle

    # 1. Un usage pointe vers un modèle absent — ce qui a cassé la vision le 15/09/2026.
    for usage, nom in sorted(usages.items()):
        if not nom or nom in par_nom:
            continue
        replis = _meme_famille(nom, modeles)
        if replis:
            constats.append(Constat(
                "important", f"Usage « {usage} » : modèle absent",
                f"« {nom} » n'est plus installé. Matothèque se replie sur un modèle de la même "
                f"famille ({', '.join(replis[:3])}), sans garantie de qualité équivalente.",
                f"Choisir un modèle installé pour « {usage} » dans Services & modèles IA, "
                f"ou réinstaller « {nom} ».", nom))
        else:
            constats.append(Constat(
                "critique", f"Usage « {usage} » : modèle absent, aucun repli",
                f"« {nom} » n'est plus installé et aucun modèle de la même famille ne peut le "
                f"remplacer : cet usage échoue.",
                f"Réinstaller « {nom} » ou choisir un autre modèle pour « {usage} ».", nom))

    # 2. Un usage pointe vers un modèle qui n'a pas la capacité requise.
    for usage, nom in usages.items():
        m = par_nom.get(nom)
        if not m or not m["analyse_complete"]:
            continue
        if usage == "vision" and "vision" not in m["capacites"]:
            constats.append(Constat(
                "important", "Usage « vision » : modèle sans vision",
                f"« {nom} » n'annonce pas la capacité vision : la description d'images échouera "
                f"ou sera inventée.", "Choisir un modèle dont les capacités incluent « vision ».", nom))
        if usage == "embeddings" and not _est_embedding(m):
            constats.append(Constat(
                "critique", "Usage « embeddings » : modèle inadapté",
                f"« {nom} » n'est pas un modèle d'embeddings : la recherche sémantique ne peut pas "
                f"fonctionner.", "Choisir un modèle d'embeddings (qwen3-embedding, nomic-embed…).", nom))

    # 3. Le modèle épinglé partagé (JARVIS / Home Assistant) doit exister.
    if modele_epingle and not any(_est_epingle(n) for n in par_nom):
        constats.append(Constat(
            "critique", "Modèle épinglé absent",
            f"« {modele_epingle} » est déclaré comme modèle partagé épinglé, mais il n'est pas "
            f"installé : les services qui s'appuient dessus (JARVIS) ne répondent plus.",
            f"Réinstaller « {modele_epingle} » ou corriger OLLAMA_PINNED_MODEL.", modele_epingle))

    for m in modeles:
        if not m["analyse_complete"]:
            continue
        nom, taille = m["nom"], m["taille_go"]

        # 4. Import sans template de chat : le modèle reçoit du texte brut.
        if not _est_embedding(m) and not m["template_ok"]:
            constats.append(Constat(
                "important", "Importé sans template de chat",
                f"« {nom} » n'a ni RENDERER/PARSER ni TEMPLATE réel : il reçoit la conversation en "
                f"texte brut, sans balises de tour ni tokens d'arrêt. Réponses dégradées, arrêts "
                f"hasardeux — invisible dans un test de débit.",
                "Recréer le modèle (ollama create) en reprenant RENDERER/PARSER et les PARAMETER du "
                "modèle officiel de la même famille.", nom))

        # 5. Quantisation lourde sur un modèle qui déborde de la VRAM.
        q4 = _taille_q4(m)
        if q4 is not None and taille > vram_go * 0.9:
            constats.append(Constat(
                "important", f"Quantisation {m['quantisation']} trop lourde",
                f"« {nom} » pèse {taille} Go en {m['quantisation']} pour {vram_go:g} Go de VRAM. "
                f"En Q4_K_M il pèserait ~{q4} Go : moins de couches sur le CPU, nettement plus "
                f"rapide, pour une perte de qualité faible.",
                "Installer la variante Q4_K_M du même modèle, la valider, puis supprimer celle-ci.", nom))

        # 6. Taille du modèle face à la VRAM : fatal pour un dense, acceptable pour un MoE.
        if taille > vram_go:
            if m["moe"]:
                actifs = f", {m['experts_actifs']} experts actifs sur {m['experts']}" if m["experts"] else ""
                constats.append(Constat(
                    "info", "MoE plus gros que la VRAM",
                    f"« {nom} » ({taille} Go{actifs}) déborde sur le CPU. C'est un MoE : seule une "
                    f"petite partie des poids travaille à chaque token, l'offload reste supportable.",
                    "Rien d'obligatoire. Activer XMP/EXPO sur la RAM accélère les couches déportées.", nom))
            else:
                constats.append(Constat(
                    "important", "Modèle dense plus gros que la VRAM",
                    f"« {nom} » ({taille} Go, dense) ne tient pas dans {vram_go:g} Go : toutes ses "
                    f"couches travaillent à chaque token, celles déportées sur CPU ralentissent tout.",
                    f"Préférer un modèle dense de moins de ~{vram_go * 0.75:.0f} Go ou un MoE.", nom))

    # 7. Modèles chargés : offload, contexte, épinglage.
    for c in faits.get("charges", []):
        m = par_nom.get(c["nom"], {})
        if c["part_gpu"] < 100:
            niveau = "info" if m.get("moe") else "conseil"
            constats.append(Constat(
                niveau, f"Chargé à {c['part_gpu']} % sur le GPU",
                f"« {c['nom']} » occupe {c['taille_go']} Go, dont {100 - c['part_gpu']} % en RAM "
                f"système. D'autres applications occupent peut-être la VRAM.",
                "Fermer les applications gourmandes en VRAM (navigateurs, LM Studio avec un modèle "
                "chargé) ou choisir un modèle plus petit.", c["nom"]))
        if c["contexte"] and c["contexte"] <= 4096 and not _est_embedding(m or {"capacites": [], "nom": c["nom"]}):
            constats.append(Constat(
                "conseil", "Contexte limité à 4096 tokens",
                f"« {c['nom']} » tourne avec {c['contexte']} tokens de contexte : les documents "
                f"longs sont tronqués sans prévenir.",
                "Sur la machine Ollama : OLLAMA_CONTEXT_LENGTH=16384, avec OLLAMA_FLASH_ATTENTION=1 "
                "et OLLAMA_KV_CACHE_TYPE=q8_0 pour limiter le coût mémoire.", c["nom"]))
        # Ollama recharge un modèle dès que `num_ctx` change d'une requête à l'autre. Un modèle
        # chargé avec un autre contexte que celui de Matothèque sera donc rechargé à son prochain
        # appel — et, si c'est le modèle épinglé partagé, rechargé encore par l'autre client.
        if (num_ctx and c["contexte"] and c["contexte"] != num_ctx
                and not _est_embedding(m or {"capacites": [], "nom": c["nom"]})):
            if _est_epingle(c["nom"]):
                constats.append(Constat(
                    "important", "Contexte du modèle partagé différent de Matothèque",
                    f"« {c['nom']} » est chargé avec {c['contexte']} tokens de contexte ; Matothèque "
                    f"envoie {num_ctx}. Ollama recharge le modèle à chaque changement : Matothèque et "
                    f"l'autre client (JARVIS) se le disputent, et chacun repaie le chargement.",
                    f"Aligner OLLAMA_CONTEXT_LENGTH sur la machine Ollama et OLLAMA_NUM_CTX de "
                    f"Matothèque (actuellement {num_ctx}).", c["nom"]))
            else:
                constats.append(Constat(
                    "conseil", "Contexte différent de celui de Matothèque",
                    f"« {c['nom']} » est chargé avec {c['contexte']} tokens ; Matothèque envoie "
                    f"{num_ctx}. Il sera rechargé au prochain appel de Matothèque.",
                    f"Aligner OLLAMA_CONTEXT_LENGTH (machine Ollama) et OLLAMA_NUM_CTX "
                    f"(Matothèque, {num_ctx}).", c["nom"]))
        if c["permanent"] and not _est_epingle(c["nom"]):
            constats.append(Constat(
                "conseil", "Modèle maintenu en mémoire en permanence",
                f"« {c['nom']} » a été chargé avec keep_alive -1 : il garde {c['taille_go']} Go "
                f"réservés même inutilisé.",
                "Identifier le client qui l'épingle, ou le décharger (keep_alive 0).", c["nom"]))

    # 8. Modèles installés qu'aucun usage de Matothèque n'appelle.
    utilises = set(usages.values())
    inutiles = [m for m in modeles if m["nom"] not in utilises and not _est_epingle(m["nom"])]
    if inutiles:
        liste = ", ".join(f"{m['nom']} ({m['taille_go']} Go)" for m in inutiles)
        constats.append(Constat(
            "info", "Modèles non utilisés par Matothèque",
            f"{liste}. Ollama est partagé : un autre service (Open WebUI, agents, Home Assistant) "
            f"s'en sert peut-être.",
            "Vérifier les autres clients d'Ollama avant de supprimer quoi que ce soit."))

    constats.sort(key=lambda c: NIVEAUX.index(c.niveau))
    return constats


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _tableau_modeles(faits: dict) -> str:
    charges = {c["nom"]: c for c in faits.get("charges", [])}
    lignes = ["| Modèle | Paramètres | Quant | Taille | Archi | Capacités | Chargé |",
              "|---|---|---|---|---|---|---|"]
    for m in faits.get("modeles", []):
        archi = f"MoE {m['experts_actifs']}/{m['experts']}" if m["moe"] else "dense"
        c = charges.get(m["nom"])
        charge = f"{c['part_gpu']} % GPU, ctx {c['contexte']}" if c else "—"
        lignes.append(f"| {m['nom']} | {m['parametres'] or '?'} | {m['quantisation'] or '?'} | "
                      f"{m['taille_go']} Go | {archi} | {', '.join(m['capacites']) or '?'} | {charge} |")
    return "\n".join(lignes)


def _materiel(vram_go: float, ram_go: float | None, gpu: str) -> str:
    ram = f"{ram_go:g} Go" if ram_go else "non renseignée"
    return f"GPU : {gpu or 'non précisé'}, {vram_go:g} Go de VRAM · RAM système : {ram}"


def prompt_internet(faits: dict, usages: dict[str, str], constats: list[Constat],
                    vram_go: float, ram_go: float | None = None, gpu: str = "") -> str:
    """
    Prompt à COPIER dans une IA connectée au web. Il ne contient que du matériel, des noms de
    modèles et des réglages : aucun document, chemin, tag ni contenu utilisateur.
    """
    usages_txt = "\n".join(f"- {u} → {n or 'défaut'}" for u, n in sorted(usages.items()))
    constats_txt = "\n".join(f"- [{c.niveau}] {c.titre}" + (f" ({c.modele})" if c.modele else "")
                             for c in constats if c.niveau != "info") or "- aucun"
    return f"""Je fais tourner une IA 100 % locale avec Ollama et j'ai besoin de recommandations À JOUR, vérifiées sur des sources récentes.

## Ma machine
{_materiel(vram_go, ram_go, gpu)}
Ollama {faits.get('ollama_version') or 'version inconnue'}

## Modèles installés
{_tableau_modeles(faits)}

## Rôle de chaque modèle dans mon application (gestion documentaire en français)
{usages_txt}

## Problèmes déjà détectés localement
{constats_txt}

## Ce que je te demande
1. Pour CHAQUE rôle ci-dessus : existe-t-il aujourd'hui un meilleur modèle qui tourne correctement sur ma machine ? Tiens compte de la VRAM : un modèle dense doit tenir en VRAM ; un MoE peut déborder en RAM s'il a peu de paramètres actifs. Priorité à la qualité en français.
2. Pour chaque recommandation : le tag Ollama EXACT (`ollama pull …`), la quantisation, la taille sur disque, et la date de sortie du modèle.
3. Y a-t-il une version d'Ollama plus récente que la mienne, avec des changements utiles pour ma configuration ?
4. Les réglages Ollama recommandés pour ma machine (contexte, flash attention, cache KV, modèles chargés simultanément).

## Contraintes de réponse
- Réponds en français, sous forme de tableau markdown : Rôle | Modèle actuel | Recommandation | Tag ollama pull | Taille | Pourquoi.
- N'invente AUCUN tag, aucune version, aucun chiffre : si tu n'es pas sûr, écris « à vérifier » et cite ta source.
- Si mon modèle actuel reste le meilleur choix pour un rôle, dis-le simplement.
"""


def prompt_synthese_locale(faits: dict, usages: dict[str, str], constats: list[Constat],
                           vram_go: float, ram_go: float | None = None, gpu: str = "") -> tuple[str, str]:
    """(système, utilisateur) pour faire rédiger une synthèse par l'IA locale, sans Internet."""
    systeme = (
        "Tu es un expert en IA locale (Ollama). On te donne le diagnostic factuel d'une installation. "
        "Rédige en français, de façon concise : 1) l'état général en deux phrases ; 2) les actions "
        "prioritaires, numérotées, cinq au maximum, chacune avec sa raison ; 3) ce qui demande une "
        "information récente d'Internet (nouveaux modèles, nouvelle version d'Ollama). Appuie-toi "
        "UNIQUEMENT sur les faits fournis : n'invente aucun nom de modèle, aucune version, aucun chiffre."
    )
    constats_txt = "\n".join(
        f"- [{c.niveau}] {c.titre} : {c.detail}" + (f" → {c.action}" if c.action else "")
        for c in constats) or "- aucun constat"
    usages_txt = "\n".join(f"- {u} → {n or 'défaut'}" for u, n in sorted(usages.items()))
    utilisateur = (
        f"# Diagnostic du {datetime.now():%d/%m/%Y}\n\n## Machine\n{_materiel(vram_go, ram_go, gpu)}\n"
        f"Ollama {faits.get('ollama_version') or 'version inconnue'}\n\n## Modèles\n{_tableau_modeles(faits)}\n\n"
        f"## Usages\n{usages_txt}\n\n## Constats\n{constats_txt}"
    )
    return systeme, utilisateur


def constats_dict(constats: list[Constat]) -> list[dict]:
    return [asdict(c) for c in constats]
