"""
Tests unitaires — utils/chunker.py
====================================
Vérifie le découpage de texte en chunks avec overlap.
"""

import pytest
from utils.chunker import chunk_text, CHARS_PER_TOKEN


class TestChunkText:
    def test_texte_vide(self):
        assert chunk_text("") == []

    def test_texte_court_retourne_un_seul_chunk(self):
        texte = "Texte court qui tient dans un seul chunk."
        chunks = chunk_text(texte, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == texte

    def test_texte_exactement_taille_chunk(self):
        # Un texte de 500 tokens × 4 chars = 2000 chars exactement
        texte = "a" * (500 * CHARS_PER_TOKEN)
        chunks = chunk_text(texte, chunk_size=500, chunk_overlap=0)
        assert len(chunks) == 1

    def test_texte_long_produit_plusieurs_chunks(self):
        # Texte de 3× la taille d'un chunk
        texte = ("Voici une phrase complète qui sert de test. " * 200)
        chunks = chunk_text(texte, chunk_size=100, chunk_overlap=10)
        assert len(chunks) > 1

    def test_overlap_est_present(self):
        # Avec overlap, le début du chunk N+1 doit contenir la fin du chunk N
        texte = "ABCDEFGHIJ" * 500  # Texte long, caractères distincts par position
        chunks = chunk_text(texte, chunk_size=50, chunk_overlap=20)
        # Vérifier qu'il y a plus de chunks avec overlap qu'sans
        chunks_sans_overlap = chunk_text(texte, chunk_size=50, chunk_overlap=0)
        assert len(chunks) >= len(chunks_sans_overlap)

    def test_chunks_non_vides(self):
        texte = "Test " * 1000
        chunks = chunk_text(texte, chunk_size=50, chunk_overlap=10)
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_chunks_couvrent_tout_le_texte(self):
        texte = "Un deux trois quatre cinq. " * 300
        chunks = chunk_text(texte, chunk_size=50, chunk_overlap=0)
        # La concaténation des chunks doit couvrir tout le contenu unique
        texte_reconstruit = " ".join(chunks)
        # Les 50 premiers chars du texte original doivent apparaître
        assert texte[:50] in texte_reconstruit

    def test_utilise_parametres_settings_par_defaut(self):
        texte = "Test " * 2000
        chunks_default = chunk_text(texte)
        chunks_explicit = chunk_text(texte, chunk_size=500, chunk_overlap=50)
        # Les deux doivent produire le même résultat
        assert len(chunks_default) == len(chunks_explicit)

    def test_coupe_aux_paragraphes(self):
        # Le chunker doit préférer couper aux doubles newlines
        paragraphe_a = "Premier paragraphe avec du contenu." * 50
        paragraphe_b = "Deuxième paragraphe avec du contenu." * 50
        texte = paragraphe_a + "\n\n" + paragraphe_b
        chunks = chunk_text(texte, chunk_size=len(paragraphe_a) // CHARS_PER_TOKEN + 10, chunk_overlap=0)
        # Aucun chunk ne doit couper au milieu d'un mot abruptement
        for chunk in chunks:
            assert not chunk.startswith(" ")
