"""
Catalogue descriptif des modèles IA
===================================
Fournit, pour chaque modèle Ollama installé, un descriptif (« que fait ce modèle ? ») et une
évaluation qualitative (écriture FR, vitesse, VRAM, verdict) — pour l'icône « i » d'aide et le
tableau comparatif des Paramètres.

**Dynamique** : le tableau est construit à partir des modèles réellement installés. Les modèles
connus sont décrits par une base ci-dessous ; un modèle INCONNU (futur) obtient un descriptif
DÉRIVÉ (rôle deviné du nom, vitesse de la taille de paramètres, VRAM de la taille du fichier) →
il apparaît automatiquement, et un modèle supprimé disparaît (puisqu'on part de la liste installée).

Repère matériel des verdicts : RTX 4080 SUPER, **16 Go de VRAM** (l'embedding GED prend ~4,7 Go) —
cf. [docs/ia-locale-pc-game.md](../../docs/ia-locale-pc-game.md).

⚠️ **Cette base vieillit** : elle a longtemps décrit comme « modèle principal » un modèle supprimé
depuis. Elle ne sert donc plus qu'au descriptif HUMAIN (à quoi sert le modèle, qualité d'écriture
en français) ; tout ce qui se mesure — rôle, vitesse, VRAM, verdict — est recalculé depuis
l'installation réelle par `evaluer()` via le bouton « Mettre à jour le tableau ».
"""
from __future__ import annotations

# Base de connaissance : (sous-chaîne du nom en minuscules) → description. Première correspondance.
# Champs : role · resume · ecriture_fr · vitesse · verdict.
_KB: list[tuple[str, dict]] = [
    ("qwen3-embedding", {
        "role": "Embeddings", "resume": "Vectorise les documents pour la recherche sémantique (4096 dim). Modèle d'embedding principal.",
        "ecriture_fr": "—", "vitesse": "Rapide", "verdict": "🟢 Cœur de la recherche sémantique — ne pas retirer."}),
    ("nomic-embed", {
        "role": "Embeddings", "resume": "Embeddings légers (274 Mo) — REPLI des embeddings principaux (OLLAMA_MODEL_EMBEDDING_FALLBACK) : il est bien utilisé, malgré les apparences.",
        "ecriture_fr": "—", "vitesse": "Très rapide", "verdict": "🟢 Fallback embeddings léger."}),
    ("embed", {
        "role": "Embeddings", "resume": "Modèle d'embeddings (vectorisation de texte).",
        "ecriture_fr": "—", "vitesse": "Rapide", "verdict": "Embeddings."}),
    ("qwen2.5vl", {
        # Préférence MESURÉE, que les faits ne peuvent pas déduire : à capacités égales, ce
        # modèle dédié décrit mieux les images qu'un généraliste multimodal plus gros.
        "prefere_pour": "vision",
        "role": "Vision", "resume": "Décrit les images et fait l'OCR de secours (multimodal). Utilisé pour « décrire les images ».",
        "ecriture_fr": "—", "vitesse": "Correcte",
        "verdict": "🟢 Vision de Matothèque (vision_model) — sa suppression casse la description d'images, sans message."}),
    ("llava", {
        "role": "Vision", "resume": "Vision dépassée (non câblée).",
        "ecriture_fr": "—", "vitesse": "Correcte", "verdict": "⚠️ Remplacé par qwen2.5vl."}),
    ("glm-ocr", {
        "role": "OCR", "resume": "OCR faible (1,1B), supplanté par Tesseract/Tika.",
        "ecriture_fr": "—", "vitesse": "Rapide", "verdict": "🔴 Obsolète (retrait possible)."}),
    ("ministral", {
        "role": "Texte / Chat", "resume": "Génération française de qualité (Mistral). Modèle des rapports ; bon aussi pour le chat.",
        "ecriture_fr": "✅ Excellente (très bon FR)", "vitesse": "🟠 Correcte (14B)",
        "verdict": "✅ Qualité — mails/courriers soignés, rapports."}),
    ("mixtral", {
        "role": "Texte", "resume": "Ancien modèle principal (26 Go), dense : ne tient pas sur 16 Go de VRAM.",
        "ecriture_fr": "✅ Bonne", "vitesse": "🔴 Lourd", "verdict": "⚠️ Legacy — un MoE rend le même service en deux fois moins lourd."}),
    ("mistral", {
        "role": "Texte", "resume": "Génération légère, redondante avec llama3.1.",
        "ecriture_fr": "🟢 Bonne", "vitesse": "✅ Rapide", "verdict": "⚠️ Legacy."}),
    ("llama3.1", {
        "role": "Texte / Chat", "resume": "Modèle PAR DÉFAUT : enrichissement (catégorie/tags/résumé) et chat rapide. ⚠️ ÉPINGLÉ en mémoire car partagé avec JARVIS (Home Assistant) — ne pas supprimer.",
        "ecriture_fr": "🟢 Bonne", "vitesse": "✅ Rapide (8B)",
        "verdict": "✅ Défaut polyvalent — chat + RAG, léger en VRAM."}),
    ("qwen3.6", {
        "role": "Texte / Vision (raisonnement)",
        "resume": "MoE 34,7B dont ~8 experts actifs sur 256 : raisonnement et vision, sans le coût d'un dense de sa taille. Mesuré à 25,3 tok/s en Q4_K_M, malgré 37 % des couches sur CPU.",
        "ecriture_fr": "✅✅ Excellente", "vitesse": "🟠 Correcte (MoE, offload partiel)",
        "verdict": "✅ En Q4_K_M. ❌ Jamais en Q8_0 : −58 % de débit pour une qualité à peine meilleure."}),
    ("qwythos", {
        "role": "Texte (non censuré)", "resume": "Modèle importé, non censuré.",
        "ecriture_fr": "🟢 Bonne", "vitesse": "🟠 Correcte", "verdict": "Usage spécifique."}),
]


def _role_devine(nom: str) -> str:
    n = nom.lower()
    if "embed" in n or "nomic" in n:
        return "Embeddings"
    if any(h in n for h in ("vl", "vision", "llava", "minicpm-v", "moondream")):
        return "Vision"
    if "ocr" in n:
        return "OCR"
    return "Texte / Chat"


def _note_vram(gb: float) -> str:
    if gb <= 0:
        return "—"
    if gb < 6:
        return f"{gb:.1f} Go — ✅ tient large (marge pour l'embedding)"
    if gb < 12:
        return f"{gb:.1f} Go — 🟠 OK, serré avec l'embedding (mode GED)"
    if gb < 16:
        return f"{gb:.1f} Go — 🟠 tient seul, tendu avec l'embedding"
    return f"{gb:.1f} Go — 🔴 déborde de la VRAM 16 Go → lent"


def _vitesse_taille(params: str | None, gb: float) -> str:
    p = (params or "").lower()
    if any(t in p for t in ("1b", "2b", "3b", "4b")) or gb < 4:
        return "✅ Très rapide"
    if any(t in p for t in ("7b", "8b", "9b")) or gb < 7:
        return "✅ Rapide"
    if any(t in p for t in ("13b", "14b")) or gb < 12:
        return "🟠 Correcte"
    return "🔴 Lente (gros modèle)"


def _role_mesure(capacites: list[str], nom: str) -> str:
    """Rôle d'après les CAPACITÉS annoncées par Ollama, bien plus sûr qu'un motif de nom."""
    if "embedding" in capacites:
        return "Embeddings"
    if "vision" in capacites:
        return "Texte / Vision" if "completion" in capacites else "Vision"
    if "completion" in capacites:
        return "Texte / Chat" + (" (raisonnement)" if "thinking" in capacites else "")
    return _role_devine(nom)


def _vitesse_mesuree(m: dict, charge: dict | None) -> str:
    """
    Vitesse attendue. Un MoE se juge sur ses paramètres ACTIFS, pas sur sa taille : un 35B-A3B
    de 22 Go répond plus vite qu'un dense de 22 Go. Si le modèle est chargé, la part réellement
    sur GPU est mesurée — plus fiable que toute estimation.
    """
    if charge and charge.get("part_gpu", 0) < 100:
        return f"🟠 {charge['part_gpu']} % sur GPU (le reste en RAM)"
    if charge:
        return "✅ Rapide (100 % GPU)"
    if m.get("moe") and m.get("experts") and m.get("experts_actifs"):
        return f"✅ Rapide malgré sa taille (MoE, {m['experts_actifs']}/{m['experts']} experts actifs)"
    return _vitesse_taille(m.get("parametres"), m.get("taille_go", 0))


def _vram_mesuree(taille_go: float, vram_go: float, moe: bool, charge: dict | None) -> str:
    if charge:
        etat = "tient entièrement en VRAM" if charge.get("part_gpu") == 100 else \
               f"chargé à {charge['part_gpu']} % en VRAM"
        return f"{taille_go} Go — mesuré : {etat}"
    if taille_go > vram_go:
        return (f"{taille_go} Go — 🟠 dépasse {vram_go:g} Go, mais MoE : offload supportable" if moe
                else f"{taille_go} Go — 🔴 dépasse {vram_go:g} Go de VRAM → lent")
    if taille_go > vram_go * 0.75:
        return f"{taille_go} Go — 🟠 tient seul, tendu avec l'embedding"
    return f"{taille_go} Go — ✅ tient large sur {vram_go:g} Go"


_VERDICT_NIVEAU = {"critique": "🔴", "important": "🟠", "conseil": "🔵"}


def evaluer(m: dict, vram_go: float, constats: list, charge: dict | None = None,
            usages: dict[str, str] | None = None, resume_ia: str = "") -> dict:
    """
    Évaluation d'un modèle à partir des FAITS relevés sur l'installation (diagnostic), et non
    d'une base écrite à la main : taille, quantisation, MoE, capacités, part réelle en VRAM.

    Ce qui ne se mesure pas — la qualité d'écriture en français, le résumé de ce que fait le
    modèle — vient de la base `_KB` si le modèle y figure, sinon du résumé rédigé par l'IA
    locale (`resume_ia`) s'il a été demandé. Jamais inventé ici.

    `constats` : les constats du diagnostic CONCERNANT ce modèle (ils donnent le verdict).
    """
    nom = m.get("nom") or m.get("name") or ""
    taille_go = m.get("taille_go", 0)
    connu = next((info for cle, info in _KB if cle in nom.lower()), None)

    roles = [u for u, mod in (usages or {}).items() if mod == nom]
    if constats:
        pire = min(constats, key=lambda c: ("critique", "important", "conseil", "info").index(c["niveau"]))
        verdict = f"{_VERDICT_NIVEAU.get(pire['niveau'], 'ℹ️')} {pire['titre']} — {pire['action'] or pire['detail']}"
    elif roles:
        verdict = f"✅ En service : {', '.join(sorted(roles))}."
    else:
        verdict = "🟢 Rien à signaler — aucun usage de Matothèque ne l'appelle."

    if connu:
        resume, ecriture = connu["resume"], connu["ecriture_fr"]
    elif resume_ia:
        resume, ecriture = resume_ia, "À évaluer"
    else:
        quant = f", {m['quantisation']}" if m.get("quantisation") else ""
        resume = (f"Modèle non répertorié — {m.get('parametres') or 'taille inconnue'}{quant}, "
                  f"capacités : {', '.join(m.get('capacites') or []) or 'inconnues'}.")
        ecriture = "À évaluer"

    role = _role_mesure(m.get("capacites") or [], nom)
    return {
        "role": role,
        "resume": resume,
        "ecriture_fr": ecriture if role.startswith("Texte") else "—",
        "vitesse": _vitesse_mesuree(m, charge),
        "vram": _vram_mesuree(taille_go, vram_go, bool(m.get("moe")), charge),
        "verdict": verdict,
        "taille_go": taille_go,
        "connu": bool(connu),
        "source": "ia" if (resume_ia and not connu) else ("catalogue" if connu else "auto"),
        # Faits conservés : ils servent à recommander un modèle par usage sans réinterroger
        # Ollama, et à afficher l'architecture dans le tableau.
        "capacites": list(m.get("capacites") or []),
        "parametres": m.get("parametres") or "",
        "quantisation": m.get("quantisation") or "",
        "moe": bool(m.get("moe")),
    }


def _milliards(parametres: str) -> float:
    """« 34.7B » → 34.7 ; « 137M » → 0.137 ; inconnu → 0."""
    texte = (parametres or "").strip().upper()
    try:
        if texte.endswith("B"):
            return float(texte[:-1])
        if texte.endswith("M"):
            return float(texte[:-1]) / 1000
    except ValueError:
        pass
    return 0.0


def recommander(evaluations: dict[str, dict], vram_go: float) -> dict[str, str | None]:
    """
    Meilleur modèle INSTALLÉ pour chaque usage, d'après les faits (capacités annoncées par
    Ollama, taille, MoE) — et non d'après des motifs dans le nom, qui classaient « vision »
    tout modèle contenant « vl » et ignoraient un modèle multimodal au nom neutre.

    Un MoE compte comme tenant en VRAM : seule une fraction de ses poids travaille par token.
    """
    def tient(e: dict) -> bool:
        return e.get("moe") or e.get("taille_go", 0) <= vram_go * 0.9

    items = [(nom, e) for nom, e in evaluations.items()]
    textes = [(n, e) for n, e in items if "completion" in e.get("capacites", [])]
    visions = [(n, e) for n, e in items if "vision" in e.get("capacites", [])]
    embeds = [(n, e) for n, e in items if "embedding" in e.get("capacites", [])]

    def prefere(candidats, usage: str) -> str | None:
        """
        Préférence écrite dans `_KB` pour cet usage — la seule chose que les faits ne disent pas.
        Une capacité `vision` annoncée ne dit rien de la QUALITÉ des descriptions : à capacités
        égales, un modèle dédié bat un généraliste multimodal plus gros, et ça se mesure, ça ne
        se déduit pas. La préférence ne s'applique que si le modèle est exploitable ici.
        """
        for nom, e in candidats:
            info = next((i for cle, i in _KB if cle in nom.lower()), None)
            if info and info.get("prefere_pour") == usage and e.get("taille_go", 0) <= vram_go * 0.9:
                return nom
        return None

    def plus_capable(candidats, sans_offload: bool = False):
        """
        Le plus gros modèle qui reste exploitable ici (paramètres, puis taille).

        `sans_offload` écarte d'abord tout ce qui déborde de la VRAM, MoE compris : pour un
        travail en LOT (décrire les images de toute une indexation), un modèle qui tient
        entièrement en mémoire finit largement avant un modèle plus savant à moitié sur CPU.
        """
        utilisables = [c for c in candidats if tient(c[1])] or candidats
        if sans_offload:
            utilisables = [c for c in utilisables if c[1].get("taille_go", 0) <= vram_go * 0.9] or utilisables
        return max(utilisables, key=lambda c: (_milliards(c[1].get("parametres", "")), c[1].get("taille_go", 0)),
                   default=(None, None))[0]

    def plus_rapide(candidats):
        """Le plus petit modèle qui tient confortablement : c'est la réactivité qui prime."""
        confortables = [c for c in candidats if c[1].get("taille_go", 0) <= vram_go * 0.7 and not c[1].get("moe")]
        return min(confortables or candidats, key=lambda c: c[1].get("taille_go", 0), default=(None, None))[0]

    # Un modèle d'embeddings ne dialogue pas : on l'écarte des usages de texte.
    textes_purs = [(n, e) for n, e in textes if "embedding" not in e.get("capacites", [])]
    rapide = plus_rapide(textes_purs)
    return {
        "rapport": plus_capable(textes_purs),
        "chat": rapide,
        "enrichissement": rapide,
        "resume_modele": rapide,
        # Travail en LOT (indexation) : la vitesse prime, d'où `sans_offload`.
        "vision": prefere(visions, "vision") or plus_capable(visions, sans_offload=True),
        "embeddings": plus_capable(embeds),
    }


def decrire(nom: str, size_octets: int = 0, parametres: str | None = None) -> dict:
    """Descriptif + évaluation d'un modèle. Connu → base ; inconnu → dérivé (rôle/vitesse/VRAM)."""
    gb = (size_octets or 0) / 1e9
    n = (nom or "").lower()
    for cle, info in _KB:
        if cle in n:
            return {**info, "vram": _note_vram(gb), "taille_go": round(gb, 1), "connu": True}
    # Modèle inconnu (futur) : dérivation best-effort.
    role = _role_devine(nom)
    est_texte = role.startswith("Texte")
    return {
        "role": role,
        "resume": "Modèle non répertorié — évaluation automatique d'après sa taille.",
        "ecriture_fr": "À évaluer" if est_texte else "—",
        "vitesse": _vitesse_taille(parametres, gb),
        "vram": _note_vram(gb),
        "verdict": "❔ Non évalué — à tester.",
        "taille_go": round(gb, 1),
        "connu": False,
    }
