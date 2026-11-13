package main

import (
	"compress/gzip"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
)

func contenu(n int) []byte {
	b := make([]byte, n)
	for i := range b {
		b[i] = byte((i * 7) % 251)
	}
	return b
}

func ecrire(t *testing.T, chemin string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(chemin), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(chemin, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

// Valeurs calculées par app/inventaire/doublons.py (le serveur) sur les mêmes contenus.
var references = []struct {
	taille            int
	partielle, totale string
}{
	{0, "af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
	{1000, "46b0061ec1266834e5eab06f047aab603e8c118dce008179c2713f63ec5e78e2", "59425e4412e296fc74736673ce067027f384203f59c0d2c3e6be7b13347b3ffc"},
	{65536, "5c012fabe1f91c71bb1b23ad9690968033b08a5b42dfbf70e6278d78a1e05155", "de3f3404598736bd6abece44ed40b347febf99becf1a476f0d18fdc9a32a6166"},
	{100000, "6fd8d5bea38edece3333ae3ce3646aaac8928696aaa392113116fd608a31caa3", "96ad0ddabe9c733d4550fde750255a94806811029be67504bd9bd68e556686b9"},
	{131072, "4f06b12307de900f84d625c054277211d9a928a09b29a41265e51f8814a0adf7", "02170ec6855258d12448d7937b2faca08544235dba8416054daf149cc32b95c1"},
	{131073, "780b381f06a7dda15aa7e4c457811b9cc3511a4c5ace08db7fd572d94f062854", "886bb63e0b86b13e8bd3128b8ba98f373ba91f4cff9f0d823cec92c8642fe239"},
	{300000, "1bab3b4a5c6b32d2ce64f4eaa40a4e03176d4918198521514629613bbc2343fd", "b1cf7538cf80d01efe3e0b8e45dc930048a138c7b6f8c4aff08f478e4695e631"},
}

func TestEmpreintesIdentiquesAuServeur(t *testing.T) {
	dir := t.TempDir()
	for _, ref := range references {
		chemin := filepath.Join(dir, "f")
		ecrire(t, chemin, contenu(ref.taille))
		f, _ := os.Open(chemin)
		p, c, lus, err := empreintePartielle(f, int64(ref.taille))
		f.Close()
		if err != nil || hex.EncodeToString(p) != ref.partielle {
			t.Fatalf("partielle %d : %x (%v)", ref.taille, p, err)
		}
		if ref.taille <= 2*bloc {
			if hex.EncodeToString(c) != ref.totale || lus != int64(ref.taille) {
				t.Fatalf("petit fichier %d : la complète doit être offerte", ref.taille)
			}
		} else if c != nil || lus != 2*bloc {
			t.Fatalf("partielle %d : %d octets lus", ref.taille, lus)
		}
		f, _ = os.Open(chemin)
		p2, c2, lus2, err := empreinteComplete(f, int64(ref.taille))
		f.Close()
		if err != nil || hex.EncodeToString(c2) != ref.totale || hex.EncodeToString(p2) != ref.partielle ||
			lus2 != int64(ref.taille) {
			t.Fatalf("complète %d : %x / %x (%v)", ref.taille, c2, p2, err)
		}
	}
}

func TestFichierChangeNonLu(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "f")
	ecrire(t, chemin, contenu(1000))
	info, _ := os.Stat(chemin)
	d := demande{ID: 1, Taille: 1000, Mtime: secondes(info.ModTime()) + 5, Nature: "partielle"}
	base := filepath.Dir(chemin)
	if _, err := calculer(base, chemin, d); err != errChange {
		t.Fatalf("date différente : %v", err)
	}
	d.Mtime, d.Taille = secondes(info.ModTime()), 999
	if _, err := calculer(base, chemin, d); err != errChange {
		t.Fatalf("taille différente : %v", err)
	}
	d.Taille = 1000
	if r, err := calculer(base, chemin, d); err != nil || r.Complete == nil {
		t.Fatalf("fichier conforme : %v", err)
	}
}

func TestRacinesAutorisees(t *testing.T) {
	base := t.TempDir()
	c := &Config{ServeurURL: "http://x", Jeton: "mato_x", RacinesAutorisees: []string{filepath.Join(base, "Users")}}
	if err := c.valider(); err != nil {
		t.Fatal(err)
	}
	cas := map[string]bool{
		filepath.Join(base, "Users"):                     true,
		filepath.Join(base, "Users", "Thomas"):           true,
		filepath.Join(base, "UsersX"):                    false,
		filepath.Join(base, "Windows"):                   false,
		base + string(filepath.Separator) + "Users/../W": false,
		"relatif": false,
	}
	for chemin, attendu := range cas {
		if c.autorisee(chemin) != attendu {
			t.Errorf("autorisee(%q) != %v", chemin, attendu)
		}
	}
}

func TestConfigInvalide(t *testing.T) {
	racine := t.TempDir()
	for _, c := range []Config{
		{ServeurURL: "ftp://x", Jeton: "mato_x", RacinesAutorisees: []string{racine}},
		{ServeurURL: "http://x", Jeton: "autre", RacinesAutorisees: []string{racine}},
		{ServeurURL: "http://x", Jeton: "mato_x"},
		{ServeurURL: "http://x", Jeton: "mato_x", RacinesAutorisees: []string{"relatif"}},
	} {
		c := c
		if c.valider() == nil {
			t.Errorf("config acceptée à tort : %+v", c)
		}
	}
}

func TestConfigAvecBOMRefuseeClairement(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "agent.json")
	ecrire(t, chemin, []byte("\xef\xbb\xbf{}"))
	if _, err := chargerConfig(chemin); err == nil {
		t.Fatal("un BOM doit être signalé (l'installeur écrit sans BOM)")
	}
}

func TestExclusionsSousEnsembleDuServeur(t *testing.T) {
	e := nouvellesExclusions([]string{"@eaDir", "#recycle"}, []string{"*.tmp"})
	cas := []struct {
		nom, rel string
		prof     int
		dossier  bool
		exclu    bool
	}{
		{"@EADIR", "a/@EADIR", 1, true, true},    // nom verrouillé : sans casse
		{"@docker", "@docker", 0, true, true},    // « @… » à la racine
		{"@docker", "a/@docker", 1, true, false}, // plus bas : un nom comme un autre
		{"x.tmp", "a/x.tmp", 1, false, true},
		{"x.TMP", "a/x.TMP", 1, false, false}, // motif : avec casse, comme le serveur
		{"photo.jpg", "photo.jpg", 0, false, false},
	}
	for _, c := range cas {
		if e.exclut(c.nom, c.rel, c.prof, c.dossier) != c.exclu {
			t.Errorf("exclut(%q) != %v", c.rel, c.exclu)
		}
	}
}

func TestParcoursEtLots(t *testing.T) {
	racine := t.TempDir()
	ecrire(t, filepath.Join(racine, "Docs", "a.pdf"), contenu(10))
	ecrire(t, filepath.Join(racine, "Docs", "@eaDir", "vignette"), contenu(1))
	ecrire(t, filepath.Join(racine, "@systeme", "x"), contenu(1))
	ecrire(t, filepath.Join(racine, "b.txt"), contenu(20))
	if err := os.Symlink(filepath.Join(racine, "Docs"), filepath.Join(racine, "lien")); err != nil {
		t.Log("liens symboliques indisponibles : vérification sautée")
	}
	var recus []dossierEnvoye
	envois := 0
	iv := &inventoriste{racine: racine, excl: nouvellesExclusions([]string{"@eaDir"}, nil), lotMax: 1,
		envoyer: func(l []dossierEnvoye) error { envois++; recus = append(recus, l...); return nil }}
	if err := iv.parcourir(); err != nil {
		t.Fatal(err)
	}
	noms := map[string][]string{}
	for _, d := range recus {
		noms[d.Chemin] = []string{}
		for _, e := range d.Enfants {
			noms[d.Chemin] = append(noms[d.Chemin], e[0].(string))
		}
		sort.Strings(noms[d.Chemin])
	}
	if strings.Join(noms[""], ",") != "Docs,b.txt" {
		t.Fatalf("racine : %v (liens, @… et @eaDir exclus)", noms[""])
	}
	if strings.Join(noms["Docs"], ",") != "a.pdf" {
		t.Fatalf("Docs : %v", noms["Docs"])
	}
	if iv.fichiers != 2 || iv.dossiers != 2 || envois != 2 || len(noms) != 2 {
		t.Fatalf("compteurs : %d fichiers, %d dossiers, %d envois, %v", iv.fichiers, iv.dossiers, envois, noms)
	}
}

func TestDossierIllisibleSignale(t *testing.T) {
	var recus []dossierEnvoye
	iv := &inventoriste{racine: filepath.Join(t.TempDir(), "absent"),
		envoyer: func(l []dossierEnvoye) error { recus = append(recus, l...); return nil }}
	if err := iv.parcourir(); err != nil {
		t.Fatal(err)
	}
	if len(recus) != 1 || !recus[0].Illisible {
		t.Fatalf("un dossier illisible doit être signalé, pas envoyé vide : %+v", recus)
	}
}

func TestGrandDossierEnMorceaux(t *testing.T) {
	var lots [][]dossierEnvoye
	iv := &inventoriste{lotMax: lotMaxServeur, envoyer: func(l []dossierEnvoye) error {
		lots = append(lots, l)
		return nil
	}}
	ds := dossierEnvoye{Chemin: "gros", Illisibles: []string{"x"}}
	for i := 0; i < 45000; i++ {
		ds.Enfants = append(ds.Enfants, element{"f", false, int64(1), 0.0})
	}
	if err := iv.ajouter(ds); err != nil {
		t.Fatal(err)
	}
	if err := iv.vider(); err != nil {
		t.Fatal(err)
	}
	total, morceaux := 0, 0
	for _, l := range lots {
		n := 0
		for _, d := range l {
			n += len(d.Enfants)
			morceaux++
			if d.Chemin != "gros" || len(d.Enfants) > enfantsMaxParMorceau {
				t.Fatalf("morceau incorrect : %s, %d", d.Chemin, len(d.Enfants))
			}
		}
		if n > enfantsMaxParLot {
			t.Fatalf("lot trop gros : %d", n)
		}
		total += n
	}
	if total != 45000 || morceaux != 3 {
		t.Fatalf("%d éléments en %d morceaux", total, morceaux)
	}
}

// fauxServeur : rejoue le protocole de /api/agent/* et garde ce qu'il reçoit.
type fauxServeur struct {
	mu        sync.Mutex
	racine    string
	dossiers  []dossierEnvoye
	resultats []resultat
	fini      bool
	demandes  []demande
	echecs    int
}

func (s *fauxServeur) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if r.Header.Get("Authorization") != "Bearer mato_test" || r.Header.Get("X-Agent-Version") == "" {
		w.WriteHeader(401)
		return
	}
	if s.echecs > 0 {
		s.echecs--
		w.WriteHeader(503)
		return
	}
	switch {
	case r.Method == "GET" && r.URL.Path == "/api/agent/config":
		json.NewEncoder(w).Encode(map[string]any{"version_protocole": 1, "intervalle_min": 7, "lot_max_dossiers": 10,
			"racines":         []map[string]any{{"emplacement_id": 3, "racine": s.racine, "inventaire_du": true}},
			"exclusions_noms": []string{"@eaDir"}, "exclusions_motifs": []string{}})
	case r.Method == "POST" && r.URL.Path == "/api/agent/envois":
		w.WriteHeader(201)
		io.WriteString(w, `{"envoi_id": 12}`)
	case r.Method == "POST" && r.URL.Path == "/api/agent/envois/12/lots":
		if r.Header.Get("Content-Encoding") != "gzip" {
			w.WriteHeader(415)
			return
		}
		gz, err := gzip.NewReader(r.Body)
		if err != nil {
			w.WriteHeader(422)
			return
		}
		var lot struct {
			Dossiers []dossierEnvoye `json:"dossiers"`
		}
		json.NewDecoder(gz).Decode(&lot)
		s.dossiers = append(s.dossiers, lot.Dossiers...)
		io.WriteString(w, `{"recus": 1}`)
	case r.Method == "POST" && r.URL.Path == "/api/agent/envois/12/fin":
		s.fini = true
		w.WriteHeader(202)
		io.WriteString(w, `{"scan_id": 1}`)
	case r.Method == "GET" && r.URL.Path == "/api/agent/empreintes":
		d := s.demandes
		s.demandes = nil
		if d == nil {
			d = []demande{}
		}
		json.NewEncoder(w).Encode(map[string]any{"demandes": d})
	case r.Method == "POST" && r.URL.Path == "/api/agent/empreintes":
		var corps struct {
			Resultats []resultat `json:"resultats"`
		}
		json.NewDecoder(r.Body).Decode(&corps)
		s.resultats = append(s.resultats, corps.Resultats...)
		io.WriteString(w, `{"retenus": 1}`)
	default:
		w.WriteHeader(404)
	}
}

func TestProtocoleComplet(t *testing.T) {
	racine := t.TempDir()
	chemin := filepath.Join(racine, "Videos", "film.mp4")
	ecrire(t, chemin, contenu(300000))
	info, _ := os.Stat(chemin)
	s := &fauxServeur{racine: racine, demandes: []demande{
		{ID: 9, EmplacementID: 3, Chemin: "Videos/film.mp4", Taille: 300000, Mtime: secondes(info.ModTime()), Nature: "complete"},
		{ID: 10, EmplacementID: 3, Chemin: "../hors.txt", Taille: 1, Mtime: 0, Nature: "partielle"},
		{ID: 11, EmplacementID: 99, Chemin: "Videos/film.mp4", Taille: 300000, Mtime: 0, Nature: "partielle"},
	}}
	srv := httptest.NewServer(s)
	defer srv.Close()
	cfg := &Config{ServeurURL: srv.URL, Jeton: "mato_test", RacinesAutorisees: []string{racine}}
	cl := nouveauClient(cfg)
	cl.attente = func(time.Duration) {}
	if n := cycle(cl, cfg, nil); n != 7 {
		t.Fatalf("intervalle rendu : %d", n)
	}
	if !s.fini || len(s.dossiers) != 2 {
		t.Fatalf("envoi : fini=%v, %d dossiers", s.fini, len(s.dossiers))
	}
	if len(s.resultats) != 1 || s.resultats[0].ID != 9 || s.resultats[0].Complete == nil ||
		*s.resultats[0].Complete != references[6].totale || s.resultats[0].Partielle != references[6].partielle {
		t.Fatalf("empreintes : %+v", s.resultats)
	}
}

func TestDossierHorsListeBlancheJamaisInventorie(t *testing.T) {
	autorise, interdit := t.TempDir(), t.TempDir()
	s := &fauxServeur{racine: interdit}
	srv := httptest.NewServer(s)
	defer srv.Close()
	cfg := &Config{ServeurURL: srv.URL, Jeton: "mato_test", RacinesAutorisees: []string{autorise}}
	cycle(nouveauClient(cfg), cfg, nil)
	if s.fini || len(s.dossiers) != 0 {
		t.Fatal("un dossier hors de la liste blanche locale a été inventorié")
	}
}

func TestNouvellesTentativesSurErreurServeur(t *testing.T) {
	s := &fauxServeur{racine: t.TempDir(), echecs: 2}
	srv := httptest.NewServer(s)
	defer srv.Close()
	cfg := &Config{ServeurURL: srv.URL, Jeton: "mato_test", RacinesAutorisees: []string{s.racine}}
	cl := nouveauClient(cfg)
	attentes := 0
	cl.attente = func(time.Duration) { attentes++ }
	var cs configServeur
	if err := cl.obtenir("/api/agent/config", &cs); err != nil || attentes != 2 {
		t.Fatalf("après deux 503 : %v (%d attentes)", err, attentes)
	}
	cl.jeton = "mato_faux"
	attentes = 0
	if err := cl.obtenir("/api/agent/config", &cs); err == nil || attentes != 0 {
		t.Fatalf("un 401 ne doit pas être répété : %v (%d attentes)", err, attentes)
	}
}

func TestIdentiteAligneeAvecLInstalleur(t *testing.T) {
	for _, script := range []string{"installer-agent.ps1", "desinstaller-agent.ps1"} {
		data, err := os.ReadFile(script)
		if err != nil {
			t.Fatal(err)
		}
		s := string(data)
		if !strings.Contains(s, `"`+nomService+`"`) || !strings.Contains(s, `"`+dossierDonnees+`"`) {
			t.Errorf("%s ne reprend pas l'identité de identite.go (%s, %s)", script, nomService, dossierDonnees)
		}
	}
}

func TestLienIntermediaireJamaisSuivi(t *testing.T) {
	dir := t.TempDir()
	confie, ailleurs := filepath.Join(dir, "confie"), filepath.Join(dir, "ailleurs")
	ecrire(t, filepath.Join(ailleurs, "secret.bin"), contenu(1000))
	if err := os.MkdirAll(confie, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(ailleurs, filepath.Join(confie, "lien")); err != nil {
		t.Skip("liens symboliques indisponibles sur ce poste")
	}
	chemin := filepath.Join(confie, "lien", "secret.bin")
	info, _ := os.Stat(chemin)
	d := demande{ID: 1, Taille: 1000, Mtime: secondes(info.ModTime()), Nature: "partielle"}
	if _, err := calculer(confie, chemin, d); err != errHorsRacine {
		t.Fatalf("un dossier intermédiaire lien doit être refusé : %v", err)
	}
	cfg := &Config{ServeurURL: "http://x", Jeton: "mato_x", RacinesAutorisees: []string{confie}}
	if cfg.racineSure(filepath.Join(confie, "lien")) {
		t.Fatal("une racine qui est un lien doit être refusée")
	}
	if !cfg.racineSure(confie) {
		t.Fatal("la racine confiée elle-même doit être acceptée")
	}
}
