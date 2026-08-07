#!/usr/bin/env python3
"""Parse Prometheus alert rules into a reconciled Camayoc catalogue snapshot."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


BASE = "http://aegis.gastown.local/ontology/"
QUIPU = "http://quipu.dev/ontology/"
METRIC_TOKEN = re.compile(r"(?<![A-Za-z0-9_:])([A-Za-z_:][A-Za-z0-9_:]*)")
COMPARISON = re.compile(r"(?:>=|<=|==|!=|>|<)\s*(-?(?:\d+(?:\.\d*)?|\.\d+))")
RESERVED = {"absent", "and", "bool", "by", "group_left", "group_right", "ignoring", "label_replace", "on", "or", "sum", "time", "unless", "vector"}


@dataclass(frozen=True)
class Rule:
    alert: str
    expression: str
    window: str
    keeper: str
    service: str
    severity: str
    meaning: str
    source: str
    declared_at: str
    content_hash: str

    @property
    def slug(self) -> str:
        # Case and punctuation differences can collapse to the same readable
        # slug (measured in the live burn-rate rules). Keep the readable stem
        # but anchor identity to the exact alert name.
        suffix = hashlib.sha256(self.alert.encode()).hexdigest()[:8]
        return f"{slug(self.alert)}-{suffix}"

    @property
    def metric_name(self) -> str:
        for token in METRIC_TOKEN.findall(self.expression):
            if token not in RESERVED and not token.startswith("http"):
                return token
        return self.alert

    @property
    def threshold(self) -> str:
        match = COMPARISON.search(self.expression)
        return match.group(0) if match else self.expression


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unnamed"


def turtle_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize_template(text: str) -> str:
    # Prometheus rule templates are commonly wrapped in Jinja control lines
    # (`{% raw -%}`, conditionals). The rules themselves remain YAML; control
    # lines are not catalogue facts and are removed before deterministic parse.
    return re.sub(r"^\s*\{%-?.*?-?%\}\s*$", "", text, flags=re.MULTILINE)


def source_timestamp(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path.parent), "log", "-1", "--format=%cI", "--", path.name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.UTC).isoformat().replace("+00:00", "Z")


def iter_rule_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and any(str(path).endswith(s) for s in (".yml", ".yaml", ".yml.j2", ".yaml.j2")):
            yield path


def parse_file(path: Path) -> list[Rule]:
    text = normalize_template(path.read_text(encoding="utf-8"))
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid rule YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        return []
    rules: list[Rule] = []
    for group in data["groups"]:
        if not isinstance(group, dict):
            continue
        for raw in group.get("rules") or []:
            if not isinstance(raw, dict) or "alert" not in raw or "expr" not in raw:
                continue
            labels = raw.get("labels") or {}
            annotations = raw.get("annotations") or {}
            canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            rules.append(
                Rule(
                    alert=str(raw["alert"]),
                    expression=str(raw["expr"]).strip(),
                    window=str(raw.get("for") or "instant"),
                    keeper=str(labels.get("keeper") or "unowned"),
                    service=str(labels.get("service") or "unspecified-service"),
                    severity=str(labels.get("severity") or "unspecified"),
                    meaning=str(annotations.get("description") or annotations.get("summary") or raw["alert"]),
                    source=str(path),
                    declared_at=source_timestamp(path),
                    content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
                )
            )
    return rules


def parse_rules(root: Path, strict: bool = False) -> list[Rule]:
    rules: list[Rule] = []
    errors: list[str] = []
    for path in iter_rule_files(root):
        try:
            rules.extend(parse_file(path))
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if strict and errors:
        raise ValueError("\n".join(errors))
    for error in errors:
        print(f"skip: {error}", file=sys.stderr)
    deduped = {rule.alert: rule for rule in rules}
    return [deduped[name] for name in sorted(deduped)]


def render_turtle(rules: list[Rule], endpoint: str | None) -> str:
    lines = [
        "@prefix aegis: <http://aegis.gastown.local/ontology/> .",
        "@prefix quipu: <http://quipu.dev/ontology/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
    ]
    params = json.dumps({"endpoint": endpoint} if endpoint else {}, sort_keys=True, separators=(",", ":"))
    for rule in rules:
        metric = f"aegis:metric-{rule.slug}"
        requirement = f"aegis:nfr-{rule.slug}"
        method = f"aegis:method-{rule.slug}"
        owner = f"aegis:{slug(rule.keeper)}"
        subject = f"aegis:service-{slug(rule.service)}"
        gate = f"aegis:alert-{rule.slug}"
        lines.extend(
            [
                f"{requirement} a aegis:NonFunctionalRequirement ;",
                f"    rdfs:label {turtle_string(rule.alert + ' requirement')} ;",
                '    aegis:sourceKind "declared" ;',
                f"    aegis:about {subject} ;",
                f"    aegis:threshold {turtle_string(rule.threshold)} ;",
                '    aegis:unit "PromQL expression result" ;',
                f"    aegis:measurementWindow {turtle_string(rule.window)} ;",
                f"    aegis:ownedBy {owner} ;",
                f"    aegis:createdAt {turtle_string(rule.declared_at)} .",
                "",
                f"{metric} a aegis:Metric ;",
                f"    rdfs:label {turtle_string(rule.alert)} ;",
                '    aegis:sourceKind "declared" ;',
                '    aegis:unit "PromQL expression result" ;',
                f"    aegis:meaning {turtle_string(rule.meaning)} ;",
                f"    aegis:metricName {turtle_string(rule.metric_name)} ;",
                f"    aegis:ownedBy {owner} ;",
                f"    aegis:probe {turtle_string(rule.expression)} ;",
                f"    aegis:measuresRequirement {requirement} ;",
                f"    aegis:gates {gate} ;",
                f"    quipu:derivedBy {method} ;",
                f"    aegis:contentHash {turtle_string(rule.content_hash)} .",
                "",
                f"{method} quipu:derivationSystem \"prometheus\" ;",
                f"    quipu:derivationQuery {turtle_string(rule.expression)} ;",
                f"    quipu:derivationParams {turtle_string(params)} .",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Prometheus rule file or directory")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--prometheus-endpoint", help="Endpoint stored as a method parameter; no default is invented")
    parser.add_argument("--strict", action="store_true", help="fail if any candidate YAML file cannot be parsed")
    args = parser.parse_args()
    rules = parse_rules(args.source, strict=args.strict)
    if not rules:
        print("no Prometheus alert rules found", file=sys.stderr)
        return 2
    output = render_turtle(rules, args.prometheus_endpoint)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)
    print(f"catalogued {len(rules)} alert-backed metrics", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
