#!/usr/bin/env python3
"""Write a fresh private ntfy topic into the owner secrets file (ADR 0028). Run as root, once.

    sudo python3 /opt/market-edge-lab/app/deploy/vps/set_ntfy_topic.py [--force]

The topic is a password on a public server. Nothing prints it. The script:
- generates it with `secrets.token_urlsafe(32)`;
- writes it straight into `/etc/market-edge-lab/secrets.env` (root:root 0600), keeping every
  other line;
- replaces the file atomically (temp file created with O_EXCL, fsync, then rename).

An existing topic is kept unless `--force` is passed, because replacing it silently would
break the owner's phone subscription. Only the owner reads the topic back, privately, on the
server (never in an agent session, whose transcript would keep it).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

KEY = "EDGE_LAB_NTFY_TOPIC_URL"
DEFAULT_PATH = "/etc/market-edge-lab/secrets.env"


def _is_topic_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    return stripped.startswith(KEY + "=")


def _has_topic(line: str) -> bool:
    """A usable topic line: plain KEY=value with a value. An `export` line or an empty value is
    not what systemd's EnvironmentFile parser (or sink_from_env) treats as configured."""
    stripped = line.strip()
    return stripped.startswith(KEY + "=") and bool(stripped[len(KEY) + 1:].strip())


def new_topic_url() -> str:
    return "https://ntfy.sh/mel-" + secrets.token_urlsafe(32)  # 47 characters, [-_A-Za-z0-9]


def write_topic(path: str, *, force: bool = False, uid: int = 0, gid: int = 0) -> str:
    """Return "written", "kept" (a topic exists and force is False). Never returns the topic."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        lines = []
    if any(_has_topic(line) for line in lines) and not force:
        return "kept"
    lines = [line for line in lines if not _is_topic_line(line)]
    lines.append(f"{KEY}={new_topic_url()}")
    tmp = f"{path}.new.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if hasattr(os, "chown"):
            os.chown(tmp, uid, gid)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        if hasattr(os, "O_DIRECTORY"):  # make the rename itself durable
            dfd = os.open(os.path.dirname(os.path.abspath(path)), os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return "written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--force", action="store_true", help="replace an existing topic (breaks the subscription)")
    args = parser.parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("run as root", file=sys.stderr)
        return 2
    result = write_topic(args.path, force=args.force)
    print("topic written" if result == "written" else "topic already set; kept (use --force to replace)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
