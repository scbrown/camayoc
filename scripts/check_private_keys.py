#!/usr/bin/env python3
"""Refuse private signing material in the Git index, including binary DER.

# arming: ci; .github/workflows/ci.yml, plus optional pre-commit hook.
Only filenames and reasons are printed; key material never enters diagnostics.
"""
import re
import subprocess
import sys
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_der_private_key

PEM = re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----')


def private_reason(name, content):
    if name.lower().endswith('.pk8'):
        return 'private signing-key path'
    if PEM.search(content):
        return 'private-key PEM marker'
    if content.startswith(b'\x30'):
        try:
            load_der_private_key(content, password=None)
        except ValueError:
            return None  # Not a DER private key (e.g. a public key/certificate).
        except TypeError:
            return 'encrypted DER private key'
        except UnsupportedAlgorithm:
            return 'unsupported DER key material'
        else:
            return 'DER private key'
    return None


def scan(root):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)
    entries = git('ls-files', '--stage', '-z').split(b'\0')
    findings = []
    for entry in entries:
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        mode, oid, stage = metadata.split()
        name = raw_name.decode('utf-8', errors='surrogateescape')
        if stage != b'0':
            findings.append((name, 'unmerged index cannot be certified'))
            continue
        if mode == b'160000':
            continue  # Submodule contents belong to their own repository gate.
        # Read the INDEX blob, not the worktree: overwriting a staged key with
        # benign bytes must not produce a false pass before committing it.
        content = git('cat-file', 'blob', oid.decode('ascii'))
        reason = private_reason(name, content)
        if reason:
            findings.append((name, reason))
    return findings


def main():
    try:
        findings = scan(Path.cwd())
    except (OSError, subprocess.SubprocessError, ValueError):
        print('REFUSED: could not inspect the complete Git index', file=sys.stderr)
        return 2
    for name, reason in findings:
        print(f'REFUSED: {name!r}: {reason}', file=sys.stderr)
    if findings:
        return 1
    print('PASS: no private signing material in the Git index')
    return 0


if __name__ == '__main__':
    sys.exit(main())
