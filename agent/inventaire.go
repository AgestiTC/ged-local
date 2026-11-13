// inventaire.go — parcours d'un dossier du PC et envoi de ses listes, par lots compressés.
//
// Métadonnées seulement (nom, type, taille, date) : aucun octet de contenu n'est lu ici.
// Prudence, comme sur le serveur : un dossier illisible est SIGNALÉ (le serveur n'en marque
// rien disparu), un élément dont on ne peut lire les informations aussi. Les liens et
// jonctions ne sont jamais suivis.
package main

import (
	"errors"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	profondeurMax = 200
	// Au-delà, un dossier est envoyé en plusieurs morceaux (le serveur les rassemble).
	enfantsMaxParMorceau = 20000
	enfantsMaxParLot     = 50000
	lotMaxServeur        = 2000
)

var errArret = errors.New("arrêt demandé")

// element : [nom, est_dossier, taille, date (secondes, avec décimales)].
type element [4]any

type dossierEnvoye struct {
	Chemin     string    `json:"chemin"`
	Illisible  bool      `json:"illisible,omitempty"`
	Enfants    []element `json:"enfants"`
	Illisibles []string  `json:"illisibles,omitempty"`
}

// exclusions : un SOUS-ensemble de celles du serveur (qui refiltre tout). Élaguer plus que
// lui ferait passer pour disparus des fichiers qu'il aurait gardés.
type exclusions struct {
	noms   map[string]bool // sans casse : noms système verrouillés
	motifs []string        // avec casse, comme fnmatchcase côté serveur
}

func nouvellesExclusions(noms, motifs []string) exclusions {
	e := exclusions{noms: map[string]bool{}, motifs: motifs}
	for _, n := range noms {
		e.noms[strings.ToLower(n)] = true
	}
	return e
}

func (e exclusions) exclut(nom, relatif string, profondeur int, dossier bool) bool {
	if e.noms[strings.ToLower(nom)] {
		return true
	}
	if dossier && profondeur == 0 && strings.HasPrefix(nom, "@") {
		return true
	}
	for _, m := range e.motifs {
		if ok, _ := path.Match(m, nom); ok {
			return true
		}
		if ok, _ := path.Match(m, relatif); ok {
			return true
		}
	}
	return false
}

func joindre(parent, nom string) string {
	if parent == "" {
		return nom
	}
	return parent + "/" + nom
}

func secondes(t time.Time) float64 { return float64(t.UnixNano()) / 1e9 }

// inventoriste : parcours en profondeur avec une pile (mémoire bornée), envoi au fil de l'eau.
type inventoriste struct {
	racine   string
	excl     exclusions
	lotMax   int
	envoyer  func([]dossierEnvoye) error
	lot      []dossierEnvoye
	nbLot    int
	dossiers int
	fichiers int
	erreurs  int
	arret    <-chan struct{}
}

type aVisiter struct {
	relatif    string
	profondeur int
}

func (iv *inventoriste) parcourir() error {
	if iv.lotMax <= 0 || iv.lotMax > lotMaxServeur {
		iv.lotMax = lotMaxServeur
	}
	pile := []aVisiter{{"", 0}}
	for len(pile) > 0 {
		if arreteDemande(iv.arret) {
			return errArret
		}
		d := pile[len(pile)-1]
		pile = pile[:len(pile)-1]
		absolu := iv.racine
		if d.relatif != "" {
			absolu = filepath.Join(iv.racine, filepath.FromSlash(d.relatif))
		}
		ds := dossierEnvoye{Chemin: d.relatif, Enfants: []element{}}
		entrees, err := os.ReadDir(absolu)
		if err != nil {
			// Illisible, ou lecture interrompue : signalé, jamais pris pour un dossier vide.
			iv.erreurs++
			ds.Illisible = true
			if err := iv.ajouter(ds); err != nil {
				return err
			}
			continue
		}
		iv.dossiers++
		for _, e := range entrees {
			nom := e.Name()
			if !utf8.ValidString(nom) || strings.ContainsAny(nom, "/\x00") {
				iv.erreurs++ // nom qu'aucune base ne saurait garder tel quel
				continue
			}
			if e.Type()&(fs.ModeSymlink|fs.ModeIrregular|fs.ModeDevice|fs.ModeNamedPipe|fs.ModeSocket) != 0 {
				continue // lien, jonction, périphérique : jamais suivis
			}
			estDossier := e.IsDir()
			relatif := joindre(d.relatif, nom)
			if iv.excl.exclut(nom, relatif, d.profondeur, estDossier) {
				continue
			}
			info, err := e.Info()
			if err != nil {
				iv.erreurs++
				ds.Illisibles = append(ds.Illisibles, nom)
				continue
			}
			if info.Mode()&(fs.ModeSymlink|fs.ModeIrregular) != 0 {
				continue
			}
			var taille int64
			if !estDossier {
				taille = info.Size()
				iv.fichiers++
			}
			ds.Enfants = append(ds.Enfants, element{nom, estDossier, taille, secondes(info.ModTime())})
			if estDossier && d.profondeur < profondeurMax {
				pile = append(pile, aVisiter{relatif, d.profondeur + 1})
			}
		}
		if err := iv.ajouter(ds); err != nil {
			return err
		}
	}
	return iv.vider()
}

func (iv *inventoriste) ajouter(ds dossierEnvoye) error {
	morceaux := []dossierEnvoye{ds}
	if len(ds.Enfants) > enfantsMaxParMorceau {
		morceaux = nil
		for i := 0; i < len(ds.Enfants); i += enfantsMaxParMorceau {
			fin := min(i+enfantsMaxParMorceau, len(ds.Enfants))
			m := dossierEnvoye{Chemin: ds.Chemin, Enfants: ds.Enfants[i:fin]}
			if i == 0 {
				m.Illisibles = ds.Illisibles
			}
			morceaux = append(morceaux, m)
		}
	}
	for _, m := range morceaux {
		iv.lot = append(iv.lot, m)
		iv.nbLot += len(m.Enfants) + len(m.Illisibles)
		if len(iv.lot) >= iv.lotMax || iv.nbLot >= enfantsMaxParLot {
			if err := iv.vider(); err != nil {
				return err
			}
		}
	}
	return nil
}

func (iv *inventoriste) vider() error {
	if len(iv.lot) == 0 {
		return nil
	}
	err := iv.envoyer(iv.lot)
	iv.lot, iv.nbLot = nil, 0
	return err
}

// inventorier : un envoi complet pour une racine (ouverture, lots, fin).
func inventorier(cl *Client, r racine, excl exclusions, lotMax int, arret <-chan struct{}) error {
	var ouvert struct {
		EnvoiID int64 `json:"envoi_id"`
	}
	if err := cl.poster("/api/agent/envois", map[string]int{"emplacement_id": r.EmplacementID}, false,
		&ouvert); err != nil {
		return fmt.Errorf("ouverture de l'envoi : %w", err)
	}
	base := fmt.Sprintf("/api/agent/envois/%d", ouvert.EnvoiID)
	iv := &inventoriste{racine: r.Racine, excl: excl, lotMax: lotMax, arret: arret,
		envoyer: func(lot []dossierEnvoye) error {
			return cl.poster(base+"/lots", map[string]any{"dossiers": lot}, true, nil)
		}}
	debut := time.Now()
	if err := iv.parcourir(); err != nil {
		return fmt.Errorf("envoi interrompu (le serveur l'abandonnera) : %w", err)
	}
	if err := cl.poster(base+"/fin", map[string]any{}, false, nil); err != nil {
		return fmt.Errorf("fin de l'envoi : %w", err)
	}
	log.Printf("Inventaire de %s envoyé : %d dossiers, %d fichiers, %d erreurs, en %s", r.Racine,
		iv.dossiers, iv.fichiers, iv.erreurs, time.Since(debut).Round(time.Second))
	return nil
}
