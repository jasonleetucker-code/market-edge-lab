"""Serve one fixture state on loopback for manual or browser review: `python tests/browser/serve_fixture.py early`."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from edge_lab.dashboard import make_app  # noqa: E402
from edge_lab.dashboard.server import _QuietHandler  # noqa: E402
from fixture_states import BUILDERS  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("state", choices=sorted(BUILDERS))
    p.add_argument("--port", type=int, default=8767)
    args = p.parse_args()
    cfg, root = BUILDERS[args.state]()
    server = make_server("127.0.0.1", args.port, make_app(cfg), handler_class=_QuietHandler)
    print(f"fixture {args.state} on http://127.0.0.1:{args.port}/", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
