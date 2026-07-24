# Connecteur WebDAV — mise en route

Le connecteur **WebDAV** indexe un serveur distant en **lecture seule** via HTTP Basic
(pas d'OAuth). Il couvre un large éventail de serveurs : **Nextcloud / ownCloud**,
**Infomaniak kDrive**, **Synology WebDAV Server**, serveurs Apache/nginx `mod_dav`, etc.

## Où le configurer

**Paramètres → Connecteurs cloud → WebDAV → « Connecter un serveur WebDAV »**.

Un compte connecté = une **Source** (multi-comptes). Le mot de passe est **chiffré en local**
(Fernet) ; rien n'est stocké en clair.

## Champs à renseigner

| Champ | Rôle | Exemples |
|-------|------|----------|
| **Nom** | Libellé affiché | `Nextcloud perso` |
| **Utilisateur** | Compte WebDAV | `jean` |
| **Mot de passe** | Mot de passe ou **mot de passe d'application** (recommandé) | — |
| **URL de base** | Racine WebDAV | voir ci-dessous |
| **Dossier de départ** | *(facultatif)* sous-dossier relatif à la racine | `/Documents` |

### URL de base selon le serveur

- **Nextcloud / ownCloud** : `https://cloud.exemple.fr/remote.php/dav/files/<utilisateur>/`
  → créer un **mot de passe d'application** (Paramètres → Sécurité) plutôt que le mot de passe du compte.
- **Infomaniak kDrive** : `https://<id>.connect.kdrive.infomaniak.com/` (WebDAV activé côté kDrive).
- **Synology WebDAV Server** : `https://<nas>:5006/` (HTTPS) — activer le paquet *WebDAV Server*.
- **Apache/nginx `mod_dav`** : l'URL exposée par la config `<Location>` DAV.

## Vérifier et indexer

1. **« Connecter et tester »** crée le compte et teste immédiatement la connexion
   (pastille **verte** = OK, **rouge** = URL/identifiants à revoir).
2. **« Indexer »** lance une **tâche durable** qui parcourt récursivement le dossier,
   télécharge chaque fichier supporté, l'extrait (Tika) et l'enrichit — comme le NAS SMB.
3. Le contenu apparaît ensuite dans **GED** et dans **Paramètres → Dossiers indexés**
   (préfixe `webdav://<id>/…`), avec **synchro périodique** possible comme les autres sources.

> 100 % local : le seul flux réseau sortant est **vers ton serveur WebDAV** (aucun tiers).
