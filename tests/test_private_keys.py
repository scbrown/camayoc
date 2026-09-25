"""Boundary controls use ephemeral keys, never committed fixtures."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SPEC = importlib.util.spec_from_file_location('private_keys', Path(__file__).resolve().parents[1] / 'scripts/check_private_keys.py')
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class PrivateKeyTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()

    def der(self, encryption=None):
        return self.key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                      encryption or serialization.NoEncryption())

    def test_binary_private_key_is_refused_under_an_unrelated_name(self):
        self.assertEqual(GUARD.private_reason('notes.bin', self.der()), 'DER private key')

    def test_encrypted_der_is_still_private_material(self):
        self.assertEqual(GUARD.private_reason('notes.bin', self.der(serialization.BestAvailableEncryption(b'ephemeral-test'))),
                         'encrypted DER private key')

    def test_runtime_pk8_paths_are_refused_even_if_invalid(self):
        for name in ['.quipu/verifier.pk8', 'nested/.quipu/new.pk8', 'OTHER.PK8']:
            with self.subTest(name=name): self.assertIsNotNone(GUARD.private_reason(name, b'not-a-valid-key'))

    def test_private_pem_markers_are_refused(self):
        for kind in ['PRIVATE KEY', 'RSA PRIVATE KEY', 'OPENSSH PRIVATE KEY', 'ENCRYPTED PRIVATE KEY']:
            marker = ('-----BEGIN ' + kind + '-----').encode()
            with self.subTest(kind=kind): self.assertIsNotNone(GUARD.private_reason('notes.txt', marker))

    def test_public_key_and_benign_bytes_pass(self):
        public = self.key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        for content in [public, b'Public documentation.\n', b'0 not DER']:
            self.assertIsNone(GUARD.private_reason('public.der', content))

    def test_actual_index_not_worktree_is_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
            candidate = root / 'unrelated.bin'
            candidate.write_bytes(self.der())
            subprocess.run(['git', '-C', str(root), 'add', 'unrelated.bin'], check=True)
            candidate.write_text('Benign worktree hiding a staged key.\n')
            self.assertEqual(GUARD.scan(root), [('unrelated.bin', 'DER private key')])
            subprocess.run(['git', '-C', str(root), 'add', 'unrelated.bin'], check=True)
            self.assertEqual(GUARD.scan(root), [])

    def test_ignore_rule_covers_regenerated_runtime_key(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['git', '-C', str(root), 'check-ignore', '--no-index', '.quipu/regenerated.pk8'], capture_output=True)
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
