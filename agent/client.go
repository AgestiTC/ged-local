// client.go — échanges HTTP avec le serveur rangement (`/api/agent/*`).
//
// Différence voulue avec NetSight : le certificat TLS est TOUJOURS vérifié (pas de
// InsecureSkipVerify — c'est l'erreur que NetSight a dû corriger). En réseau local sans
// certificat, utiliser une adresse http:// du LAN.
package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

type ErreurHTTP struct {
	Statut  int
	Message string
}

func (e *ErreurHTTP) Error() string { return fmt.Sprintf("HTTP %d : %s", e.Statut, e.Message) }

type Client struct {
	base    string
	jeton   string
	http    *http.Client
	attente func(time.Duration)
}

func nouveauClient(c *Config) *Client {
	return &Client{base: c.ServeurURL, jeton: c.Jeton, http: &http.Client{Timeout: 2 * time.Minute},
		attente: time.Sleep}
}

// requete : trois essais (2 s puis 4 s d'attente) sur une panne réseau ou une erreur 5xx ;
// un refus net (4xx) n'est pas répété.
func (c *Client) requete(methode, chemin string, corps []byte, gz bool, sortie any) error {
	var dernier error
	for essai := 0; essai < 3; essai++ {
		if essai > 0 {
			c.attente(time.Duration(1<<essai) * time.Second)
		}
		err := c.une(methode, chemin, corps, gz, sortie)
		if err == nil {
			return nil
		}
		var eh *ErreurHTTP
		if errors.As(err, &eh) && eh.Statut < 500 && eh.Statut != http.StatusTooManyRequests {
			return err
		}
		dernier = err
	}
	return dernier
}

func (c *Client) une(methode, chemin string, corps []byte, gz bool, sortie any) error {
	var lecteur io.Reader
	if corps != nil {
		lecteur = bytes.NewReader(corps)
	}
	req, err := http.NewRequest(methode, c.base+chemin, lecteur)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.jeton)
	req.Header.Set("X-Agent-Version", VersionAgent)
	req.Header.Set("User-Agent", "rangement-agent/"+VersionAgent)
	if corps != nil {
		req.Header.Set("Content-Type", "application/json")
		if gz {
			req.Header.Set("Content-Encoding", "gzip")
		}
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	donnees, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode/100 != 2 {
		msg := string(donnees)
		if len(msg) > 300 {
			msg = msg[:300] + "…"
		}
		return &ErreurHTTP{Statut: resp.StatusCode, Message: msg}
	}
	if sortie != nil {
		return json.Unmarshal(donnees, sortie)
	}
	return nil
}

func (c *Client) obtenir(chemin string, sortie any) error {
	return c.requete(http.MethodGet, chemin, nil, false, sortie)
}

func (c *Client) poster(chemin string, valeur any, gz bool, sortie any) error {
	brut, err := json.Marshal(valeur)
	if err != nil {
		return err
	}
	if gz {
		var b bytes.Buffer
		w := gzip.NewWriter(&b)
		if _, err := w.Write(brut); err != nil {
			return err
		}
		if err := w.Close(); err != nil {
			return err
		}
		brut = b.Bytes()
	}
	return c.requete(http.MethodPost, chemin, brut, gz, sortie)
}

// configServeur : réponse de GET /api/agent/config.
type configServeur struct {
	VersionProtocole int      `json:"version_protocole"`
	IntervalleMin    int      `json:"intervalle_min"`
	LotMaxDossiers   int      `json:"lot_max_dossiers"`
	Racines          []racine `json:"racines"`
	ExclusionsNoms   []string `json:"exclusions_noms"`
	ExclusionsMotifs []string `json:"exclusions_motifs"`
}

type racine struct {
	EmplacementID int    `json:"emplacement_id"`
	Racine        string `json:"racine"`
	InventaireDu  bool   `json:"inventaire_du"`
}
