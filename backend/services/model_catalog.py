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

Repère matériel des verdicts : RTX 4080 SUPER, **16 Go de VRAM** (l'embedding GED prend ~4,7 Go).
"""
from __future__ import annotations

# Base de connaissance : (sous-chaîne du nom en minuscules) → description. Première correspondance.
# Champs : role · resume · ecriture_fr · vitesse · verdict.
_KB: list[tuple[str, dict]] = [
    ("qwen3-embedding", {
        "role": "Embeddings", "resume": "Vectorise les documents pour la recherche sémantique (4096 dim). Modèle d'embedding principal.",
        "ecriture_fr": "—", "vitesse": "Rapide", "verdict": "🟢 Cœur de la recherche sémantique — ne pas retirer."}),
    ("nomic-embed", {
        "role": "Embeddings", "resume": "Embeddings légers (274 Mo), repli rapide.",
        "ecriture_fr": "—", "vitesse": "Très rapide", "verdict": "🟢 Fallback embeddings léger."}),
    ("embed", {
        "role": "Embeddings", "resume": "Modèle d'embeddings (vectorisation de texte).",
        "ecriture_fr": "—", "vitesse": "Rapide", "verdict": "Embeddings."}),
    ("qwen2.5vl", {
        "role": "Vision", "resume": "Décrit les images et fait l'OCR de secours (multimodal). Utilisé pour « décrire les images ».",
        "ecriture_fr": "—", "vitesse": "Correcte", "verdict": "🟢 Vision recommandée."}),
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
        "role": "Texte", "resume": "Ancien modèle principal (26 Go), redondant avec Qwen3.6-35B.",
        "ecriture_fr": "✅ Bonne", "vitesse": "🔴 Lourd", "verdict": "⚠️ Legacy — retrait possible."}),
    ("mistral", {
        "role": "Texte", "resume": "Génération légère, redondante avec llama3.1.",
        "ecriture_fr": "🟢 Bonne", "vitesse": "✅ Rapide", "verdict": "⚠️ Legacy."}),
    ("llama3.1", {
        "role": "Texte / Chat", "resume": "Modèle PAR DÉFAUT : enrichissement (catégorie/tags/résumé) et chat rapide. Grand contexte.",
        "ecriture_fr": "🟢 Bonne", "vitesse": "✅ Rapide (8B)",
        "verdict": "✅ Défaut polyvalent — chat + RAG, léger en VRAM."}),
    ("qwen3.6-35b", {
        "role": "Raisonnement", "resume": "Raisonnement haut de gamme (MoE ~35B, 44 Go). Pour rapports exigeants.",
        "ecriture_fr": "✅✅ Excellente", "vitesse": "🔴 Ne tient pas en VRAM 16 Go → lent/502",
        "verdict": "❌ À éviter en chat — rapports lourds uniquement."}),
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
