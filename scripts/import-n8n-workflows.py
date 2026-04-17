"""
Import des workflows DocFlow dans n8n via l'API REST.

Usage :
    python import-n8n-workflows.py --url http://192.168.42.130:5678 --api-key <clé>

Obtenir la clé API n8n :
    n8n UI → Settings (roue dentée en bas à gauche) → API → Create an API key

Les workflows importés utilisent la variable d'environnement n8n DOCFLOW_API_URL.
À configurer dans n8n : Settings → Environment variables → DOCFLOW_API_URL=http://192.168.42.130:8000
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).parent.parent / "n8n" / "workflows"

# L'API n8n v1 n'accepte que ces champs à la création
ALLOWED_FIELDS = {"name", "nodes", "connections", "settings", "staticData"}


def load_workflow(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k in ALLOWED_FIELDS}


def api_request(base_url: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} — {body_err}") from e


def list_existing(base_url: str, api_key: str) -> dict[str, str]:
    """Retourne {nom_workflow: id} pour les workflows existants."""
    try:
        data = api_request(base_url, api_key, "GET", "/api/v1/workflows?limit=100")
        return {w["name"]: w["id"] for w in data.get("data", [])}
    except Exception:
        return {}


def import_workflow(base_url: str, api_key: str, wf: dict, existing: dict[str, str]) -> str:
    name = wf["name"]
    if name in existing:
        wf_id = existing[name]
        api_request(base_url, api_key, "PUT", f"/api/v1/workflows/{wf_id}", wf)
        return f"mis à jour (id={wf_id})"
    else:
        result = api_request(base_url, api_key, "POST", "/api/v1/workflows", wf)
        return f"créé (id={result.get('id', '?')})"


def activate_workflow(base_url: str, api_key: str, name: str, existing: dict[str, str]) -> None:
    """Active un workflow après import."""
    wf_id = existing.get(name)
    if not wf_id:
        # Re-lire les workflows après création
        existing.update(list_existing(base_url, api_key))
        wf_id = existing.get(name)
    if wf_id:
        try:
            api_request(base_url, api_key, "POST", f"/api/v1/workflows/{wf_id}/activate")
        except Exception as e:
            print(f"  [WARN] Activation echouee pour '{name}' : {e}")


def main():
    parser = argparse.ArgumentParser(description="Import workflows DocFlow dans n8n")
    parser.add_argument("--url", default="http://192.168.42.130:5678", help="URL de l'instance n8n")
    parser.add_argument("--api-key", required=True, help="Clé API n8n")
    parser.add_argument("--no-activate", action="store_true", help="Ne pas activer les workflows après import")
    args = parser.parse_args()

    print(f"n8n : {args.url}")

    # Vérifier la connectivité
    try:
        api_request(args.url, args.api_key, "GET", "/api/v1/workflows?limit=1")
        print("Connexion n8n OK\n")
    except Exception as e:
        print(f"Impossible de joindre n8n : {e}", file=sys.stderr)
        sys.exit(1)

    existing = list_existing(args.url, args.api_key)

    workflow_files = sorted(WORKFLOWS_DIR.glob("*.json"))
    if not workflow_files:
        print("Aucun fichier JSON trouvé dans n8n/workflows/", file=sys.stderr)
        sys.exit(1)

    results = {}
    for wf_file in workflow_files:
        wf = load_workflow(wf_file)
        name = wf["name"]
        try:
            status = import_workflow(args.url, args.api_key, wf, existing)
            results[name] = ("OK", status)
            print(f"  [OK] {name} -- {status}")
        except Exception as e:
            results[name] = ("ERREUR", str(e))
            print(f"  [ERREUR] {name} -- {e}", file=sys.stderr)

    # Activer les workflows à trigger automatique (pas le webhook)
    if not args.no_activate:
        print("\nActivation des workflows schedules...")
        existing.update(list_existing(args.url, args.api_key))
        for wf_file in workflow_files:
            wf = load_workflow(wf_file)
            first_node_type = wf["nodes"][0].get("type", "") if wf["nodes"] else ""
            if "scheduleTrigger" in first_node_type or "cron" in first_node_type.lower():
                activate_workflow(args.url, args.api_key, wf["name"], existing)
                print(f"  [OK] {wf['name']} active")

    errors = [n for n, (s, _) in results.items() if s == "ERREUR"]
    print(f"\nImport termine -- {len(results) - len(errors)}/{len(results)} workflows importes")

    if errors:
        print("Workflows en erreur :", ", ".join(errors))
        sys.exit(1)

    print("\nRappel : configurer dans n8n Settings -> Variables d'environnement :")
    print("  DOCFLOW_API_URL = http://192.168.42.130:8000")


if __name__ == "__main__":
    main()
