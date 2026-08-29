#!/usr/bin/env python3
"""Produce a Quipu pack and its Camayoc certification envelope."""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ACCESS_VIA = {"mcp", "rest", "sparql-federated", "file", "promql"}
FRESHNESS_RE = re.compile(r"^(live|snapshot\([^()]+\)|frozen\([^()]+\))$")


class PackCertificationError(ValueError):
    """A pack or certification input cannot satisfy the governed contract."""


@dataclass(frozen=True)
class PackManifest:
    pack_format: str
    name: str
    version: str
    content_hash: str
    source_graph: str


@dataclass(frozen=True)
class Certification:
    bundle_iri: str
    publisher_claim_iri: str
    certifier_claim_iri: str
    publisher_key_iri: str
    certifier_key_iri: str
    publisher_signature: str
    certifier_signature: str
    shapes_version: str
    shacl_report_hash: str
    provenance_manifest_iri: str
    source_uri: str
    access_via: str
    freshness: str
    verified_by: str
    frozen_window_iri: str | None = None
    shuttle_derived: bool = False


def _iri(value: str) -> str:
    if not value or any(char.isspace() or char in '<>"{}|' for char in value):
        raise PackCertificationError(f"invalid absolute IRI: {value!r}")
    if ":" not in value:
        raise PackCertificationError(f"IRI has no scheme: {value!r}")
    return f"<{value}>"


def _literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _require_hash(value: str, field: str) -> None:
    if not HASH_RE.fullmatch(value):
        raise PackCertificationError(f"{field} must be sha256:<64 lowercase hex>")


def read_manifest(pack_path: Path) -> PackManifest:
    """Read the one authoritative manifest row from a `.qpack.db`."""
    try:
        with sqlite3.connect(f"file:{pack_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT pack_format, name, version, content_hash, source_graph "
                "FROM pack_manifest ORDER BY id"
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        raise PackCertificationError(f"cannot read pack manifest: {exc}") from exc
    if len(rows) != 1:
        raise PackCertificationError(f"pack_manifest must contain exactly one row, found {len(rows)}")
    manifest = PackManifest(*rows[0])
    _require_hash(manifest.content_hash, "pack_manifest.content_hash")
    return manifest


def build_envelope(manifest: PackManifest, certification: Certification) -> str:
    """Render deterministic Turtle for the governed two-claim envelope."""
    _require_hash(manifest.content_hash, "pack_manifest.content_hash")
    _require_hash(certification.shacl_report_hash, "shacl_report_hash")
    if certification.access_via not in ACCESS_VIA:
        raise PackCertificationError(f"unsupported access_via: {certification.access_via}")
    if not FRESHNESS_RE.fullmatch(certification.freshness):
        raise PackCertificationError(f"invalid freshness: {certification.freshness}")
    if certification.shuttle_derived and not certification.frozen_window_iri:
        raise PackCertificationError("a Shuttle-derived bundle requires a frozen-window IRI")

    bundle = _iri(certification.bundle_iri)
    publisher = _iri(certification.publisher_claim_iri)
    certifier = _iri(certification.certifier_claim_iri)
    publisher_key = _iri(certification.publisher_key_iri)
    certifier_key = _iri(certification.certifier_key_iri)
    provenance = _iri(certification.provenance_manifest_iri)
    window = (
        f" ;\n    aegis:frozenWindow {_iri(certification.frozen_window_iri)}"
        if certification.frozen_window_iri
        else ""
    )

    return f"""@prefix aegis: <http://aegis.gastown.local/ontology/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

{bundle} a aegis:CertifiedShareBundle ;
    rdfs:label {_literal(manifest.name + '.qpack.db')} ;
    aegis:canonicalGraphHash {_literal(manifest.content_hash)} ;
    aegis:shapesBundleVersion {_literal(certification.shapes_version)} ;
    aegis:provenanceManifest {provenance} ;
    aegis:publisherAttestation {publisher} ;
    aegis:certificationSeal {certifier} ;
    aegis:source_uri {_literal(certification.source_uri)} ;
    aegis:access_via {_literal(certification.access_via)} ;
    aegis:freshness {_literal(certification.freshness)} ;
    aegis:verified_by {_literal(certification.verified_by)} .

{publisher} a aegis:PublisherAttestation ;
    rdfs:label "publisher attestation" ;
    aegis:attestsBundle {bundle} ;
    aegis:signingKey {publisher_key} ;
    aegis:attestationSignature {_literal(certification.publisher_signature)} .

{certifier} a aegis:KnowledgeCertificationSeal ;
    rdfs:label "knowledge certification seal" ;
    aegis:certifiesBundle {bundle} ;
    aegis:canonicalGraphHash {_literal(manifest.content_hash)} ;
    aegis:shapesBundleVersion {_literal(certification.shapes_version)} ;
    aegis:shaclReportHash {_literal(certification.shacl_report_hash)} ;
    aegis:scrubCheckPass true ;
    aegis:provenanceManifest {provenance} ;
    aegis:signingKey {certifier_key} ;
    aegis:attestationSignature {_literal(certification.certifier_signature)}{window} .
"""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_quipu_pack(
    quipu_bin: str,
    db_path: Path,
    graph_iri: str,
    out_path: Path,
    name: str,
    version: str,
    shapes: Sequence[str],
    queries: Sequence[str],
    runner: Runner = subprocess.run,
) -> PackManifest:
    """Build then verify one pack, using argument arrays and no shell."""
    command = [
        quipu_bin,
        "pack",
        graph_iri,
        "--out",
        str(out_path),
        "--name",
        name,
        "--version",
        version,
        "--db",
        str(db_path),
    ]
    for shape in shapes:
        command.extend(["--shapes", shape])
    for query in queries:
        command.extend(["--queries", query])
    built = runner(command, check=False, capture_output=True, text=True)
    if built.returncode != 0:
        raise PackCertificationError(f"quipu pack failed: {built.stderr.strip()}")
    verified = runner(
        [quipu_bin, "pack", "--verify", str(out_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if verified.returncode != 0:
        raise PackCertificationError(f"quipu pack verification failed: {verified.stderr.strip()}")
    return read_manifest(out_path)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("graph_iri")
    result.add_argument("--db", type=Path, required=True)
    result.add_argument("--out", type=Path, required=True)
    result.add_argument("--name", required=True)
    result.add_argument("--version", required=True)
    result.add_argument("--shape", action="append", default=[])
    result.add_argument("--query", action="append", default=[])
    result.add_argument("--quipu-bin", default="quipu")
    result.add_argument("--envelope-out", type=Path)
    for field in [
        "bundle-iri",
        "publisher-claim-iri",
        "certifier-claim-iri",
        "publisher-key-iri",
        "certifier-key-iri",
        "publisher-signature",
        "certifier-signature",
        "shapes-version",
        "shacl-report-hash",
        "provenance-manifest-iri",
        "source-uri",
        "access-via",
        "freshness",
        "verified-by",
    ]:
        result.add_argument(f"--{field}", required=True)
    result.add_argument("--frozen-window-iri")
    result.add_argument("--shuttle-derived", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = run_quipu_pack(
            args.quipu_bin,
            args.db,
            args.graph_iri,
            args.out,
            args.name,
            args.version,
            args.shape,
            args.query,
        )
        certification = Certification(
            bundle_iri=args.bundle_iri,
            publisher_claim_iri=args.publisher_claim_iri,
            certifier_claim_iri=args.certifier_claim_iri,
            publisher_key_iri=args.publisher_key_iri,
            certifier_key_iri=args.certifier_key_iri,
            publisher_signature=args.publisher_signature,
            certifier_signature=args.certifier_signature,
            shapes_version=args.shapes_version,
            shacl_report_hash=args.shacl_report_hash,
            provenance_manifest_iri=args.provenance_manifest_iri,
            source_uri=args.source_uri,
            access_via=args.access_via,
            freshness=args.freshness,
            verified_by=args.verified_by,
            frozen_window_iri=args.frozen_window_iri,
            shuttle_derived=args.shuttle_derived,
        )
        envelope = build_envelope(manifest, certification)
        envelope_path = args.envelope_out or Path(f"{args.out}.cert.ttl")
        envelope_path.write_text(envelope)
    except PackCertificationError as exc:
        print(f"certify-pack refused: {exc}", file=sys.stderr)
        return 2
    print(f"certified {args.out}: {manifest.content_hash} -> {envelope_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
