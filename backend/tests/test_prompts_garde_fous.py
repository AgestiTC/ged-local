"""
Consignes communes = garde-fous (plan prompts + RAG, fin de la piste A — décision de Thomas, 19/11/2026).
==========================================================================================================
Les consignes « JSON seul », « n'invente rien », « en français » ne sont pas factorisées (le texte envoyé
reste celui d'origine) : une version modifiée depuis Paramètres doit les GARDER, sinon elle est refusée.
Textes fictifs uniquement.
"""
import pytest

from services import consignes_reference, prompts


def noms(texte: str) -> set[str]:
    return {g.nom for g in prompts.garde_fous_presents(texte)}


class TestDetection:
    @pytest.mark.parametrize("texte", [
        "Réponds UNIQUEMENT par un objet JSON, sans texte autour.",
        "Retourne uniquement un JSON valide.",
        "Ne retourne que le JSON, rien d'autre.",
        "Ta réponse : un JSON, sans texte avant ni après.",
    ])
    def test_json_strict_reconnu(self, texte):
        assert "json_strict" in noms(texte)

    def test_json_seul_sans_exigence_n_est_pas_un_garde_fou(self):
        assert "json_strict" not in noms("Voici un exemple de JSON utilisé par l'outil.")

    @pytest.mark.parametrize("texte", ["N'invente rien.", "N’INVENTE JAMAIS de date.", "aucune invention",
                                       "Tu n'ajoutes aucune information."])
    def test_ne_rien_inventer_reconnu(self, texte):
        assert "ne_rien_inventer" in noms(texte)

    def test_francais_est_une_consigne_de_langue(self):
        assert "francais" in noms("Réponds en FRANÇAIS.")
        assert "francais" not in noms("Analyse un document RH français.")


class TestRegistre:
    def test_les_prompts_json_portent_le_garde_fou_json(self):
        # Seule exception : la partie « utilisateur » de musique.style, dont la partie système le porte.
        sans = [c for c in prompts.cles() if prompts.prompt(c).sortie == "json"
                and "json_strict" not in {g.nom for g in prompts.garde_fous_de(c)}]
        assert sans == ["musique.style.utilisateur"]
        assert "json_strict" in {g.nom for g in prompts.garde_fous_de("musique.style")}

    def test_chaque_origine_respecte_ses_propres_garde_fous(self):
        for cle in prompts.cles():
            assert prompts.garde_fous_retires(prompts.prompt(cle).texte, prompts.prompt(cle).texte) == [], cle


class TestContrat:
    def test_retirer_la_consigne_json_est_refuse(self):
        origine = prompts.prompt("enrichissement").texte
        candidat = origine.replace("retourne UNIQUEMENT un objet JSON valide", "retourne un objet")
        assert candidat != origine
        erreurs = prompts.verifier_contrat("enrichissement", candidat)
        assert len(erreurs) == 1 and "Réponse en JSON seul" in erreurs[0]

    def test_reformuler_la_consigne_est_accepte(self):
        origine = prompts.prompt("enrichissement").texte
        candidat = origine.replace("retourne UNIQUEMENT un objet JSON valide",
                                   "retourne seulement un JSON valide")
        assert prompts.verifier_contrat("enrichissement", candidat) == []

    def test_retirer_n_invente_rien_et_le_francais(self):
        cle = "modeles.resume_local"
        assert {g.nom for g in prompts.garde_fous_de(cle)} == {"ne_rien_inventer", "francais"}
        erreurs = prompts.verifier_contrat(cle, "Décris en une phrase à quoi sert ce modèle fictif.")
        assert any("Ne rien inventer" in e for e in erreurs)
        assert any("Réponse en français" in e for e in erreurs)

    def test_une_cle_sans_garde_fou_n_impose_rien(self):
        assert prompts.garde_fous_de("comparatif.ecarts") == ()

    def test_les_erreurs_de_forme_restent_en_tete(self):
        # Variable manquante ET consigne retirée : la forme d'abord, la consigne ensuite.
        cle = next(c for c in prompts.cles() if prompts.prompt(c).variables and prompts.garde_fous_de(c))
        erreurs = prompts.verifier_contrat(cle, "Une consigne fictive assez longue, sans rien d'autre.")
        assert "manquante" in erreurs[0]
        assert any(e.startswith("Consigne retirée") for e in erreurs)

    def test_une_version_en_base_qui_retire_un_garde_fou_est_ignoree(self):
        try:
            prompts.appliquer_versions_actives({"enrichissement": (3, "Classe ce document fictif, merci beaucoup.")})
            assert prompts.version_servie("enrichissement") == 0
            assert prompts.texte("enrichissement") == prompts.prompt("enrichissement").texte
            assert "Réponse en JSON seul" in prompts.version_ignoree("enrichissement")[1]
        finally:
            prompts.vider_cache()


class TestConsignesReference:
    def test_n_invente_rien_doit_rester(self):
        origine = consignes_reference.origine("reference_analyse")
        assert consignes_reference.verifier(origine, "reference_analyse") == []
        sans = "\n".join(l for l in origine.splitlines() if "invent" not in l.lower())
        assert sans != origine
        problemes = consignes_reference.verifier(sans, "reference_analyse")
        assert any("Ne rien inventer" in p for p in problemes)
        # Sans clé (ancien appel) : pas de contrôle des consignes communes.
        assert consignes_reference.verifier(sans) == []
