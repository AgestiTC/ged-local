"""
Diagnostic IA : chaque règle rejoue un cas constaté sur PC-GAME le 15/09/2026.

- un 35B-A3B en Q8_0 (43 Go pour 16 Go de VRAM), importé avec `TEMPLATE {{ .Prompt }}` et sans
  RENDERER : du texte brut, sans balises de tour — invisible dans un test de débit ;
- l'usage « vision » pointait vers `qwen2.5vl:7b`, supprimé pendant un ménage : la description
  d'images s'est retrouvée sur un repli ou en échec, sans que rien ne le signale ;
- `llama3.1` chargé « Forever » : volontaire (modèle épinglé partagé avec JARVIS), il ne doit
  PAS être présenté comme un problème.
"""

import httpx
import pytest

from services import diagnostic_ia as diag


def _modele(nom, taille_go, quant="Q4_K_M", moe=False, capacites=("completion",), template_ok=True):
    return {
        "nom": nom, "taille_go": taille_go, "parametres": "", "quantisation": quant,
        "architecture": "x", "moe": moe, "experts": 256 if moe else 0, "experts_actifs": 8 if moe else 0,
        "contexte_max": 262144, "capacites": list(capacites), "projecteur": "vision" in capacites,
        "template_ok": template_ok, "analyse_complete": True,
    }


EMBED = _modele("qwen3-embedding:8b", 4.7, capacites=("embedding",), template_ok=False)
LLAMA = _modele("llama3.1:latest", 4.9, capacites=("completion", "tools"))
MINISTRAL = _modele("ministral-3:14b", 9.1, capacites=("completion", "vision", "tools"))

USAGES_OK = {"rapport": "ministral-3:14b", "chat": "llama3.1:latest", "enrichissement": "llama3.1:latest",
             "embeddings": "qwen3-embedding:8b", "vision": "ministral-3:14b"}


def _titres(constats, niveau=None):
    return [c.titre for c in constats if niveau is None or c.niveau == niveau]


class TestInstallationSaine:
    def test_aucun_probleme_signale(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL], "charges": []}
        constats = diag.analyser(faits, USAGES_OK, 16, "llama3.1:latest")
        assert [c for c in constats if c.niveau in ("critique", "important", "conseil")] == []

    def test_un_modele_d_embeddings_n_a_pas_besoin_de_template(self):
        """Un modèle d'embeddings ne converse pas : son template vide est normal."""
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL], "charges": []}
        assert "Importé sans template de chat" not in _titres(diag.analyser(faits, USAGES_OK, 16))


class TestUsages:
    def test_usage_vers_modele_supprime_avec_repli(self):
        """Le cas du 15/09 : vision → qwen2.5vl supprimé, un autre modèle « vision » installé."""
        autre_vl = _modele("llava:7b", 4.7, capacites=("completion", "vision"))
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL, autre_vl], "charges": []}
        constats = diag.analyser(faits, {**USAGES_OK, "vision": "qwen2.5vl:7b"}, 16)
        c = next(c for c in constats if c.modele == "qwen2.5vl:7b")
        assert c.niveau == "important" and "llava:7b" in c.detail

    def test_usage_vers_modele_supprime_sans_repli_est_critique(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL], "charges": []}
        constats = diag.analyser(faits, {**USAGES_OK, "vision": "qwen2.5vl:7b"}, 16)
        assert "Usage « vision » : modèle absent, aucun repli" in _titres(constats, "critique")

    def test_vision_confiee_a_un_modele_sans_vision(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL], "charges": []}
        constats = diag.analyser(faits, {**USAGES_OK, "vision": "llama3.1:latest"}, 16)
        assert "Usage « vision » : modèle sans vision" in _titres(constats, "important")

    def test_embeddings_confies_a_un_modele_de_texte(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL], "charges": []}
        constats = diag.analyser(faits, {**USAGES_OK, "embeddings": "llama3.1:latest"}, 16)
        assert "Usage « embeddings » : modèle inadapté" in _titres(constats, "critique")

    def test_modele_epingle_absent(self):
        faits = {"modeles": [EMBED, MINISTRAL], "charges": []}
        usages = {**USAGES_OK, "chat": "ministral-3:14b", "enrichissement": "ministral-3:14b"}
        assert "Modèle épinglé absent" in _titres(diag.analyser(faits, usages, 16, "llama3.1:latest"), "critique")


class TestModeles:
    def test_le_q8_de_43_go_sans_template(self):
        """Le cas du 15/09, trois défauts d'un coup."""
        q8 = _modele("Qwen3.6-35B:latest", 43.0, quant="Q8_0", moe=True, template_ok=False)
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL, q8], "charges": []}
        constats = [c for c in diag.analyser(faits, {**USAGES_OK, "rapport": q8["nom"]}, 16) if c.modele == q8["nom"]]
        titres = _titres(constats)
        assert "Importé sans template de chat" in titres
        assert "Quantisation Q8_0 trop lourde" in titres
        # MoE : l'offload n'est qu'une information, pas une alerte.
        assert ("info", "MoE plus gros que la VRAM") in [(c.niveau, c.titre) for c in constats]
        quant = next(c for c in constats if c.titre.startswith("Quantisation"))
        assert "~24.5 Go" in quant.detail   # 43 × 4,85 / 8,5 — cohérent avec les 22 Go mesurés

    def test_dense_plus_gros_que_la_vram_est_important(self):
        dense = _modele("qwen3.8:27b", 17.9)
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL, dense], "charges": []}
        constats = diag.analyser(faits, {**USAGES_OK, "rapport": dense["nom"]}, 16)
        assert "Modèle dense plus gros que la VRAM" in _titres(constats, "important")

    def test_la_vram_saisie_change_le_verdict(self):
        """Le même modèle tient sur une carte de 24 Go."""
        dense = _modele("qwen3.8:27b", 17.9)
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL, dense], "charges": []}
        assert "Modèle dense plus gros que la VRAM" not in _titres(
            diag.analyser(faits, {**USAGES_OK, "rapport": dense["nom"]}, 24))

    def test_modele_analyse_incompletement_n_est_pas_juge(self):
        """Sans /api/show on ne sait rien du template : ne pas inventer de défaut."""
        inconnu = {**_modele("mystere:1b", 30.0, template_ok=False), "analyse_complete": False}
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL, inconnu], "charges": []}
        assert [c for c in diag.analyser(faits, USAGES_OK, 16) if c.modele == "mystere:1b"] == []


class TestModelesCharges:
    def test_epinglage_volontaire_non_signale(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL],
                 "charges": [{"nom": "llama3.1:latest", "taille_go": 6.0, "part_gpu": 100, "contexte": 16384, "permanent": True}]}
        assert "Modèle maintenu en mémoire en permanence" not in _titres(
            diag.analyser(faits, USAGES_OK, 16, "llama3.1:latest"))

    def test_epinglage_d_un_autre_modele_signale(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL],
                 "charges": [{"nom": "ministral-3:14b", "taille_go": 9.5, "part_gpu": 100, "contexte": 16384, "permanent": True}]}
        assert "Modèle maintenu en mémoire en permanence" in _titres(
            diag.analyser(faits, USAGES_OK, 16, "llama3.1:latest"), "conseil")

    def test_contexte_par_defaut_d_ollama(self):
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL],
                 "charges": [{"nom": "llama3.1:latest", "taille_go": 5.3, "part_gpu": 100, "contexte": 4096, "permanent": False}]}
        c = next(c for c in diag.analyser(faits, USAGES_OK, 16) if c.titre.startswith("Contexte"))
        assert "OLLAMA_CONTEXT_LENGTH" in c.action

    def test_offload_d_un_dense_est_un_conseil_d_un_moe_une_info(self):
        moe = _modele("qwen3.6:35b-a3b", 22.0, moe=True)
        faits = {"modeles": [EMBED, LLAMA, MINISTRAL, moe], "charges": [
            {"nom": "ministral-3:14b", "taille_go": 9.5, "part_gpu": 80, "contexte": 16384, "permanent": False},
            {"nom": moe["nom"], "taille_go": 22.0, "part_gpu": 63, "contexte": 16384, "permanent": False},
        ]}
        niveaux = {c.modele: c.niveau for c in diag.analyser(faits, USAGES_OK, 16) if "sur le GPU" in c.titre}
        assert niveaux == {"ministral-3:14b": "conseil", moe["nom"]: "info"}


class TestNormalisation:
    def test_template_brut_sans_renderer(self):
        show = {"template": "{{ .Prompt }}", "modelfile": "FROM x\nTEMPLATE {{ .Prompt }}", "capabilities": ["completion"]}
        assert diag._normaliser_modele({"name": "a", "size": 1}, show)["template_ok"] is False

    def test_renderer_suffit_meme_avec_template_brut(self):
        """Ollama récent : `TEMPLATE {{ .Prompt }}` + `RENDERER qwen3.5` est un import CORRECT."""
        show = {"template": "{{ .Prompt }}", "modelfile": "FROM x\nRENDERER qwen3.5\nPARSER qwen3.5"}
        assert diag._normaliser_modele({"name": "a", "size": 1}, show)["template_ok"] is True

    def test_moe_detecte_par_le_nombre_d_experts(self):
        show = {"model_info": {"general.architecture": "qwen35moe", "qwen35moe.expert_count": 256,
                               "qwen35moe.expert_used_count": 8, "qwen35moe.context_length": 262144}}
        m = diag._normaliser_modele({"name": "a", "size": 22e9, "details": {"quantization_level": "Q4_K_M"}}, show)
        assert (m["moe"], m["experts"], m["experts_actifs"], m["contexte_max"]) == (True, 256, 8, 262144)

    def test_keep_alive_moins_un_se_lit_dans_la_date_d_expiration(self):
        """Ollama ne dit pas « permanent » : il repousse l'expiration de plusieurs siècles."""
        c = diag._normaliser_charge({"name": "llama3.1:latest", "size": 6e9, "size_vram": 6e9,
                                     "expires_at": "2318-12-26T13:24:46+01:00", "context_length": 16384})
        assert c["permanent"] is True and c["part_gpu"] == 100

    def test_quantisation_inconnue_d_un_gguf_hugging_face(self):
        """Ollama renvoie « unknown » pour certains imports hf.co : ne pas l'afficher tel quel."""
        m = diag._normaliser_modele({"name": "hf.co/x", "size": 1, "details": {"quantization_level": "unknown"}}, {})
        assert m["quantisation"] == ""

    def test_part_gpu(self):
        c = diag._normaliser_charge({"name": "m", "size": 22e9, "size_vram": 13.86e9,
                                     "expires_at": "2026-09-15T12:00:00+02:00"})
        assert (c["part_gpu"], c["permanent"]) == (63, False)


class TestPrompts:
    def test_le_prompt_internet_ne_contient_que_du_materiel_et_des_modeles(self):
        faits = {"ollama_version": "0.34.0", "modeles": [EMBED, LLAMA, MINISTRAL], "charges": []}
        constats = diag.analyser(faits, USAGES_OK, 16)
        texte = diag.prompt_internet(faits, USAGES_OK, constats, 16, 64, "RTX 4080 SUPER")
        for attendu in ("RTX 4080 SUPER, 16 Go de VRAM", "RAM système : 64 Go", "Ollama 0.34.0",
                        "ministral-3:14b", "N'invente AUCUN tag"):
            assert attendu in texte

    def test_ram_non_renseignee(self):
        faits = {"modeles": [LLAMA], "charges": []}
        assert "RAM système : non renseignée" in diag.prompt_internet(faits, {}, [], 16)

    def test_synthese_locale_interdit_l_invention(self):
        faits = {"modeles": [LLAMA], "charges": []}
        systeme, utilisateur = diag.prompt_synthese_locale(faits, {"chat": "llama3.1:latest"}, [], 16)
        assert "n'invente aucun nom de modèle" in systeme
        assert "llama3.1:latest" in utilisateur


@pytest.mark.asyncio
async def test_collecte_resiste_a_un_show_en_echec():
    """Un modèle dont `/api/show` échoue reste listé, marqué incomplet ; le reste est analysé."""
    def repondre(requete: httpx.Request) -> httpx.Response:
        chemin = requete.url.path
        if chemin == "/api/version":
            return httpx.Response(200, json={"version": "0.34.0"})
        if chemin == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "llama3.1:latest", "size": 4.9e9, "details": {"parameter_size": "8.0B", "quantization_level": "Q4_K_M"}},
                {"name": "casse:1b", "size": 1e9, "details": {}},
            ]})
        if chemin == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if chemin == "/api/show":
            if b"casse" in requete.content:
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(200, json={"capabilities": ["completion"], "modelfile": "RENDERER x"})
        return httpx.Response(404)

    faits = await diag.collecter("http://ollama", transport=httpx.MockTransport(repondre))
    par_nom = {m["nom"]: m for m in faits["modeles"]}
    assert faits["ollama_version"] == "0.34.0"
    assert par_nom["llama3.1:latest"]["analyse_complete"] is True
    assert par_nom["casse:1b"]["analyse_complete"] is False
    assert any("casse:1b" in e for e in faits["erreurs"])


@pytest.mark.asyncio
async def test_endpoint_usages_reels_et_prompts(client, monkeypatch):
    """
    Le routeur doit analyser les modèles RÉELLEMENT appelés : embeddings et vision ne passent pas
    par `model_for` (qui retombe sur le modèle par défaut), et le repli des embeddings compte
    comme utilisé.
    """
    from routers import system as routeur

    async def faux_collecter(_base_url, **_kw):
        return {"ollama_version": "0.34.0", "modeles": [EMBED, LLAMA, MINISTRAL], "charges": [], "erreurs": []}

    monkeypatch.setattr(diag, "collecter", faux_collecter)
    monkeypatch.setattr(routeur.settings, "ollama_model_embedding", "qwen3-embedding:8b", raising=False)
    monkeypatch.setattr(routeur.settings, "ollama_model_embedding_fallback", "nomic-embed-text:latest", raising=False)

    r = await client.get("/api/system/diagnostic-ia", params={"vram_go": 16, "ram_go": 64, "gpu": "RTX 4080 SUPER"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["usages"]["embeddings"] == "qwen3-embedding:8b"
    assert corps["usages"]["embeddings_repli"] == "nomic-embed-text:latest"
    assert "RTX 4080 SUPER, 16 Go de VRAM" in corps["prompt_internet"]
    assert corps["prompt_local"]["systeme"] and corps["prompt_local"]["utilisateur"]
    # Le repli absent est signalé, avec le modèle principal comme solution de repli.
    absent = next(c for c in corps["constats"] if c["modele"] == "nomic-embed-text:latest")
    assert absent["niveau"] == "important"


@pytest.mark.asyncio
async def test_endpoint_ollama_injoignable(client, monkeypatch):
    async def en_panne(_base_url, **_kw):
        raise httpx.ConnectError("refus")

    monkeypatch.setattr(diag, "collecter", en_panne)
    r = await client.get("/api/system/diagnostic-ia")
    assert r.status_code == 503 and "Ollama injoignable" in r.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_refuse_une_vram_absurde(client):
    assert (await client.get("/api/system/diagnostic-ia", params={"vram_go": 0})).status_code == 422
