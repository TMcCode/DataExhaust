#!/usr/bin/env python3
"""Smoke-test MLP_GCS_SNAPSHOT_URI: dotenv + download + bundle shape."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main() -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("Install python-dotenv (requirements.txt).", file=sys.stderr)
        return 1
    load_dotenv(_REPO / ".env", override=True)

    uri = (os.environ.get("MLP_GCS_SNAPSHOT_URI") or "").strip()
    if not uri:
        print("Set MLP_GCS_SNAPSHOT_URI in .env or the environment.", file=sys.stderr)
        return 1
    print("URI:", uri)

    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if key:
        print("Credentials:", key)
    else:
        print("(No GOOGLE_*_CREDENTIALS in env — using gcloud ADC if configured.)")

    import mlp_gcs_snapshot

    b = mlp_gcs_snapshot.download_bundle_gzip_pickle(uri)
    if b is None:
        print("FAIL: download returned None (blob missing, IAM, or unpickle/shape).", file=sys.stderr)
        return 2
    print("OK: top-level keys:", sorted(b.keys()))
    ms = b.get("mlp_sheets")
    if isinstance(ms, dict):
        print("OK: mlp_sheets keys:", sorted(ms.keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
