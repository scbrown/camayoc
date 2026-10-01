"""A minimal triple store for the read adapters' tests.

It answers exactly the query shapes the adapters may send: one bound triple
pattern, or a UNION of single patterns (the quechua dual-read, aegis-9dpcta).
Anything with a join (" . " inside a pattern) is refused, because the served
quipu 408s joins live.

Triples are (subject, predicate, object) with LOCAL names. A predicate `name` is
the legacy aegis: term and `q:name` is its quechua twin; `a` is rdf:type, whose
object is a class written the same way (`WorkItem` or `q:WorkItem`). Instance
IRIs are always aegis:, because only terms move in the transition.
"""

from __future__ import annotations

import json
import re

TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


class TripleStore:
    def __init__(self, triples, legacy_ns: str, quechua_ns: str, iri_objects=frozenset()):
        self.t = triples
        self.a = legacy_ns
        self.q = quechua_ns
        # Predicates (by base name) whose objects are instance IRIs, so a
        # bare local name is returned as aegis:<name>, as quipu prefixes it.
        self.iri_objects = frozenset(iri_objects) | {"a"}

    def _term(self, tok: str):
        if tok.startswith("?"):
            return ("var", tok[1:])
        if tok == "a" or tok == f"<{TYPE}>":
            return ("pred", "a")
        if tok.startswith(f"<{self.q}"):
            return ("iri", "q:" + tok[len(self.q) + 1:-1])
        if tok.startswith(f"<{self.a}"):
            return ("iri", tok[len(self.a) + 1:-1])
        raise AssertionError(f"foreign IRI in a query: {tok}")

    def _out(self, value: str, iri: bool) -> str:
        if not iri or value.startswith(("aegis:", "http")):
            return value
        if value.startswith("q:"):
            return self.q + value[2:]
        return "aegis:" + value

    def select(self, query: str) -> list[dict]:
        body = query[query.index("{") + 1:query.rindex("}")].strip()
        branches = re.findall(r"\{ ([^{}]*) \}", body) if " UNION " in body else [body]
        if not branches:
            raise AssertionError(f"unparsed query {query}")
        rows, seen = [], set()
        for branch in branches:
            if " . " in branch:
                raise AssertionError(f"multi-pattern query (quipu 408s joins live): {query}")
            parts = branch.split(" ")
            if len(parts) != 3:
                raise AssertionError(f"not a single triple pattern: {branch!r}")
            s, p, o = (self._term(x) for x in parts)
            pred = "a" if p == ("pred", "a") else p[1]
            base = pred[2:] if pred.startswith("q:") else pred
            for ts, tp, to in self.t:
                if tp != pred:
                    continue
                if s[0] == "iri" and ts != s[1]:
                    continue
                if o[0] == "iri" and to not in (o[1], "aegis:" + o[1]):
                    continue
                row = {}
                if s[0] == "var":
                    row[s[1]] = self._out(ts, True)
                if o[0] == "var":
                    row[o[1]] = self._out(to, base in self.iri_objects)
                key = json.dumps(row, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
        return rows
