// config.go — configuration LOCALE de l'agent : où est le serveur, son jeton, et la
// liste blanche des dossiers qu'il accepte d'inventorier.
//
// Le serveur décide QUELS dossiers inventorier ; cette liste locale décide ce qui est
// PERMIS sur ce PC. Un serveur compromis ne peut donc pas faire lire C:\Windows à l'agent
// si l'installation ne l'a pas autorisé.
//
//	{
//	  "serveur_url": "https://rangement.exemple.fr",
//	  "jeton": "mato_…",
//	  "racines_autorisees": ["C:\\Users", "D:\\"]
//	}
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

type Config struct {
	ServeurURL        string   `json:"serveur_url"`
	Jeton             string   `json:"jeton"`
	RacinesAutorisees []string `json:"racines_autorisees"`
}

func cheminConfigParDefaut() string {
	if runtime.GOOS == "windows" {
		pd := os.Getenv("ProgramData")
		if pd == "" {
			pd = `C:\ProgramData`
		}
		return filepath.Join(pd, dossierDonnees, "agent.json")
	}
	return "/etc/rangement/agent.json"
}

func chargerConfig(chemin string) (*Config, error) {
	data, err := os.ReadFile(chemin)
	if err != nil {
		return nil, fmt.Errorf("lecture de %s : %w", chemin, err)
	}
	var c Config
	if err := json.Unmarshal(data, &c); err != nil {
		return nil, fmt.Errorf("JSON invalide dans %s : %w", chemin, err)
	}
	return &c, c.valider()
}

func (c *Config) valider() error {
	u, err := url.Parse(c.ServeurURL)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" {
		return errors.New("serveur_url doit être une adresse http(s) complète")
	}
	c.ServeurURL = strings.TrimRight(c.ServeurURL, "/")
	if !strings.HasPrefix(c.Jeton, "mato_") {
		return errors.New("jeton absent ou invalide (il commence par « mato_ »)")
	}
	if len(c.RacinesAutorisees) == 0 {
		return errors.New("racines_autorisees est vide : l'agent n'inventorierait rien")
	}
	for i, r := range c.RacinesAutorisees {
		if !filepath.IsAbs(r) {
			return fmt.Errorf("racine autorisée non absolue : %q", r)
		}
		c.RacinesAutorisees[i] = filepath.Clean(r)
	}
	return nil
}

// autorisee : `racine` (demandée par le serveur) est-elle dans la liste blanche locale ?
func (c *Config) autorisee(racine string) bool {
	if !filepath.IsAbs(racine) {
		return false
	}
	for _, a := range c.RacinesAutorisees {
		if sousDossier(a, racine) {
			return true
		}
	}
	return false
}

// reelSous : le chemin RÉEL de `chemin` (liens et jonctions résolus, y compris ceux des
// dossiers intermédiaires) est-il sous le chemin réel de `base` ? Le service tourne en
// LocalSystem : une jonction plantée dans un dossier confié ne doit pas faire lire ailleurs.
func reelSous(base, chemin string) bool {
	b, err := filepath.EvalSymlinks(base)
	if err != nil {
		return false
	}
	c, err := filepath.EvalSymlinks(chemin)
	if err != nil {
		return false
	}
	return sousDossier(b, c)
}

// racineSure : le chemin réel de la racine (liens et jonctions résolus) reste sous le chemin
// réel d'une entrée de la liste blanche. On compare des chemins
// RÉSOLUS des deux côtés : sous Windows, la résolution développe aussi les noms courts
// (`RUNNER~1` → `runneradmin`), qu'une comparaison brute prendrait pour un lien.
func (c *Config) racineSure(racine string) bool {
	if !filepath.IsAbs(racine) {
		return false
	}
	reel, err := filepath.EvalSymlinks(racine)
	if err != nil {
		return false
	}
	for _, a := range c.RacinesAutorisees {
		if ra, err := filepath.EvalSymlinks(a); err == nil && sousDossier(ra, reel) {
			return true
		}
	}
	return false
}

// sousDossier : `enfant` est-il `parent` ou en dessous ? Sans casse sous Windows.
func sousDossier(parent, enfant string) bool {
	p, e := filepath.Clean(parent), filepath.Clean(enfant)
	if runtime.GOOS == "windows" {
		p, e = strings.ToLower(p), strings.ToLower(e)
	}
	if e == p {
		return true
	}
	if !strings.HasSuffix(p, string(filepath.Separator)) {
		p += string(filepath.Separator)
	}
	return strings.HasPrefix(e, p)
}
