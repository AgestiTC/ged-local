// empreintes.go — empreintes SHA-256 demandées par le serveur (copies multiples).
//
// ⚠️ MÊME ALGORITHME que le serveur (app/inventaire/doublons.py), octet pour octet :
//   - partielle = SHA-256( taille sur 8 octets gros-boutiste + 64 premiers Ko + 64 derniers Ko ),
//     ou du fichier entier s'il fait au plus 128 Ko (la complète est alors offerte) ;
//   - complète  = SHA-256 du fichier entier.
//
// TestEmpreintesIdentiquesAuServeur compare aux valeurs calculées par le Python.
//
// Ne lit JAMAIS : un fichier hors des racines autorisées, un lien, un fichier dont la
// taille ou la date ne correspond plus à la demande, ni un fichier « à la demande » de
// OneDrive (le lire le téléchargerait).
package main

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"log"
	"math"
	"os"
	"path/filepath"
	"time"
)

const (
	bloc             = 64 * 1024
	toleranceMtime   = 0.001
	toursMaxParCycle = 20
)

var errChange = errors.New("fichier changé depuis l'inventaire")

type demande struct {
	ID            int64   `json:"id"`
	EmplacementID int     `json:"emplacement_id"`
	Chemin        string  `json:"chemin"`
	Taille        int64   `json:"taille"`
	Mtime         float64 `json:"mtime"`
	Nature        string  `json:"nature"`
}

type resultat struct {
	ID        int64   `json:"id"`
	Taille    int64   `json:"taille"`
	Mtime     float64 `json:"mtime"`
	Partielle string  `json:"partielle"`
	Complete  *string `json:"complete"`
	OctetsLus int64   `json:"octets_lus"`
}

func sommeTaille(taille int64, morceaux ...[]byte) []byte {
	h := sha256.New()
	var t [8]byte
	binary.BigEndian.PutUint64(t[:], uint64(taille))
	h.Write(t[:])
	for _, m := range morceaux {
		h.Write(m)
	}
	return h.Sum(nil)
}

// empreintePartielle : (partielle, complète si le fichier a été lu en entier, octets lus).
func empreintePartielle(f *os.File, taille int64) ([]byte, []byte, int64, error) {
	tete := make([]byte, min(int64(bloc), taille))
	if _, err := io.ReadFull(f, tete); err != nil {
		return nil, nil, 0, err
	}
	if taille > 2*bloc {
		queue := make([]byte, bloc)
		if _, err := f.ReadAt(queue, taille-bloc); err != nil {
			return nil, nil, 0, err
		}
		return sommeTaille(taille, tete, queue), nil, int64(len(tete) + len(queue)), nil
	}
	reste, err := io.ReadAll(f)
	if err != nil {
		return nil, nil, 0, err
	}
	tout := append(tete, reste...)
	c := sha256.Sum256(tout)
	return sommeTaille(taille, tout), c[:], int64(len(tout)), nil
}

// empreinteComplete : une seule lecture du fichier donne la complète ET la partielle.
func empreinteComplete(f *os.File, taille int64) ([]byte, []byte, int64, error) {
	hc := sha256.New()
	tete := make([]byte, 0, bloc)
	queue := make([]byte, 0, 2*bloc+(1<<20))
	tampon := make([]byte, 1<<20)
	var lus int64
	for {
		n, err := f.Read(tampon)
		if n > 0 {
			m := tampon[:n]
			hc.Write(m)
			if len(tete) < bloc {
				tete = append(tete, m[:min(len(m), bloc-len(tete))]...)
			}
			queue = append(queue, m...)
			if len(queue) > bloc {
				queue = append(queue[:0], queue[len(queue)-bloc:]...)
			}
			lus += int64(n)
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, nil, lus, err
		}
	}
	if lus != taille {
		return nil, nil, lus, errChange
	}
	if taille <= 2*bloc { // petit fichier : sa partielle couvre tout son contenu
		if _, err := f.Seek(0, io.SeekStart); err != nil {
			return nil, nil, lus, err
		}
		p, c, _, err := empreintePartielle(f, taille)
		return p, c, lus, err
	}
	return sommeTaille(taille, tete, queue), hc.Sum(nil), lus, nil
}

// concorde : le fichier est-il celui que l'inventaire connaît (type, taille, date) ?
func concorde(info os.FileInfo, d demande) bool {
	return info.Mode().IsRegular() && info.Size() == d.Taille &&
		math.Abs(secondes(info.ModTime())-d.Mtime) <= toleranceMtime
}

var errHorsRacine = errors.New("chemin réel hors de la racine confiée")

func calculer(base, chemin string, d demande) (*resultat, error) {
	info, err := os.Lstat(chemin)
	if err != nil {
		return nil, err
	}
	if !concorde(info, d) {
		return nil, errChange
	}
	if !reelSous(base, chemin) {
		return nil, errHorsRacine // un dossier intermédiaire est un lien ou une jonction
	}
	if aLaDemande(info) {
		return nil, errors.New("fichier « à la demande » (OneDrive…) : non lu")
	}
	f, err := os.Open(chemin)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	// Le fichier ouvert est-il bien celui qu'on vient d'inspecter ? (remplacé entre-temps)
	ouvert, err := f.Stat()
	if err != nil || !os.SameFile(info, ouvert) {
		return nil, errChange
	}
	var p, c []byte
	var lus int64
	if d.Nature == "complete" {
		p, c, lus, err = empreinteComplete(f, d.Taille)
	} else {
		p, c, lus, err = empreintePartielle(f, d.Taille)
	}
	if err != nil {
		return nil, err
	}
	apres, err := f.Stat()
	if err != nil || !concorde(apres, d) {
		return nil, errChange // modifié pendant la lecture : l'empreinte ne vaut rien
	}
	r := &resultat{ID: d.ID, Taille: info.Size(), Mtime: secondes(info.ModTime()),
		Partielle: hex.EncodeToString(p), OctetsLus: lus}
	if c != nil {
		s := hex.EncodeToString(c)
		r.Complete = &s
	}
	return r, nil
}

// calculerEmpreintes : demande, calcule, renvoie — jusqu'à ce que le serveur n'ait plus
// rien à demander (ou que sa limite du jour soit atteinte).
func calculerEmpreintes(cl *Client, cfg *Config, racines map[int]string, arret <-chan struct{}) {
	for tour := 0; tour < toursMaxParCycle; tour++ {
		var rep struct {
			Demandes []demande `json:"demandes"`
		}
		if err := cl.obtenir("/api/agent/empreintes", &rep); err != nil {
			log.Printf("Demandes d'empreintes indisponibles : %v", err)
			return
		}
		if len(rep.Demandes) == 0 {
			return
		}
		debut := time.Now()
		resultats := []resultat{}
		var lus int64
		for _, d := range rep.Demandes {
			if arreteDemande(arret) {
				break
			}
			base, ok := racines[d.EmplacementID]
			if !ok || !cfg.racineSure(base) || d.Chemin == "" {
				continue
			}
			chemin := filepath.Join(base, filepath.FromSlash(d.Chemin))
			if !sousDossier(base, chemin) {
				continue
			}
			r, err := calculer(base, chemin, d)
			if err != nil {
				continue // changé, disparu, illisible : le prochain inventaire tranchera
			}
			lus += r.OctetsLus
			resultats = append(resultats, *r)
		}
		if len(resultats) == 0 {
			return // rien de lisible dans ce tour : inutile d'insister
		}
		var ret struct {
			Retenus int `json:"retenus"`
		}
		if err := cl.poster("/api/agent/empreintes", map[string]any{"resultats": resultats}, false, &ret); err != nil {
			log.Printf("Envoi des empreintes impossible : %v", err)
			return
		}
		log.Printf("Empreintes : %d calculées (%d retenues), %.1f Mo lus en %s", len(resultats), ret.Retenus,
			float64(lus)/(1<<20), time.Since(debut).Round(time.Second))
		if arreteDemande(arret) {
			return
		}
	}
}
