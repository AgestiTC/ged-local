//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/sys/windows"
)

// Régression CI du 2026-10-14 : sur un runner, le dossier temporaire porte un nom court
// (C:\Users\RUNNER~1\…). La racine confiée doit être acceptée qu'on l'écrive en nom court
// ou en nom long.
func TestRacineEnNomCourtAcceptee(t *testing.T) {
	long := filepath.Join(t.TempDir(), "Un dossier au nom long")
	if err := os.MkdirAll(long, 0o755); err != nil {
		t.Fatal(err)
	}
	p, _ := windows.UTF16PtrFromString(long)
	tampon := make([]uint16, 1024)
	n, err := windows.GetShortPathName(p, &tampon[0], uint32(len(tampon)))
	if err != nil || n == 0 {
		t.Skip("noms courts désactivés sur ce volume")
	}
	court := windows.UTF16ToString(tampon[:n])
	if court == long {
		t.Skip("aucun nom court distinct pour ce chemin")
	}
	for _, cas := range [][2]string{{court, court}, {long, court}, {court, long}} {
		cfg := &Config{ServeurURL: "http://x", Jeton: "mato_x", RacinesAutorisees: []string{cas[0]}}
		if !cfg.racineSure(cas[1]) {
			t.Errorf("liste blanche %q, racine %q : refusée à tort", cas[0], cas[1])
		}
	}
}
