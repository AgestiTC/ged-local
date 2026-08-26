"""
Tests de la concurrence PAR CLASSE du worker de jobs
=====================================================
`classe_tache` route chaque type vers un budget de slots ('gpu' = Ollama, 'io' = réseau/disque).
Objectif : une rafale de tâches GPU (enrichissement) ne doit jamais priver les tâches I/O
(synchro NAS, réorganisation) de leurs slots — elles tournent EN MÊME TEMPS.
"""
from services import job_worker as jw


class TestClasseTache:
    def test_types_gpu(self):
        # Tout ce qui sollicite Ollama (LLM / vision / embeddings) → budget GPU (VRAM limitée).
        for t in ("enrich", "analyze", "presentation", "fill_template",
                  "analyse_regroupement", "indexation", "index_wiki", "index_connector"):
            assert jw.classe_tache(t) == "gpu", t

    def test_types_io(self):
        # Réseau / disque : tournent librement à côté du GPU.
        for t in ("sync_source", "reorg_apply", "reorg_undo", "demo"):
            assert jw.classe_tache(t) == "io", t

    def test_type_inconnu_est_io_par_defaut(self):
        # Défaut sûr : un handler oublié ne monopolise jamais le budget GPU.
        assert jw.classe_tache("type_jamais_vu") == "io"

    def test_budgets_par_classe_coherents(self):
        assert jw.CONCURRENCE_PAR_CLASSE == {"gpu": jw.CONCURRENCE_GPU, "io": jw.CONCURRENCE_IO}
        assert jw.CONCURRENCE_GPU >= 1 and jw.CONCURRENCE_IO >= 1
        # Capacité totale = somme des budgets (rétro-compat du log de démarrage).
        assert jw.CONCURRENCE == jw.CONCURRENCE_GPU + jw.CONCURRENCE_IO

    def test_tous_les_handlers_enregistres_sont_classes(self):
        # Chaque handler réellement enregistré tombe dans 'gpu' ou 'io' (jamais autre chose).
        for t in jw._HANDLERS:
            assert jw.classe_tache(t) in ("gpu", "io"), t


class TestBudget:
    def test_budget_defaut(self):
        # Sans surcharge de config → défauts (2 GPU / 3 I/O).
        assert jw._budget("gpu") == jw.CONCURRENCE_GPU
        assert jw._budget("io") == jw.CONCURRENCE_IO

    def test_budget_lit_la_config(self, monkeypatch):
        # Surcharge runtime → le budget suit (réglable à chaud dans les Paramètres).
        from services import runtime_config
        monkeypatch.setitem(runtime_config._overrides, "concurrence_gpu", "1")
        monkeypatch.setitem(runtime_config._overrides, "concurrence_io", "5")
        assert jw._budget("gpu") == 1
        assert jw._budget("io") == 5

    def test_budget_borne_et_valeur_invalide(self, monkeypatch):
        from services import runtime_config
        # Au-delà du max → borné ; valeur non numérique → défaut ; 0 → min 1 (jamais de file gelée).
        monkeypatch.setitem(runtime_config._overrides, "concurrence_gpu", "999")
        assert jw._budget("gpu") == jw._BUDGET_MAX
        monkeypatch.setitem(runtime_config._overrides, "concurrence_gpu", "abc")
        assert jw._budget("gpu") == jw.CONCURRENCE_GPU
        monkeypatch.setitem(runtime_config._overrides, "concurrence_io", "0")
        assert jw._budget("io") == jw._BUDGET_MIN
