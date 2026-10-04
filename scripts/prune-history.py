#!/usr/bin/env python3
"""Prune old history JPEGs (local outbox and/or R2) to control storage cost.

Default retention: 90 days.

Examples:
  # Local outbox only
  python3 scripts/prune-history.py --local data/outbox/history --days 90

  # R2 (requires env from example-webcam-r2.env)
  set -a && source ~/Projects/.secrets/example-webcam-r2.env && set +a
  python3 scripts/prune-history.py --r2 --prefix history/example --days 90 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def prune_local(root: Path, days: float, dry_run: bool) -> int:
    if not root.exists():
        print(f"local path missing: {root}")
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for path in root.rglob("*.jpg"):
        if path.stat().st_mtime >= cutoff:
            continue
        removed += 1
        if dry_run:
            print(f"DRY would delete {path}")
        else:
            path.unlink(missing_ok=True)
            print(f"deleted {path}")
    return removed


def prune_r2(prefix: str, days: float, dry_run: bool) -> int:
    import boto3

    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    bucket = os.environ.get("R2_BUCKET")
    if not endpoint or not bucket:
        raise SystemExit("Need AWS_ENDPOINT_URL and R2_BUCKET in environment")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    cutoff = time.time() - days * 86400
    removed = 0
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            key = obj["Key"]
            if not key.endswith((".jpg", ".jpeg")):
                continue
            last = obj["LastModified"].timestamp()
            if last >= cutoff:
                continue
            removed += 1
            if dry_run:
                print(f"DRY would delete s3://{bucket}/{key}")
            else:
                client.delete_object(Bucket=bucket, Key=key)
                print(f"deleted s3://{bucket}/{key}")
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune webcam history frames")
    parser.add_argument("--days", type=float, default=90.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local", type=Path, help="Local history root to prune")
    parser.add_argument("--r2", action="store_true", help="Prune R2 objects")
    parser.add_argument("--prefix", default="history/", help="R2 key prefix")
    args = parser.parse_args(argv)

    total = 0
    if args.local:
        total += prune_local(args.local, args.days, args.dry_run)
    if args.r2:
        total += prune_r2(args.prefix, args.days, args.dry_run)
    if not args.local and not args.r2:
        print("Specify --local and/or --r2", file=sys.stderr)
        return 2
    print(f"done — {total} object(s) {'would be ' if args.dry_run else ''}removed (>{args.days} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
