//go:build !windows

package main

import (
	"os"
	"syscall"
)

func aLaDemande(_ os.FileInfo) bool { return false }

func abaisserPriorite() { _ = syscall.Setpriority(syscall.PRIO_PROCESS, 0, 10) }
