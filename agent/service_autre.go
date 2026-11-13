//go:build !windows

package main

// Hors Windows, systemd ou launchd gèrent le cycle de vie : mode console.
func lancerCommeService(_ *Config) bool { return false }
