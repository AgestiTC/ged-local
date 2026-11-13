// Package main — rangement-agent : l'agent de poste de « rangement » (chantier 2d).
//
// Un exe unique, installé en service Windows (installer-agent.ps1). À chaque contact
// (toutes les 15 min par défaut, réglé par le serveur) :
//  1. il demande sa configuration au serveur (dossiers confiés, et s'ils sont « dus ») ;
//  2. il inventorie les dossiers dus — métadonnées seulement — et les envoie par lots ;
//  3. il calcule les empreintes demandées pour les copies multiples, dans la limite du jour.
//
// Il ne déplace, ne renomme ni ne supprime rien. Ossature (service, boucle) reprise de
// netsight-host-agent (NetSight MATO), avec une identité Windows propre (identite.go).
//
// Essai : rangement-agent.exe -config agent.json -une-fois
package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"time"
)

func main() {
	cheminConfig := flag.String("config", cheminConfigParDefaut(), "fichier de configuration JSON")
	uneFois := flag.Bool("une-fois", false, "un seul cycle puis quitte (essai)")
	version := flag.Bool("version", false, "affiche la version et quitte")
	flag.Parse()

	if *version {
		fmt.Println("rangement-agent " + VersionAgent)
		return
	}
	fermer := ouvrirJournal(filepath.Join(filepath.Dir(*cheminConfig), "agent.log"))
	defer fermer()

	cfg, err := chargerConfig(*cheminConfig)
	if err != nil {
		log.Fatalf("Configuration invalide : %v", err)
	}
	log.Printf("rangement-agent %s — serveur %s, racines autorisées %v", VersionAgent, cfg.ServeurURL,
		cfg.RacinesAutorisees)
	abaisserPriorite()

	if !*uneFois && lancerCommeService(cfg) {
		return
	}
	boucle(cfg, *uneFois, nil)
}

// ouvrirJournal : stdout + fichier, avec une rotation simple (5 Mo → agent.log.1).
func ouvrirJournal(chemin string) func() {
	if info, err := os.Stat(chemin); err == nil && info.Size() > 5<<20 {
		_ = os.Rename(chemin, chemin+".1")
	}
	f, err := os.OpenFile(chemin, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return func() {}
	}
	log.SetOutput(io.MultiWriter(os.Stdout, f))
	return func() { _ = f.Close() }
}

func arreteDemande(arret <-chan struct{}) bool {
	if arret == nil {
		return false
	}
	select {
	case <-arret:
		return true
	default:
		return false
	}
}

func boucle(cfg *Config, uneFois bool, arret <-chan struct{}) {
	cl := nouveauClient(cfg)
	intervalle := 15 * time.Minute
	for {
		if n := cycle(cl, cfg, arret); n > 0 {
			intervalle = time.Duration(n) * time.Minute
		}
		if uneFois {
			return
		}
		select {
		case <-time.After(intervalle):
		case <-arret:
			log.Println("Arrêt demandé")
			return
		}
	}
}

// cycle : un contact complet avec le serveur. Rend l'intervalle demandé (minutes), 0 si inconnu.
func cycle(cl *Client, cfg *Config, arret <-chan struct{}) int {
	var cs configServeur
	if err := cl.obtenir("/api/agent/config", &cs); err != nil {
		log.Printf("Serveur injoignable ou refus : %v", err)
		return 0
	}
	if cs.VersionProtocole != versionProtocole {
		log.Printf("Protocole %d du serveur incompatible avec cet agent (%d) : mettre l'agent à jour",
			cs.VersionProtocole, versionProtocole)
		return cs.IntervalleMin
	}
	excl := nouvellesExclusions(cs.ExclusionsNoms, cs.ExclusionsMotifs)
	racines := map[int]string{}
	for _, r := range cs.Racines {
		if !cfg.racineSure(r.Racine) {
			log.Printf("Dossier %s refusé : hors des racines autorisées sur ce PC, absent, ou lien", r.Racine)
			continue
		}
		racines[r.EmplacementID] = r.Racine
		if !r.InventaireDu || arreteDemande(arret) {
			continue
		}
		if err := inventorier(cl, r, excl, cs.LotMaxDossiers, arret); err != nil {
			log.Printf("Inventaire de %s : %v", r.Racine, err)
		}
	}
	if !arreteDemande(arret) {
		calculerEmpreintes(cl, cfg, racines, arret)
	}
	return cs.IntervalleMin
}
