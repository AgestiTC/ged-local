//go:build windows

package main

import (
	"os"
	"syscall"

	"golang.org/x/sys/windows"
)

// Attributs d'un fichier « à la demande » (OneDrive, etc.) : le lire le téléchargerait.
const (
	attributRappelALOuverture = 0x00040000 // FILE_ATTRIBUTE_RECALL_ON_OPEN
	attributRappelALaLecture  = 0x00400000 // FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
	attributHorsLigne         = 0x00001000 // FILE_ATTRIBUTE_OFFLINE
)

func aLaDemande(info os.FileInfo) bool {
	d, ok := info.Sys().(*syscall.Win32FileAttributeData)
	if !ok {
		return false
	}
	return d.FileAttributes&(attributRappelALOuverture|attributRappelALaLecture|attributHorsLigne) != 0
}

// abaisserPriorite : mode « arrière-plan » de Windows — priorité processeur, disque et
// mémoire abaissées. Le PC sert d'abord à travailler.
func abaisserPriorite() {
	const processModeBackgroundBegin = 0x00100000
	_ = windows.SetPriorityClass(windows.CurrentProcess(), processModeBackgroundBegin)
}
