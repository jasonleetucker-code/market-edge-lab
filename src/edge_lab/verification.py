"""Read-only check of the runbook §4.1 fail-closed confirmation (ADR 0028 amendment).

`deploy/vps/verify_fail_closed.sh` runs as root. When the decision unit's exact invocation failed
with rejected_out_of_window, it writes `confirmed-<InvocationID>` into a root-owned directory.
`alert.sh` then records that failure in `last_verification.json`, and everything else in
`last_failure.json`.

The status directory is writable by every edgelab process, so a record's `origin` field is never
trusted alone. A record is a deployment verification only if root's confirmation of its exact
unit and invocation exists and passes these checks:
- it is owned by the trusted uid and not a symlink;
- neither it nor its directory is group- or world-writable;
- its content matches byte for byte.

These are the same checks alert.sh makes.

This module is stdlib-only. It sends nothing and constructs no notification sink, so both the
push relay and the read-only dashboard can use it.
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping

INVOCATION_ID = re.compile(r"[0-9a-f]{32}")  # a systemd InvocationID, as alert.sh records it
UNIT_NAME = re.compile(r"edgelab-[A-Za-z0-9_@.-]{1,80}")
# Written by alert.sh into the status directory: production failures only, and root-confirmed
# fail-closed checks only.
FAILURE_NAME = "last_failure.json"
VERIFICATION_NAME = "last_verification.json"
# Root-owned directory holding the fail-closed check's confirmations (verify_fail_closed.sh).
VERIFY_DIR = "/var/lib/market-edge-lab-verify"
EXPECTED_STATUS = "rejected_out_of_window"


def _trusted(path: str, uid: int) -> bool:
    """Owned by `uid`, not a symlink, not writable by group or others (as alert.sh checks)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return not os.path.islink(path) and st.st_uid == uid and not st.st_mode & 0o022


def verification_confirmed(record: Mapping[str, Any], *, verify_dir: str | os.PathLike[str] = VERIFY_DIR,
                           trusted_uid: int = 0) -> bool:
    """Whether root confirmed this failure record's exact invocation as the runbook §4.1
    fail-closed check. False for anything malformed, missing or untrusted."""
    unit, invocation = record.get("unit"), record.get("invocation_id")
    if not (isinstance(unit, str) and UNIT_NAME.fullmatch(unit) and isinstance(invocation, str)
            and INVOCATION_ID.fullmatch(invocation)):
        return False
    directory = os.fspath(verify_dir)
    confirmation = os.path.join(directory, f"confirmed-{invocation}")
    if not (_trusted(directory, trusted_uid) and _trusted(confirmation, trusted_uid)):
        return False
    expected = f'{{"unit": "{unit}", "invocation_id": "{invocation}", "status": "{EXPECTED_STATUS}"}}\n'
    try:
        with open(confirmation, "rb") as fh:
            return fh.read(1024) == expected.encode("ascii")
    except OSError:
        return False
