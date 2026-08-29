from __future__ import annotations

import hashlib, importlib.util, json, shutil, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("certify_pack", ROOT / "scripts/certify_pack.py")
certify_pack = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules["certify_pack"] = certify_pack
SPEC.loader.exec_module(certify_pack)
HASH = "sha256:" + "a" * 64


def public_hex(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def signed_claim(manifest, report_hash, **changes):
    publisher, certifier = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    values = dict(
        bundle_iri="https://example.invalid/bundle",
        publisher_claim_iri="https://example.invalid/bundle/publisher",
        certifier_claim_iri="https://example.invalid/bundle/certifier",
        publisher_key_iri="https://example.invalid/key/publisher",
        certifier_key_iri="https://example.invalid/key/certifier",
        publisher_public_key=public_hex(publisher), certifier_public_key=public_hex(certifier),
        publisher_signature="", certifier_signature="", shapes_version="camayoc-rml@1",
        shacl_report_hash=report_hash, provenance_manifest_iri="https://example.invalid/provenance",
        source_uri="https://example.invalid/packs/crew.qpack.db", access_via="rest",
        freshness="snapshot(v1)", verified_by=HASH,
    )
    values.update(changes)
    claim = certify_pack.Certification(**values)
    values["publisher_signature"] = publisher.sign(certify_pack.publisher_message(manifest, claim)).hex()
    values["certifier_signature"] = certifier.sign(certify_pack.certifier_message(manifest, claim)).hex()
    return certify_pack.Certification(**values)


def make_pack(path, extra="safe public data"):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE pack_manifest (id INTEGER, pack_format TEXT, name TEXT, version TEXT, content_hash TEXT, source_graph TEXT)")
        conn.execute("INSERT INTO pack_manifest VALUES (1, '1', 'crew', '1.0.0', ?, 'urn:crew')", (HASH,))
        conn.execute("CREATE TABLE payload (value TEXT)")
        conn.execute("INSERT INTO payload VALUES (?)", (extra,))


class CertificationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = certify_pack.PackManifest("1", "crew", "1.0.0", HASH, "urn:crew")
        self.report_bytes = b'{"conforms":true}\n'
        self.report_hash = "sha256:" + hashlib.sha256(self.report_bytes).hexdigest()

    def test_real_static_and_window_e2e_survive_relocation(self):
        for window in (False, True):
            with self.subTest(window=window), tempfile.TemporaryDirectory() as directory:
                root, pack = Path(directory), Path(directory) / "crew.qpack.db"
                report = root / "report.json"
                make_pack(pack); report.write_bytes(self.report_bytes)
                changes = ({"freshness": "frozen(window-42)", "shuttle_derived": True,
                            "frozen_window_iri": "https://example.invalid/window/42"} if window else {})
                claim = signed_claim(self.manifest, self.report_hash, **changes)
                manifest, turtle = certify_pack.certify_existing_pack(pack, report, claim)
                relocated = certify_pack.publish_pack(pack, manifest, root / "published")
                self.assertEqual(manifest.content_hash, certify_pack.read_manifest(relocated).content_hash)
                self.assertIn(manifest.content_hash.removeprefix("sha256:"), str(relocated))
                self.assertIn("aegis:scrubCheckPass true", turtle)
                self.assertEqual(window, "aegis:frozenWindow" in turtle)

    def test_tampered_and_same_key_claims_are_refused(self):
        claim = signed_claim(self.manifest, self.report_hash)
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "invalid publisher"):
            certify_pack.build_envelope(self.manifest, certify_pack.Certification(**{**claim.__dict__, "publisher_signature": "00" * 64}))
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "key IRIs must be distinct"):
            certify_pack.build_envelope(self.manifest, certify_pack.Certification(**{**claim.__dict__, "certifier_key_iri": claim.publisher_key_iri}))

    def test_scrub_refuses_private_artifact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / "bad.qpack.db"; make_pack(pack, "database.example.lan")
            with self.assertRaisesRegex(certify_pack.PackCertificationError, "private hostname"):
                certify_pack.scrub_pack(pack)

    def test_shacl_report_is_computed_and_must_conform(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"; report.write_bytes(self.report_bytes)
            self.assertEqual(self.report_hash, certify_pack.verify_shacl_report(report))
            report.write_text(json.dumps({"conforms": False}))
            with self.assertRaisesRegex(certify_pack.PackCertificationError, "conforms=true"):
                certify_pack.verify_shacl_report(report)

    def test_shuttle_pack_requires_window(self):
        claim = signed_claim(self.manifest, self.report_hash, shuttle_derived=True)
        with self.assertRaisesRegex(certify_pack.PackCertificationError, "requires a frozen-window"):
            certify_pack.build_envelope(self.manifest, claim)

    @unittest.skipUnless(shutil.which("quipu"), "quipu CLI is required for SHACL integration")
    def test_static_and_window_envelopes_conform_and_bad_evidence_refuses(self):
        shapes = ROOT / "tests/fixtures/certified-pack.shapes.ttl"
        registrations = """
<https://example.invalid/key/publisher> a aegis:VerifierRegistration .
<https://example.invalid/key/certifier> a aegis:VerifierRegistration .
"""
        for window in (False, True):
            changes = ({"freshness": "frozen(window-42)", "shuttle_derived": True,
                        "frozen_window_iri": "https://example.invalid/window/42"} if window else {})
            turtle = certify_pack.build_envelope(
                self.manifest, signed_claim(self.manifest, self.report_hash, **changes)
            ) + registrations
            with tempfile.TemporaryDirectory() as directory:
                data = Path(directory) / "envelope.ttl"; data.write_text(turtle)
                good = subprocess.run(
                    ["quipu", "validate", "--shapes", str(shapes), "--data", str(data)],
                    capture_output=True, text=True,
                )
                self.assertEqual(0, good.returncode, good.stdout + good.stderr)
                for broken in (
                    turtle.replace('aegis:attestationSignature "', 'aegis:unusedSignature "', 1),
                    turtle.replace("aegis:scrubCheckPass true", "aegis:scrubCheckPass false"),
                ):
                    data.write_text(broken)
                    bad = subprocess.run(
                        ["quipu", "validate", "--shapes", str(shapes), "--data", str(data)],
                        capture_output=True, text=True,
                    )
                    self.assertNotEqual(0, bad.returncode, bad.stdout + bad.stderr)


class QuipuInvocationTests(unittest.TestCase):
    def test_pack_then_verify_are_argument_arrays(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "crew.qpack.db"
            def runner(command, **_kwargs):
                calls.append(command)
                if "--verify" not in command: make_pack(out)
                return subprocess.CompletedProcess(command, 0, "ok", "")
            manifest = certify_pack.run_quipu_pack("quipu", Path("source.db"), "urn:crew", out, "crew", "1.0.0", ["governance"], ["camayoc_query"], runner)
        self.assertEqual(HASH, manifest.content_hash)
        self.assertEqual(["quipu", "pack", "--verify", str(out)], calls[1])
        self.assertNotIsInstance(calls[0], str)

    def test_s3_publication_uses_digest_key_and_verifies_retained_metadata(self):
        class S3:
            def put_object(self, **request):
                self.request = request
                self.size = len(request["Body"].read())

            def head_object(self, **_request):
                return {
                    "ContentLength": self.size,
                    "Metadata": self.request["Metadata"],
                }

        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / "crew.qpack.db"; make_pack(pack)
            manifest = certify_pack.read_manifest(pack)
            client = S3()
            uri = certify_pack.publish_pack_s3(pack, manifest, "knowledge", client=client)
        self.assertEqual(
            f"s3://knowledge/sha256/{HASH.removeprefix('sha256:')}.qpack.db", uri
        )
        self.assertEqual(HASH, client.request["Metadata"]["canonical-graph-hash"])


if __name__ == "__main__": unittest.main()
