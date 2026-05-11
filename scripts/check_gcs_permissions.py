#!/usr/bin/env python3
"""Probe GCS permissions on the bucket used for runtime CSVs / snapshots.

Tests four operations against ``gs://<bucket>/<prefix>/`` and prints which
succeed. Uses the service-account JSON pointed to by
``GOOGLE_APPLICATION_CREDENTIALS`` (falls back to ``data-exhaust-key.json``
next to the repo root).

Operations tested:
  1. LIST  — required to enumerate existing objects
  2. READ  — required for the dashboard to download the snapshot
  3. WRITE — required to upload the 8 runtime CSVs
  4. DELETE — required to clean up the temp probe object

Exit codes:
  0  all four operations succeeded (you have Storage Object Admin or equivalent)
  1  one or more operations failed (script prints which)
  2  environment / credential setup error
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Bucket + prefix to probe. Override with --uri at the CLI if you want to test elsewhere.
DEFAULT_BUCKET = "data-exhaust_cloudbuild"
DEFAULT_PREFIX = "source/csvs/"
DEFAULT_READ_OBJECT = "source/mlp_dashboard_bundle.pkl.gz"


def _load_dotenv_quiet() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO / ".env", override=True)
    except ImportError:
        pass


def _resolve_credentials() -> str | None:
    for var in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_SHEETS_CREDENTIALS"):
        v = os.environ.get(var)
        if v and Path(v).is_file():
            return v
    fallback = _REPO / "data-exhaust-key.json"
    if fallback.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(fallback)
        return str(fallback)
    return None


def main() -> int:
    _load_dotenv_quiet()

    cred_path = _resolve_credentials()
    if cred_path is None:
        print(
            "ERROR: No service-account key found. Set GOOGLE_APPLICATION_CREDENTIALS "
            "or place data-exhaust-key.json at the repo root.",
            file=sys.stderr,
        )
        return 2
    print(f"Using credentials: {cred_path}")

    try:
        from google.cloud import storage
    except ImportError:
        print("ERROR: google-cloud-storage is not installed.", file=sys.stderr)
        return 2

    bucket_name = DEFAULT_BUCKET
    prefix = DEFAULT_PREFIX
    read_obj = DEFAULT_READ_OBJECT

    print(f"Probing gs://{bucket_name}/{prefix} (read test: gs://{bucket_name}/{read_obj})")
    print("-" * 72)

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    results: dict[str, tuple[bool, str]] = {}

    # 1. LIST
    try:
        blobs = list(client.list_blobs(bucket_name, prefix="source/", max_results=5))
        results["LIST"] = (True, f"{len(blobs)} objects under source/ visible (showing up to 5)")
    except Exception as e:
        results["LIST"] = (False, f"{type(e).__name__}: {e}")

    # 2. READ — try the existing snapshot blob if present
    try:
        blob = bucket.blob(read_obj)
        if not blob.exists():
            results["READ"] = (False, f"object {read_obj!r} does not exist (cannot test read)")
        else:
            head = blob.download_as_bytes(start=0, end=15)
            results["READ"] = (True, f"downloaded {len(head)} bytes from {read_obj}")
    except Exception as e:
        results["READ"] = (False, f"{type(e).__name__}: {e}")

    # 3. WRITE — upload a tiny temp object
    probe_name = f"{prefix.rstrip('/')}/_permission_probe_{uuid.uuid4().hex[:8]}_{int(time.time())}.txt"
    probe_payload = b"gcs permissions probe; safe to delete\n"
    try:
        probe_blob = bucket.blob(probe_name)
        probe_blob.upload_from_string(probe_payload, content_type="text/plain")
        results["WRITE"] = (True, f"uploaded {len(probe_payload)} bytes to {probe_name}")
    except Exception as e:
        results["WRITE"] = (False, f"{type(e).__name__}: {e}")
        probe_blob = None

    # 4. DELETE — clean up
    if probe_blob is not None and results["WRITE"][0]:
        try:
            probe_blob.delete()
            results["DELETE"] = (True, f"deleted {probe_name}")
        except Exception as e:
            results["DELETE"] = (False, f"{type(e).__name__}: {e}")
    else:
        results["DELETE"] = (False, "skipped (WRITE failed, nothing to delete)")

    for op in ("LIST", "READ", "WRITE", "DELETE"):
        ok, msg = results[op]
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {op:6}  {msg}")

    print("-" * 72)
    if all(ok for ok, _ in results.values()):
        print("All operations succeeded. You have Storage Object Admin (or equivalent) on this bucket.")
        print("You can proceed with uploading the 8 runtime CSVs.")
        return 0
    if results["LIST"][0] and results["READ"][0] and not results["WRITE"][0]:
        print("READ-ONLY access detected. You can run the dashboard but cannot upload CSVs.")
        print("Ask the bucket owner to grant 'Storage Object Admin' (or 'Storage Object Creator' + Viewer)")
        print(f"to the service account in {cred_path}.")
        return 1
    print("Mixed / unexpected result — see failures above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
