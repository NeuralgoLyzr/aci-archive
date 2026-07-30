#!/usr/bin/env python3
"""Resolve the value of the ``LYZR_API_KEY_ID_DB`` environment variable for an
ACI deployment.

``LYZR_API_KEY_ID_DB`` must hold the ``api_keys.id`` (a UUID, *not* the API key
secret) of the platform/system API key. Every app and function seeded by the
platform is stored with ``apps.api_key_id = LYZR_API_KEY_ID_DB``, and the server
falls back to that id when resolving apps/functions for a caller
(``aci.common.utils.get_lyzr_api_key_id``). If the variable is unset or points at
the wrong row, platform-seeded tools become invisible / are reported as
``custom_app``.

This script talks to the deployment over HTTP only (no DB access, no auth) using
the same call the infra runbook uses:

    POST {base_url}/v1/projects  {"name": ..., "org_id": ...}
        -> agents[0].api_keys[0].id

By default the script is idempotent: it first looks for an existing project of
the org (``GET /v1/projects`` with the ``X-ACI-ORG-ID`` header) and reuses its
oldest active API key, so re-running it does not burn the per-org project quota
(``SERVER_MAX_PROJECTS_PER_ORG``) and does not change the value that already-seeded
apps are bound to. Pass ``--force-create`` to always create a new project.

The server normally resolves this itself on startup
(``aci.common.platform_api_key.seed_env_from_db``, same selection rule), so this script is
for deployments rolled out before that existed, for recording the value in a secret store,
or for checking what a deployment resolved. With DB access, prefer
``python -m aci.cli ensure-platform-api-key``.

Requires only the Python 3 standard library.

Examples
--------
    # print just the UUID (stdout is machine-readable, logs go to stderr)
    ./scripts/seed_lyzr_api_key_id.py \
        --url https://aci.azure.lyzr.app \
        --org-id 2c06717b-c034-471a-b7fb-c8e3f5791042

    # export line for a shell / env file, and update backend/.env in place
    ./scripts/seed_lyzr_api_key_id.py --format env --env-file .env

    # full detail (includes the API key secret)
    ./scripts/seed_lyzr_api_key_id.py --format json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

ENV_VAR = "LYZR_API_KEY_ID_DB"
ORG_ID_HEADER = "X-ACI-ORG-ID"  # aci.server.config.ACI_ORG_ID_HEADER
PROJECTS_PATH = "/v1/projects"  # aci.server.config.ROUTER_PREFIX_PROJECTS

# Sorts before every real ISO-8601 timestamp, so records without one lose the
# "oldest wins" comparison instead of blowing up.
_MIN_TIMESTAMP = ""


def log(message: str) -> None:
    print(message, file=sys.stderr)


class SeedError(Exception):
    """Fatal, user-facing error."""


def request_json(
    url: str,
    *,
    method: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
    retries: int,
    retry_delay: float,
) -> Any:
    """Perform a JSON request, retrying connection errors and 5xx responses.

    A freshly rolled-out deployment often refuses connections for a few seconds,
    so retries are on by default. 4xx responses are never retried; they carry the
    real reason (quota exceeded, bad org id, wrong URL) and are surfaced as-is.
    """
    payload = None if body is None else json.dumps(body).encode()
    request_headers = {"accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            if error.code < 500:
                raise SeedError(
                    f"{method} {url} -> HTTP {error.code}: {detail or error.reason}"
                ) from error
            last_error = SeedError(f"{method} {url} -> HTTP {error.code}: {detail or error.reason}")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = SeedError(f"{method} {url} -> {error}")
        else:
            try:
                return json.loads(raw)
            except json.JSONDecodeError as error:
                raise SeedError(f"{method} {url} -> response is not JSON: {raw[:500]!r}") from error

        if attempt < retries:
            log(
                f"  attempt {attempt}/{retries} failed ({last_error}); retrying in {retry_delay:g}s"
            )
            time.sleep(retry_delay)

    raise SeedError(str(last_error))


def _created_at(record: dict[str, Any]) -> str:
    return record.get("created_at") or _MIN_TIMESTAMP


def pick_api_key(project: dict[str, Any]) -> dict[str, Any] | None:
    """Return the oldest active API key of a project, deterministically.

    Ties (identical or missing ``created_at``, which the DB default makes common
    for a project and its default agent) are broken by id so repeated runs on an
    unchanged deployment always yield the same value.
    """
    candidates: list[dict[str, Any]] = [
        api_key
        for agent in project.get("agents") or []
        for api_key in agent.get("api_keys") or []
        if api_key.get("id") and str(api_key.get("status", "active")).lower() == "active"
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda api_key: (_created_at(api_key), str(api_key["id"])))


def pick_project(projects: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Oldest project that already owns an active API key, preferring ``name``."""
    usable = [project for project in projects if pick_api_key(project)]
    if not usable:
        return None
    preferred = [project for project in usable if project.get("name") == name] or usable
    return min(preferred, key=lambda project: (_created_at(project), str(project.get("id"))))


def find_existing(
    base_url: str, org_id: str, name: str, **request_kwargs: Any
) -> dict[str, Any] | None:
    projects = request_json(
        base_url + PROJECTS_PATH,
        method="GET",
        headers={ORG_ID_HEADER: org_id},
        **request_kwargs,
    )
    if not isinstance(projects, list):
        raise SeedError(f"GET {PROJECTS_PATH} returned {type(projects).__name__}, expected a list")
    if not projects:
        return None
    return pick_project(projects, name)


def create_project(base_url: str, org_id: str, name: str, **request_kwargs: Any) -> dict[str, Any]:
    project = request_json(
        base_url + PROJECTS_PATH,
        method="POST",
        body={"name": name, "org_id": org_id},
        **request_kwargs,
    )
    if not isinstance(project, dict):
        raise SeedError(
            f"POST {PROJECTS_PATH} returned {type(project).__name__}, expected an object"
        )
    return project


def resolve(args: argparse.Namespace) -> dict[str, str]:
    request_kwargs = {
        "timeout": args.timeout,
        "retries": args.retries,
        "retry_delay": args.retry_delay,
    }
    project: dict[str, Any] | None = None

    if not args.force_create:
        log(f"Looking for an existing project of org {args.org_id} ...")
        project = find_existing(args.url, args.org_id, args.name, **request_kwargs)
        if project is None:
            log("  none usable; creating one")
        else:
            log(f"  reusing project {project.get('id')} ({project.get('name')!r})")

    if project is None:
        log(f"Creating project {args.name!r} for org {args.org_id} ...")
        project = create_project(args.url, args.org_id, args.name, **request_kwargs)
        log(f"  created project {project.get('id')}")

    api_key = pick_api_key(project)
    if api_key is None:
        raise SeedError(
            f"project {project.get('id')} has no active API key "
            f"(response: {json.dumps(project)[:500]}). The server logs the reason when it "
            "fails to decrypt an API key; check SERVER_SIGNING_KEY / KMS configuration."
        )

    api_key_id = str(api_key["id"])
    try:
        uuid.UUID(api_key_id)
    except ValueError as error:
        raise SeedError(f"api key id {api_key_id!r} is not a UUID") from error

    agent_id = next(
        (
            str(agent.get("id"))
            for agent in project.get("agents") or []
            if any(str(key.get("id")) == api_key_id for key in agent.get("api_keys") or [])
        ),
        str(api_key.get("agent_id", "")),
    )

    return {
        "project_id": str(project.get("id", "")),
        "agent_id": agent_id,
        "api_key_id": api_key_id,
        "api_key": str(api_key.get("key", "")),
    }


def write_env_file(path: str, value: str) -> None:
    """Upsert ``LYZR_API_KEY_ID_DB=<value>`` in an env file, keeping the rest intact."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        lines = []

    assignment = f"{ENV_VAR}={value}"
    pattern = re.compile(rf"^\s*(export\s+)?{ENV_VAR}\s*=")
    replaced = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = assignment
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# api_keys.id of the platform API key; see scripts/seed_lyzr_api_key_id.py")
        lines.append(assignment)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    log(f"{'Updated' if replaced else 'Appended'} {ENV_VAR} in {path}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Resolve the {ENV_VAR} value (api_keys.id of the platform API key) for an ACI deployment.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=os.getenv("ACI_SERVER_URL") or os.getenv("CLI_SERVER_URL"),
        help="base URL of the ACI deployment, e.g. https://aci.azure.lyzr.app "
        "[env: ACI_SERVER_URL, CLI_SERVER_URL]",
    )
    parser.add_argument(
        "--org-id",
        default=os.getenv("ACI_ORG_ID"),
        help="organization id the project belongs to [env: ACI_ORG_ID]",
    )
    parser.add_argument("--name", default="Default Org", help="project name to reuse or create")
    parser.add_argument(
        "--force-create",
        action="store_true",
        help="always POST a new project instead of reusing an existing one "
        "(consumes the per-org project quota and yields a NEW id)",
    )
    parser.add_argument(
        "--format",
        choices=("value", "env", "json"),
        default="value",
        help="stdout format: bare UUID, 'LYZR_API_KEY_ID_DB=<uuid>', or full JSON detail",
    )
    parser.add_argument("--env-file", help=f"upsert {ENV_VAR} in this env file")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="per-request timeout in seconds"
    )
    parser.add_argument(
        "--retries", type=int, default=5, help="attempts per request (connection errors and 5xx)"
    )
    parser.add_argument(
        "--retry-delay", type=float, default=2.0, help="delay between attempts in seconds"
    )

    args = parser.parse_args(argv)

    missing = [
        flag for flag, value in (("--url", args.url), ("--org-id", args.org_id)) if not value
    ]
    if missing:
        parser.error(f"missing required argument(s): {', '.join(missing)}")
    if not args.url.startswith(("http://", "https://")):
        parser.error(f"--url must start with http:// or https:// (got {args.url!r})")
    args.url = args.url.rstrip("/")
    try:
        uuid.UUID(args.org_id)
    except ValueError:
        parser.error(f"--org-id must be a UUID (got {args.org_id!r})")
    if args.retries < 1:
        parser.error("--retries must be >= 1")

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = resolve(args)
    except SeedError as error:
        log(f"ERROR: {error}")
        return 1

    if args.env_file:
        write_env_file(args.env_file, result["api_key_id"])

    if args.format == "json":
        print(json.dumps(result, indent=2))
    elif args.format == "env":
        print(f"{ENV_VAR}={result['api_key_id']}")
    else:
        print(result["api_key_id"])

    log(f"Set {ENV_VAR}={result['api_key_id']} on the ACI server and restart it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
