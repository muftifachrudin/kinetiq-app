"""Fetch Railway deployment status and build/deploy logs via the public
GraphQL API -- no dashboard, no screenshots.

Replaces the manual "open Railway dashboard, screenshot Build Logs AND
Deploy Logs" loop from docs/deployment-runbook.md: both failure classes
(dependency-install failures vs container crash/healthcheck) are now one
command away from any environment that has RAILWAY_TOKEN.

Usage (RAILWAY_TOKEN must be set -- a Project Token, scoped to one
project+environment):

    python tools/railway_logs.py                     # latest deployment per service
    python tools/railway_logs.py --service api-gateway --logs both
    python tools/railway_logs.py --deployment-id <uuid> --logs deploy --limit 300

Gotchas learned probing the real project (2026-07-04), also recorded in
docs/deployment-runbook.md:
- The auth header for a Project Token is `Project-Access-Token`, NOT
  `Authorization: Bearer` (that's for personal/team tokens).
- Cloudflare in front of backboard.railway.com rejects Python's default
  urllib User-Agent with HTTP 403 "error code: 1010" -- any explicit
  User-Agent passes. Not an auth problem, don't rotate the token over it.
- A Project Token cannot read `project(id: ...)` (403); it CAN read
  `projectToken`, `deployments`, `buildLogs`, `deploymentLogs`. Service
  names are discovered through the deployments list instead.
- `deploymentLogs` marks anything the container wrote to stderr as
  severity "error" -- uvicorn/alembic write their normal INFO lines to
  stderr, so severity=error there does NOT mean the app is failing. Read
  the message text, not the severity.
- Build logs embed ANSI color codes; stripped by default (--raw keeps them).
"""

import argparse
import json
import os
import re
import sys
import urllib.request

GRAPHQL_URL = "https://backboard.railway.com/graphql/v2"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def gql(query: str, variables: dict | None = None) -> dict:
    token = os.environ.get("RAILWAY_TOKEN")
    if not token:
        sys.exit("RAILWAY_TOKEN is not set (needs a Railway Project Token)")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Project-Access-Token": token,
            "Content-Type": "application/json",
            # Cloudflare 403s the default Python-urllib UA (error code 1010)
            "User-Agent": "kinetiq-railway-logs/1.0",
        },
    )
    body = json.loads(urllib.request.urlopen(request, timeout=30).read())
    if body.get("errors"):
        sys.exit(f"GraphQL error: {json.dumps(body['errors'])[:500]}")
    return body["data"]


def project_scope() -> tuple[str, str]:
    data = gql("query { projectToken { projectId environmentId } }")
    return data["projectToken"]["projectId"], data["projectToken"]["environmentId"]


def list_deployments(project_id: str, environment_id: str, first: int = 20) -> list[dict]:
    data = gql(
        """query($pid: String!, $eid: String!, $first: Int!) {
             deployments(input: {projectId: $pid, environmentId: $eid}, first: $first) {
               edges { node { id status createdAt service { id name } } }
             } }""",
        {"pid": project_id, "eid": environment_id, "first": first},
    )
    return [edge["node"] for edge in data["deployments"]["edges"]]


def latest_per_service(deployments: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for deployment in deployments:  # API returns newest-first
        name = deployment["service"]["name"]
        if name not in latest:
            latest[name] = deployment
    return latest


def fetch_logs(kind: str, deployment_id: str, limit: int) -> list[dict]:
    field = {"build": "buildLogs", "deploy": "deploymentLogs"}[kind]
    data = gql(
        f"""query($id: String!, $limit: Int!) {{
              {field}(deploymentId: $id, limit: $limit) {{ timestamp message severity }}
            }}""",
        {"id": deployment_id, "limit": limit},
    )
    return data[field]


def print_logs(kind: str, deployment_id: str, limit: int, raw: bool) -> None:
    lines = fetch_logs(kind, deployment_id, limit)
    header = f"==== {kind.upper()} LOGS ({deployment_id}, last {len(lines)} lines) ===="
    print(header)
    if kind == "deploy" and lines:
        print("(note: severity=error just means the line came from stderr -- "
              "uvicorn/alembic INFO lines land there too)")
    for line in lines:
        message = line["message"] if raw else ANSI_RE.sub("", line["message"])
        print(f"{line['timestamp']} [{line['severity']}] {message}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--service", help="only this service (name as shown in Railway)")
    parser.add_argument("--deployment-id", help="operate on this deployment instead of the latest")
    parser.add_argument("--logs", choices=["build", "deploy", "both", "none"], default="none",
                        help="which logs to print for the selected deployment(s)")
    parser.add_argument("--limit", type=int, default=100, help="max log lines per kind (default 100)")
    parser.add_argument("--raw", action="store_true", help="keep ANSI color codes in log output")
    args = parser.parse_args(argv)

    if args.deployment_id:
        targets = [args.deployment_id]
    else:
        project_id, environment_id = project_scope()
        latest = latest_per_service(list_deployments(project_id, environment_id))
        if args.service:
            if args.service not in latest:
                sys.exit(f"service {args.service!r} not found; have: {sorted(latest)}")
            latest = {args.service: latest[args.service]}
        print(f"project {project_id} / environment {environment_id}")
        for name, deployment in sorted(latest.items()):
            print(f"  {name:20s} {deployment['status']:10s} {deployment['createdAt']}  {deployment['id']}")
        print()
        targets = [d["id"] for d in latest.values()]

    if args.logs != "none":
        kinds = ["build", "deploy"] if args.logs == "both" else [args.logs]
        for deployment_id in targets:
            for kind in kinds:
                print_logs(kind, deployment_id, args.limit, args.raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
