from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("certify_pack", ROOT / "scripts" / "certify_pack.py")
certify_pack = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["certify_pack"] = certify_pack
SPEC.loader.exec_module(certify_pack)


HASH = "sha256:" + "a" * 64
REPORT_HASH = "sha256:" + "b" * 64


def certification(**changes):
    values = {
        "bundle_iri": "https://example.invalid/bundle",
        "publisher_claim_iri": "https://example.invalid/bundle/publisher",
        "certifier_claim_iri": "https://example.invalid/bundle/certifier",
        "publisher_key_iri": "https://example.invalid/key/publisher",
        "certifier_key_iri": "https://example.invalid/key/certifier",
        "publisher_signature": "cosign:publisher",
        "certifier_signature": "cosign:certifier",
        "shapes_version": "camayoc-rml@1",
        "shacl_report_hash": REPORT_HASH,
        "provenance_manifest_iri": "https://example.invalid/provenance",
        "source_uri": "https://example.invalid/packs/crew.qpack.db",
        "access_via": "rest",
        "freshness": "frozen(window-42)",
        "verified_by": HASH,
    }
    values.update(changes)
    return certify_pack.Certification(**values)


class ManifestTests(unittest.TestCase):
    def test_reads_the_one_authoritative_manifest_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.qpack.db"
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE pack_manifest (id INTEGER, pack_format TEXT, name TEXT, "
                    "version TEXT, content_hash TEXT, source_graph TEXT)"
                )
                conn.execute(
                    "INSERT INTO pack_manifest VALUES (1, '1', 'crew', '1.0.0', ?, 'urn:crew')",
                    (HASH,),
                )
            manifest = certify_pack.read_manifest(path)
        self.assertEqual(HASH, manifest.content_hash)
        self.assertEqual("crew", manifest.name)

    def test_refuses_a_noncanonical_hash(self):
        manifest = certify_pack.PackManifest("1", "crew", "1", "sha256:short", "urn:crew")
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "64 lowercase hex"):
            certify_pack.build_envelope(manifest, certification())


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = certify_pack.PackManifest("1", "crew", "1.0.0", HASH, "urn:crew")

    def test_static_pack_emits_two_distinct_claims_without_a_fake_window(self):
        turtle = certify_pack.build_envelope(self.manifest, certification(freshness="snapshot(v1)"))
        self.assertIn("aegis:publisherAttestation <https://example.invalid/bundle/publisher>", turtle)
        self.assertIn("aegis:certificationSeal <https://example.invalid/bundle/certifier>", turtle)
        self.assertIn(f'aegis:canonicalGraphHash "{HASH}"', turtle)
        self.assertIn("aegis:scrubCheckPass true", turtle)
        self.assertNotIn("aegis:frozenWindow", turtle)

    def test_shuttle_pack_requires_and_emits_its_frozen_window(self):
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "requires a frozen-window"):
            certify_pack.build_envelope(self.manifest, certification(shuttle_derived=True))
        turtle = certify_pack.build_envelope(
            self.manifest,
            certification(
                shuttle_derived=True,
                frozen_window_iri="https://example.invalid/window/42",
            ),
        )
        self.assertIn("aegis:frozenWindow <https://example.invalid/window/42>", turtle)

    def test_pointer_contract_refuses_unknown_access_and_freshness(self):
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "unsupported access_via"):
            certify_pack.build_envelope(self.manifest, certification(access_via="browser maybe"))
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "invalid freshness"):
            certify_pack.build_envelope(self.manifest, certification(freshness="recent"))


class QuipuInvocationTests(unittest.TestCase):
    def test_pack_then_verify_are_argument_arrays_and_manifest_is_read_after(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "crew.qpack.db"

            def runner(command, **_kwargs):
                calls.append(command)
                if "--verify" not in command:
                    with sqlite3.connect(out) as conn:
                        conn.execute(
                            "CREATE TABLE pack_manifest (id INTEGER, pack_format TEXT, name TEXT, "
                            "version TEXT, content_hash TEXT, source_graph TEXT)"
                        )
                        conn.execute(
                            "INSERT INTO pack_manifest VALUES (1, '1', 'crew', '1.0.0', ?, 'urn:crew')",
                            (HASH,),
                        )
                return subprocess.CompletedProcess(command, 0, "ok", "")

            manifest = certify_pack.run_quipu_pack(
                "quipu",
                Path("source.db"),
                "urn:crew",
                out,
                "crew",
                "1.0.0",
                ["governance"],
                ["camayoc_query"],
                runner,
            )
        self.assertEqual(HASH, manifest.content_hash)
        self.assertEqual("quipu", calls[0][0])
        self.assertEqual(["quipu", "pack", "--verify", str(out)], calls[1])
        self.assertNotIsInstance(calls[0], str)


if __name__ == "__main__":
    unittest.main()
