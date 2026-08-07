#!/usr/bin/env python3
"""Execute a Camayoc metric retrieval method without storing its sample."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def execute(method: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    system = method.get("system")
    query = method.get("query")
    params = method.get("params") or {}
    if not system or not query:
        return {"status": "invalid", "error": "method requires system and query"}
    if system != "prometheus":
        return {"status": "unsupported", "system": system}
    endpoint = params.get("endpoint")
    if not endpoint:
        return {"status": "unreachable", "system": system, "error": "no endpoint declared"}
    url = endpoint.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        return {"status": "unreachable", "system": system, "error": str(exc)}
    if payload.get("status") != "success":
        return {"status": "query_error", "system": system, "response": payload}
    return {"status": "retrieved", "system": system, "result": payload.get("data", {}).get("result", [])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method", help="JSON file containing system, query, params")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    with open(args.method, encoding="utf-8") as handle:
        method = json.load(handle)
    result = execute(method, args.timeout)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "retrieved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
