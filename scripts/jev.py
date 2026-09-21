#!/usr/bin/env python3
"""Jev (TypeSafe System One) — a thin, honest client for typed decisions.

Design: docs/design/jev-typed-decisions.md (aegis-sfg5vb). This module is the
ONLY place camayoc talks to Jev. It does three things and refuses to do more:

1. Builds a request in Jev's shape: one `state`, a map of named questions of
   type `noul` (yes/no -> probability), `choice` (<=255 options -> winner +
   probability per option + confidence) or `score` (2-10 ordered levels).
2. Sends it with the bearer key from `TYPESAFE_API_KEY` and returns the raw
   answers, unmodified, plus the request that produced them — a verdict that
   cannot show its question is not a verdict.
3. Fails LOUD. No key -> `JevUnavailable`, never a silent fallback: a caller
   that wants a lexical answer asks the lexical scorer; the label must never
   lie (the same rule `competency.py` and `settled_decisions.py` already obey).

Three Jev properties every caller must respect (measured from public docs,
2026-09-20, not from use):
  * it CANNOT ABSTAIN — a `choice` always picks; give it a "none of these"
    option and read the confidence before acting;
  * it gives NO RATIONALE — record the state and criteria verbatim;
  * long, noisy state degrades it — callers assemble minimal state.

Every answer is a model judgment. Anything written back to the graph from it
carries `aegis:sourceKind "inferred"` and lands in the quarantine plane. Jev
never promotes.

Usage (ad hoc probe; `--dry-run` prints the request and sends nothing):
    export TYPESAFE_API_KEY=$(cd ~/workspace/goldblum && just infisical get TYPESAFE_API_KEY)
    python3 scripts/jev.py noul --state "Ticket: my card was charged twice" \\
        --ask "Does this message request a refund?"
    python3 scripts/jev.py choice --state "..." --ask "Which team handles this?" \\
        --option billing="Payments, refunds, invoices" --option it="Access, devices"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Callable

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
#: Documented limits (docs.typesafe.ai/api, read 2026-09-20).
MAX_CHOICE_OPTIONS = 255
SCORE_LEVELS = (2, 10)
#: The option id this module reserves so a `choice` can say "nothing fits".
NONE_OPTION = "none-of-these"

Transport = Callable[[dict, str], dict]


class JevError(RuntimeError):
    """The API answered with an error we can name."""


class JevUnavailable(JevError):
    """No key, or the service refused us. Callers must NOT fall back silently."""


def _default_transport(body: dict, key: str) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        ENDPOINT, data=data, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "camayoc-jev/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")[:500]
        if exc.code == 401:
            raise JevUnavailable("401: the TYPESAFE_API_KEY was refused") from exc
        if exc.code == 422:
            raise JevError(f"422: request rejected by validation: {text}") from exc
        if exc.code in (429, 529):
            raise JevUnavailable(f"{exc.code}: rate-limited/overloaded — retry with backoff") from exc
        raise JevError(f"HTTP {exc.code}: {text}") from exc


class JevClient:
    """One state in, typed answers out. `transport` is injectable for tests."""

    def __init__(self, api_key: str | None = None, transport: Transport | None = None,
                 model: str = MODEL):
        self.api_key = api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", "")
        self.transport = transport or _default_transport
        self.model = model
        if not self.api_key and transport is None:
            raise JevUnavailable(
                "TYPESAFE_API_KEY is not set. Put the key in Infisical as TYPESAFE_API_KEY and "
                "export it: TYPESAFE_API_KEY=$(cd ~/workspace/goldblum && just infisical get TYPESAFE_API_KEY). "
                "There is no silent fallback; ask the lexical scorer if that is what you want."
            )

    # -- request builders -------------------------------------------------
    @staticmethod
    def noul_q(instructions: str, true: str | None = None, false: str | None = None) -> dict:
        q: dict = {"type": "noul", "instructions": instructions}
        if true or false:
            q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v}
        return q

    @staticmethod
    def choice_q(instructions: str, criteria: dict[str, str], none_text: str | None = None) -> dict:
        opts = dict(criteria)
        if none_text is not None:
            opts[NONE_OPTION] = none_text
        if not 1 <= len(opts) <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"choice needs 1..{MAX_CHOICE_OPTIONS} options, got {len(opts)}")
        return {"type": "choice", "instructions": instructions, "criteria": opts}

    @staticmethod
    def score_q(instructions: str, levels: list[str]) -> dict:
        lo, hi = SCORE_LEVELS
        if not lo <= len(levels) <= hi:
            raise ValueError(f"score needs {lo}..{hi} ordered levels, got {len(levels)}")
        return {"type": "score", "instructions": instructions, "criteria": list(levels)}

    # -- the call ------------------------------------------------------------
    def ask(self, state, questions: dict[str, dict]) -> dict:
        """POST one state with named questions. Returns
        {"request": <body>, "response": <raw>, "answers": {...}, "usage": {...}}."""
        body = {"state": state, "model": self.model, "questions": questions}
        raw = self.transport(body, self.api_key)
        if not isinstance(raw, dict) or "answers" not in raw:
            raise JevError(f"unexpected response shape: {str(raw)[:200]}")
        return {"request": body, "response": raw, "answers": raw["answers"],
                "usage": raw.get("usage", {}), "model": raw.get("model", self.model)}

    def choice(self, state, instructions: str, criteria: dict[str, str],
               none_text: str | None = None, qid: str = "q") -> dict:
        out = self.ask(state, {qid: self.choice_q(instructions, criteria, none_text)})
        a = out["answers"][qid]
        return {**out, "choice": a.get("choice"), "probabilities": a.get("probabilities", {}),
                "confidence": a.get("confidence")}

    def noul(self, state, instructions: str, qid: str = "q", **criteria) -> dict:
        out = self.ask(state, {qid: self.noul_q(instructions, **criteria)})
        return {**out, "noul": out["answers"][qid].get("noul")}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="kind", required=True)
    for kind in ("noul", "choice"):
        p = sub.add_parser(kind)
        p.add_argument("--state", required=True, help="the text/JSON Jev judges")
        p.add_argument("--ask", required=True, help="the question (instructions)")
        p.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
        if kind == "choice":
            p.add_argument("--option", action="append", default=[], metavar="ID=TEXT")
            p.add_argument("--none", default="None of these fit", help="text for the none-of-these option ('' to omit)")
    a = ap.parse_args(argv)
    if a.kind == "choice":
        crit = dict(o.split("=", 1) for o in a.option)
        q = JevClient.choice_q(a.ask, crit, a.none or None)
    else:
        q = JevClient.noul_q(a.ask)
    body = {"state": a.state, "model": MODEL, "questions": {"q": q}}
    if a.dry_run:
        print(json.dumps(body, indent=2)); return 0
    try:
        out = JevClient().ask(a.state, {"q": q})
    except JevError as exc:
        print(f"jev: {exc}", file=sys.stderr); return 2
    print(json.dumps({"answers": out["answers"], "usage": out["usage"], "model": out["model"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
