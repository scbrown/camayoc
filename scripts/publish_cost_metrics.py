#!/usr/bin/env python3
"""Publish st's rendered cost result through the existing Camayoc transport."""
import argparse
from pathlib import Path
import sys
from camayoc_metrics import push


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exposition', type=Path)
    parser.add_argument('--rig', required=True)
    args = parser.parse_args()
    ok, why = push('st_bead_cost', args.exposition.read_text(), grouping={'rig': args.rig})
    print(why, file=sys.stderr)
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
