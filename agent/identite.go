// identite.go — identité Windows de l'agent de rangement.
//
// ⚠️ SOURCE UNIQUE. Leçon de NetSight (PLAN-BASCULE-100-MATO.md) : deux produits qui
// partagent un nom de service se désinstallent et s'arrêtent l'un l'autre. Tout ce qui
// nomme le service ou ses dossiers passe par ces valeurs — `installer-agent.ps1` les
// reprend à l'identique, et TestIdentiteAligneeAvecLInstalleur le vérifie.
package main

const (
	// Nom du service Windows (SCM).
	nomService = "RangementAgent"
	// Dossier sous %ProgramData% : configuration (avec le jeton) et journal.
	dossierDonnees = "Rangement"
	// Version du protocole parlé avec le serveur (`/api/agent/config`).
	versionProtocole = 1
)

// VersionAgent est injectée à la construction : -ldflags "-X main.VersionAgent=0.1.0".
// « dev » signale un exe construit sans `construire.ps1`.
var VersionAgent = "dev"
