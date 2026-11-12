"""Vision en une passe (plan lots IA, étape 2) : une seule demande par image ou par page.

Avant : une passe « transcription », puis (si aucun texte) une passe « description » sur toutes
les pages — un PDF de photos = 20 appels. Aucun appel réseau : `generate` est bouchonné.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import extraction
from services.extraction import ExtractionService


@pytest.fixture
def candidats(monkeypatch):
    """Liste de modèles candidats pilotable, sans interroger ni la base ni Ollama."""
    from services import runtime_config
    etat = {"modeles": ["modele-a"]}

    async def liste(usage):
        return list(etat["modeles"])

    monkeypatch.setattr(runtime_config, "model_candidates", liste)
    return etat


def _service(*reponses, **kw) -> tuple[ExtractionService, AsyncMock]:
    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=list(reponses)) if reponses else AsyncMock(**kw)
    return ExtractionService(None, ollama, None), ollama.generate


@pytest.fixture
def image(tmp_path):
    f = tmp_path / "photo-fictive.png"
    f.write_bytes(b"PNG fictif")
    return f


@pytest.fixture
def pdf_de(monkeypatch, tmp_path):
    """Un PDF fictif dont la rastérisation rend N pages (octets bidon, rien n'est lu)."""
    def fabrique(n: int):
        monkeypatch.setattr(extraction, "_rasteriser_pdf",
                            lambda chemin, max_pages: [f"page{i}".encode() for i in range(min(n, max_pages))])
        f = tmp_path / "scan-fictif.pdf"
        f.write_bytes(b"%PDF fictif")
        return f
    return fabrique


DESCRIPTION = "Une photo d'un chantier : une grue jaune, trois ouvriers, un ciel couvert."


# ─── image ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_image_avec_texte_un_seul_appel(candidats, image):
    svc, generate = _service("Facture n° 42 — total 120 €")
    assert await svc._ocr_fallback_sans_usage(image, "png") == "Facture n° 42 — total 120 €"
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_photo_sans_texte_un_seul_appel_et_la_description_est_rendue(candidats, image):
    svc, generate = _service(DESCRIPTION)
    assert await svc._ocr_fallback_sans_usage(image, "png") == DESCRIPTION
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_la_consigne_unique_demande_transcription_puis_description(candidats, image):
    svc, generate = _service(DESCRIPTION)
    await svc._ocr_fallback_sans_usage(image, "png")
    consigne = generate.await_args.args[0].lower()
    assert "transcri" in consigne and "décri" in consigne
    assert generate.await_args.kwargs["model"] == "modele-a"
    assert len(generate.await_args.kwargs["images"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reponse", ["(aucun texte)", "  (Aucun texte) \n", "[aucun texte]", "", None, "  ", "ok"])
async def test_reponse_vide_ou_sentinelle_seule_rend_vide_sans_second_appel(candidats, image, reponse):
    svc, generate = _service(reponse)
    assert await svc._ocr_fallback_sans_usage(image, "png") == ""
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_sentinelle_suivie_d_une_description_garde_la_description_sans_la_sentinelle(candidats, image):
    svc, _ = _service(f"(aucun texte)\n\n{DESCRIPTION}")
    sortie = await svc._ocr_fallback_sans_usage(image, "png")
    assert sortie == DESCRIPTION
    assert "aucun texte" not in sortie.lower()


@pytest.mark.asyncio
async def test_sentinelle_repetee_puis_description(candidats, image):
    svc, _ = _service(f"(aucun texte) (aucun texte) {DESCRIPTION}")
    assert await svc._ocr_fallback_sans_usage(image, "png") == DESCRIPTION


@pytest.mark.asyncio
async def test_le_texte_transcrit_garde_sa_mise_en_page(candidats, image):
    texte = "Ligne 1\n\nLigne   2 (aucun texte à droite)"
    svc, _ = _service(texte)
    assert await svc._ocr_fallback_sans_usage(image, "png") == texte     # seule la forme « (aucun texte) » est retirée


@pytest.mark.asyncio
async def test_erreur_bascule_sur_le_modele_suivant(candidats, image):
    candidats["modeles"] = ["modele-a", "modele-b"]
    svc, generate = _service(RuntimeError("boum"), DESCRIPTION)
    assert await svc._ocr_fallback_sans_usage(image, "png") == DESCRIPTION
    assert [c.kwargs["model"] for c in generate.await_args_list] == ["modele-a", "modele-b"]


@pytest.mark.asyncio
async def test_tous_les_modeles_en_erreur_rend_vide_sans_exception(candidats, image):
    candidats["modeles"] = ["modele-a", "modele-b"]
    svc, generate = _service(RuntimeError("boum"), TimeoutError("lent"))
    assert await svc._ocr_fallback_sans_usage(image, "png") == ""
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_fichier_illisible_ne_leve_pas(candidats, tmp_path):
    svc, generate = _service(DESCRIPTION)
    assert await svc._ocr_fallback_sans_usage(tmp_path / "absent.png", "png") == ""
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_extension_non_geree_rend_vide_sans_appel(candidats, tmp_path):
    svc, generate = _service(DESCRIPTION)
    assert await svc._ocr_fallback_sans_usage(tmp_path / "x.docx", "docx") == ""
    generate.assert_not_awaited()


# ─── PDF ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_image_de_dix_pages_dix_appels_au_plus(candidats, pdf_de):
    svc, generate = _service(**{"return_value": DESCRIPTION})
    sortie = await svc._ocr_fallback_sans_usage(pdf_de(10), "pdf")
    assert generate.await_count == 10
    assert sortie == "\n\n".join([DESCRIPTION] * 10)


@pytest.mark.asyncio
async def test_pdf_de_trente_pages_reste_plafonne(candidats, pdf_de):
    svc, generate = _service(**{"return_value": "texte de page"})
    await svc._ocr_fallback_sans_usage(pdf_de(30), "pdf")
    assert generate.await_count == extraction._OCR_MAX_PAGES == 10


@pytest.mark.asyncio
async def test_pdf_pages_jointes_par_deux_sauts_de_ligne_pages_vides_ignorees(candidats, pdf_de):
    svc, generate = _service("Texte page 1", "(aucun texte)", "Texte page 3")
    assert await svc._ocr_fallback_sans_usage(pdf_de(3), "pdf") == "Texte page 1\n\nTexte page 3"
    assert generate.await_count == 3


@pytest.mark.asyncio
async def test_pdf_sans_rien_d_exploitable_rend_vide_sans_seconde_passe(candidats, pdf_de):
    svc, generate = _service(**{"return_value": "(aucun texte)"})
    assert await svc._ocr_fallback_sans_usage(pdf_de(4), "pdf") == ""
    assert generate.await_count == 4                      # une seule passe, pas 8


@pytest.mark.asyncio
async def test_pdf_erreur_a_mi_parcours_bascule_sur_le_modele_suivant_pour_tout_le_document(candidats, pdf_de):
    candidats["modeles"] = ["modele-a", "modele-b"]
    svc, generate = _service("page 1 a", RuntimeError("boum"), "page 1 b", "page 2 b")
    assert await svc._ocr_fallback_sans_usage(pdf_de(2), "pdf") == "page 1 b\n\npage 2 b"
    assert [c.kwargs["model"] for c in generate.await_args_list] == ["modele-a", "modele-a", "modele-b", "modele-b"]


@pytest.mark.asyncio
async def test_pdf_sans_page_rend_vide(candidats, pdf_de):
    svc, generate = _service(DESCRIPTION)
    assert await svc._ocr_fallback_sans_usage(pdf_de(0), "pdf") == ""
    generate.assert_not_awaited()


# ─── réponse vide partout : un second avis, un seul ─────────────────────────────────────

@pytest.mark.asyncio
async def test_modele_qui_repond_vide_partout_un_autre_modele_rattrape(candidats, pdf_de):
    """Un modèle mal choisi (non-vision) ne doit pas laisser tous les scans sans texte."""
    candidats["modeles"] = ["modele-a", "modele-b"]
    svc, generate = _service("", "(aucun texte)", "Page 1 lue", "Page 2 lue")
    assert await svc._ocr_fallback_sans_usage(pdf_de(2), "pdf") == "Page 1 lue\n\nPage 2 lue"
    assert [a.kwargs["model"] for a in generate.await_args_list] == ["modele-a"] * 2 + ["modele-b"] * 2


@pytest.mark.asyncio
async def test_document_vraiment_vide_deux_modeles_interroges_au_plus(candidats, image):
    """Trois modèles installés, document vide : on n'en charge pas un troisième pour rien."""
    candidats["modeles"] = ["modele-a", "modele-b", "modele-c"]
    svc, generate = _service(return_value="")
    assert await svc._ocr_fallback_sans_usage(image, "png") == ""
    assert [a.kwargs["model"] for a in generate.await_args_list] == ["modele-a", "modele-b"]


@pytest.mark.asyncio
async def test_une_page_lue_suffit_pas_de_second_modele(candidats, pdf_de):
    candidats["modeles"] = ["modele-a", "modele-b"]
    svc, generate = _service("", "Page 2 lue")
    assert await svc._ocr_fallback_sans_usage(pdf_de(2), "pdf") == "Page 2 lue"
    assert generate.await_count == 2
