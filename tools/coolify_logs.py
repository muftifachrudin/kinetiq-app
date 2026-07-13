"""Fetch Coolify application status, container logs, and deployment/build
logs via the REST API -- replaces tools/railway_logs.py now that compute
runs on self-hosted Coolify instead of Railway (13 July 2026 migration).

Usage (COOLIFY_URL and COOLIFY_TOKEN must be set -- an API token from
Coolify's Security -> API Tokens, `read` permission is enough for this
tool):

    python tools/coolify_logs.py                          # list applications + status
    python tools/coolify_logs.py --app <uuid> --logs container
    python tools/coolify_logs.py --app <uuid> --logs build --limit 200

Two distinct log sources, same distinction the old Railway tool made
between Build Logs and Deploy Logs:
- `container`: GET /api/v1/applications/{uuid}/logs -- tail of the running
  container's stdout/stderr, single string field.
- `build`: GET /api/v1/deployments/applications/{uuid} -- the most recent
  deployment's structured build/deploy log (a JSON array of
  {output, type, timestamp} entries embedded as a string in the `logs`
  field of each deployment record), plus its status (finished/failed/etc).

`--app` accepts a Coolify application UUID (as shown by the no-argument
listing) or an exact name match.
"""

import argparse
import json
import os
import sys
import urllib.request


def api_get(path: str) -> dict | list:
    base_url = os.environ.get("COOLIFY_URL")
    token = os.environ.get("COOLIFY_TOKEN")
    if not base_url or not token:
        sys.exit("COOLIFY_URL and COOLIFY_TOKEN must both be set")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return json.loads(urllib.request.urlopen(request, timeout=30).read())


def list_applications() -> list[dict]:
    return api_get("applications")


def resolve_app_uuid(identifier: str, apps: list[dict]) -> str:
    for app in apps:
        if app["uuid"] == identifier or app["name"] == identifier:
            return app["uuid"]
    sys.exit(f"no application found matching {identifier!r}; have: {[a['name'] for a in apps]}")


def print_container_logs(uuid: str) -> None:
    data = api_get(f"applications/{uuid}/logs")
    print(f"==== CONTAINER LOGS ({uuid}) ====")
    print(data.get("logs", "(empty)"))
    print()


def print_build_logs(uuid: str, limit: int) -> None:
    data = api_get(f"deployments/applications/{uuid}")
    deployments = data.get("deployments", [])
    if not deployments:
        print(f"no deployments recorded for {uuid}")
        return
    latest = deployments[0]
    print(
        f"==== BUILD/DEPLOY LOG ({uuid}, deployment {latest['deployment_uuid']}, "
        f"status={latest['status']}, commit={latest['commit'][:12]}) ===="
    )
    entries = json.loads(latest.get("logs") or "[]")
    for entry in entries[-limit:]:
        stream = entry.get("type", "stdout")
        print(f"{entry.get('timestamp', '')} [{stream}] {entry.get('output', '')}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", help="application UUID or exact name (default: list all applications + status)")
    parser.add_argument("--logs", choices=["container", "build", "both"], default=None,
                        help="which logs to print for --app (default: both)")
    parser.add_argument("--limit", type=int, default=100, help="max build/deploy log lines (default 100)")
    args = parser.parse_args(argv)

    apps = list_applications()

    if not args.app:
        print(f"{'NAME':40s} {'STATUS':20s} UUID")
        for app in sorted(apps, key=lambda a: a["name"]):
            print(f"{app['name']:40s} {app.get('status', '?'):20s} {app['uuid']}")
        return 0

    uuid = resolve_app_uuid(args.app, apps)
    logs = args.logs or "both"
    if logs in ("container", "both"):
        print_container_logs(uuid)
    if logs in ("build", "both"):
        print_build_logs(uuid, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
