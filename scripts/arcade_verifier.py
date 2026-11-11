#!/usr/bin/env python3
"""Run the Arcade for Hermes custom user verifier on your own machine.

  ARCADE_API_KEY=... python3 scripts/arcade_verifier.py --policy examples/bowser/policy.yaml --port 8765

Then set http://localhost:8765 as the project's "Custom user verifier" URL at
https://app.arcade.dev/settings/user-verification and open the links from `/arcade connect` in the
same browser. Each link sends you here with a flow id; pick the role you are consenting as, and
Arcade continues to the app's sign-in. Ctrl-C stops it. Requires: pip install arcadepy
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_plugin():
    spec = importlib.util.spec_from_file_location("arcade_for_hermes", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["arcade_for_hermes"] = module
    spec.loader.exec_module(module)
    from arcade_for_hermes.policy import Policy
    from arcade_for_hermes.verifier import Verifier

    return Policy, Verifier


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", default=str(ROOT / "policy.example.yaml"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--public-url", default="", help="URL Arcade should redirect to, if not http://host:port")
    args = ap.parse_args()
    if not os.environ.get("ARCADE_API_KEY"):
        print("set ARCADE_API_KEY in the environment first", file=sys.stderr)
        return 2
    from arcadepy import Arcade

    Policy, Verifier = _load_plugin()
    policy = Policy.load(args.policy)
    principals = {role: policy.principal(role) for role in policy.roles}
    client = Arcade(max_retries=1)
    verifier = Verifier(lambda: client, principals, host=args.host, port=args.port, ttl_seconds=args.minutes * 60,
                        public_url=args.public_url)
    url = verifier.start()
    print(f"Verifier running at {url} for {args.minutes} minutes. Roles: {', '.join(principals)}")
    print("Set this URL as the Custom user verifier in Arcade settings, then open your /arcade connect links.")
    try:
        while verifier.running:
            time.sleep(1)
            while verifier.confirmations and verifier.confirmations[0].get("_printed") is None:
                c = verifier.confirmations[0]
                c["_printed"] = True
                print(f"confirmed {c['user_id']} (auth {c['auth_id']})")
                verifier.confirmations.append(verifier.confirmations.pop(0))
    except KeyboardInterrupt:
        pass
    verifier.stop()
    print(f"Stopped. {len(verifier.confirmations)} confirmation(s); errors: {verifier.errors or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
