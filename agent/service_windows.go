//go:build windows

// service_windows.go — mode service Windows (repris de netsight-host-agent v0.4.117).
//
// Sans lui, le SCM tue l'exe au bout de 30 s (« erreur 1053 ») : un programme console
// n'annonce pas qu'il a démarré. Ici, l'exe détecte qu'il est lancé par le SCM, annonce
// « Running » aussitôt, puis délègue à `boucle` — interrompue proprement à l'arrêt.
package main

import (
	"log"

	"golang.org/x/sys/windows/svc"
)

type gestionnaire struct{ cfg *Config }

func (g *gestionnaire) Execute(_ []string, r <-chan svc.ChangeRequest, etat chan<- svc.Status) (bool, uint32) {
	etat <- svc.Status{State: svc.StartPending}
	arret := make(chan struct{})
	fini := make(chan struct{})
	go func() {
		boucle(g.cfg, false, arret)
		close(fini)
	}()
	etat <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}
	log.Printf("Service %s démarré", nomService)
attente:
	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Interrogate:
				etat <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				break attente
			}
		case <-fini:
			break attente
		}
	}
	etat <- svc.Status{State: svc.StopPending}
	close(arret)
	<-fini
	log.Printf("Service %s arrêté", nomService)
	return false, 0
}

// lancerCommeService : vrai si l'exe a été lancé par le SCM (et a tourné jusqu'à l'arrêt).
func lancerCommeService(cfg *Config) bool {
	estService, err := svc.IsWindowsService()
	if err != nil || !estService {
		return false
	}
	if err := svc.Run(nomService, &gestionnaire{cfg: cfg}); err != nil {
		log.Fatalf("Service : %v", err)
	}
	return true
}
