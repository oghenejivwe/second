"""Mint a reusable Google token, once, on a laptop with a browser.

    uv run python scripts/authorize_google.py --role runtime
    uv run python scripts/authorize_google.py --role seeder
    uv run python scripts/authorize_google.py --role runtime --check

Two clients, deliberately
=========================

**runtime** -- ``calendar``, ``gmail.readonly``, ``gmail.compose``. Shipped. Can
read the calendar and inbox and compose drafts. **Cannot insert mail**, so the agent
cannot manufacture the evidence it later cites.

**seeder** -- ``gmail.insert``, ``calendar.events``. Run once, locally, never
deployed. Builds the demo world.

Splitting them costs nothing and it is the difference between claiming least
privilege and having it.

⚠️  PUBLISH THE OAUTH APP BEFORE YOU RUN THIS
=============================================

A refresh token minted while the app's publishing status is **Testing** expires
after **seven days**, and the fuse is set at the moment the token is issued.
Publishing afterwards does not defuse a token that already exists. Adding yourself
as a test user does not exempt you -- the rule keys on publishing status, not on who
you are.

A build submitted on the 14th and judged a week later dies with a
``400 invalid_grant`` that looks exactly like a code bug, at the worst possible
moment.

So, before the first run: Google Auth Platform -> Audience -> **PUBLISH APP**. One
click, no verification, works for up to 100 users. Never submit for verification --
both Gmail scopes are Restricted and verification is a CASA assessment measured in
weeks.

This script cannot check the publishing status (there is no API for it on a consumer
project), so it asks, and it records the answer next to the token.

How the token reaches a deployed backend
========================================

There is no browser in AgentCore, so the deployed runtime never runs this flow. The
refresh token travels instead:

1. Run this locally. It writes ``token.json`` -- client id, client secret, refresh
   token, scopes.
2. Put that JSON in Secrets Manager::

       aws secretsmanager create-secret --name second/google-refresh-token \\
           --secret-string file://token.json --region us-west-2

3. Set ``SECOND_GOOGLE_SECRET_ID=second/google-refresh-token`` in the deployed
   environment and leave ``GOOGLE_TOKEN`` unset.
   ``second.tools._google._load_credentials`` reads the secret when that variable is
   present and the token file when it is not, so local and deployed differ by one
   environment variable and no code.
4. The task role needs ``secretsmanager:GetSecretValue`` on that secret ARN.

**Never commit ``token.json`` or either ``client_secret*.json``.** All four are
already in ``.gitignore``; this script refuses to write outside the repository root
so they land where that covers them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROLES = {
    "runtime": {
        "client_env": "GOOGLE_CLIENT_SECRET",
        "client_default": "client_secret.json",
        "token_env": "GOOGLE_TOKEN",
        "token_default": "token.json",
        "shipped": True,
        "port": 8080,
    },
    "seeder": {
        "client_env": "GOOGLE_SEED_CLIENT_SECRET",
        "client_default": "client_secret_seed.json",
        "token_env": "GOOGLE_SEED_TOKEN",
        "token_default": "token_seed.json",
        "shipped": False,
        # A different port, so a half-finished runtime flow in another tab cannot
        # hand its code to this one.
        "port": 8081,
    },
}


def scopes_for(role: str) -> list[str]:
    from second.settings import GOOGLE_SCOPES

    return list(getattr(GOOGLE_SCOPES, role))


def _path(env_name: str, default: str) -> Path:
    """Resolve a credential path, refusing to leave the repository root.

    The four credential filenames are covered by ``.gitignore`` at the root. A path
    that escapes it would be written somewhere nothing is ignoring, and this
    repository becomes public during a hackathon.
    """
    raw = os.environ.get(env_name, default)
    resolved = (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    if ROOT not in resolved.parents and resolved.parent != ROOT:
        raise SystemExit(
            f"refusing to use {resolved}: credentials must live in {ROOT}, where "
            f".gitignore covers them. This repository becomes public."
        )
    return resolved


def authorise(role: str, *, assume_published: bool = False) -> Path:
    """Run the consent flow and write a token, or explain why it is not usable."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    config = ROLES[role]
    client_file = _path(config["client_env"], config["client_default"])
    token_file = _path(config["token_env"], config["token_default"])
    scopes = scopes_for(role)

    if not client_file.exists():
        raise SystemExit(
            f"no OAuth client at {client_file}.\n"
            f"  Google Auth Platform -> Clients -> Create client -> Desktop app,\n"
            f"  save it as {client_file.name} in {ROOT},\n"
            f"  and register these scopes on the app's Data Access page:\n"
            + "".join(f"    {scope}\n" for scope in scopes)
            + "  Scope registration is app-level; the client requests a subset. Register\n"
            "  all five (runtime's three plus the seeder's two) or the second consent fails."
        )

    if not assume_published and not _confirm_published():
        raise SystemExit(
            "Stopping. Publish the app first -- a token minted in Testing mode expires\n"
            "in seven days and publishing afterwards does not defuse it.\n"
            "  Google Auth Platform -> Audience -> PUBLISH APP\n"
            "Then re-run. Use --assume-published to skip this question in a script."
        )

    print(f"\nAuthorising the {role} client with {len(scopes)} scope(s):")
    for scope in scopes:
        print(f"  {scope}")
    print("\nA browser will open. Expect an 'unverified app' warning -- both Gmail scopes")
    print("are Restricted, so the app stays unverified. Click through it.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes)
    credentials = flow.run_local_server(
        port=config["port"],
        # access_type is already defaulted to "offline" by the library
        # (Flow.authorization_url does kwargs.setdefault), but prompt is not -- and
        # prompt="consent" is the load-bearing one. Without it Google returns a
        # refresh token only on the very first consent, so a re-run produces an
        # access token and a file that is worthless within the hour.
        access_type="offline",
        prompt="consent",
        open_browser=True,
    )

    _assert_usable(credentials, role, scopes)
    _write(token_file, credentials, role, assumed_published=True)
    return token_file


def _confirm_published() -> bool:
    print("\n" + "=" * 72)
    print("  Is the OAuth app's publishing status 'In production' (not 'Testing')?")
    print()
    print("  A refresh token minted while the app is in Testing expires after SEVEN")
    print("  DAYS, and the fuse is set when the token is issued. Publishing later does")
    print("  not defuse it. A build judged a week after submission dies with a")
    print("  400 invalid_grant that reads exactly like a code bug.")
    print()
    print("  Google Auth Platform -> Audience -> PUBLISH APP. One click, no review.")
    print("=" * 72)
    return input("\n  Published? [y/N] ").strip().lower() in ("y", "yes")


def _assert_usable(credentials, role: str, requested: list[str]) -> None:
    """Refuse to write a token that will not survive a restart.

    Two checks, both for failures that are silent at mint time and fatal later.
    """
    if not getattr(credentials, "refresh_token", None):
        raise SystemExit(
            "Google returned no refresh token, so this file would stop working within\n"
            "the hour and there would be no way to renew it without a browser.\n"
            "Cause: prompt='consent' was not honoured, or a prior grant already exists.\n"
            "Fix: revoke this app at https://myaccount.google.com/permissions and re-run."
        )

    granted = set(getattr(credentials, "scopes", None) or [])
    missing = [scope for scope in requested if scope not in granted]
    if missing:
        # Google grants per-scope: a user can untick one on the consent screen and
        # the flow still succeeds. The tool that needed it then 403s in front of a
        # judge with an error about permissions, not about consent.
        raise SystemExit(
            "Some scopes were requested but not granted:\n"
            + "".join(f"  {scope}\n" for scope in missing)
            + "Consent is per-scope, so one unticked box looks like success here and a\n"
            "403 later. Re-run and accept all of them."
        )


def _write(token_file: Path, credentials, role: str, *, assumed_published: bool) -> None:
    payload = json.loads(credentials.to_json())
    payload["_second"] = {
        "role": role,
        "shipped": ROLES[role]["shipped"],
        "publishing_status_confirmed_in_production": assumed_published,
        "note": (
            "If this token stops working with 400 invalid_grant, the app was in "
            "Testing when it was minted. Publish the app and re-run "
            "scripts/authorize_google.py; do not debug it as a code defect."
        ),
    }
    token_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {token_file.name} ({len(payload.get('scopes') or [])} scopes, refresh token present).")
    if role == "seeder":
        print("This one is NEVER deployed. It exists so the agent cannot seed its own evidence.")
    else:
        print("For the deployed runtime, put this in Secrets Manager -- see this file's docstring.")


def check(role: str) -> int:
    """Read an existing token and make one real call with it.

    A token file that parses is not a token that works. The runtime token is proved
    against ``settings.get``; the seeder's is proved against ``events.list``, because
    the seeder's narrower ``calendar.events`` scope cannot read settings at all.
    """
    from second.tools import _google

    config = ROLES[role]
    token_file = _path(config["token_env"], config["token_default"])
    if not token_file.exists():
        print(f"no token at {token_file}. Run without --check to create one.")
        return 1

    stored = json.loads(token_file.read_text(encoding="utf-8"))
    print(f"{token_file.name}: scopes={stored.get('scopes')}")
    if not stored.get("refresh_token"):
        print("  NO REFRESH TOKEN. This file cannot be renewed. Re-run the flow.")
        return 1
    if not (stored.get("_second") or {}).get("publishing_status_confirmed_in_production", True):
        print("  WARNING: minted without confirming the app was published. Expect 7-day expiry.")

    os.environ[config["token_env"]] = str(token_file)
    try:
        if role == "runtime":
            from second.tools.calendar_tools import get_calendar_timezone

            print(f"  live call OK. Calendar timezone: {get_calendar_timezone()}")
        else:
            events = _google.service("calendar", "seeder").events()
            page = _google.call(
                events.list(calendarId="primary", maxResults=1, singleEvents=True, orderBy="startTime"),
                "list one event",
            )
            print(f"  live call OK. Calendar reachable ({len(page.get('items') or [])} event read).")
    except Exception as error:  # noqa: BLE001 - this script's whole job is to report this
        print(f"  LIVE CALL FAILED: {type(error).__name__}: {error}")
        if "invalid_grant" in str(error):
            print("  invalid_grant means the refresh token is dead. If the app was in")
            print("  Testing when this was minted, that is the seven-day fuse. Publish, re-run.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", choices=sorted(ROLES), default="runtime")
    parser.add_argument("--check", action="store_true", help="validate an existing token with one live call")
    parser.add_argument(
        "--assume-published",
        action="store_true",
        help="skip the publishing-status question (only if you have already confirmed it)",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT / "src"))
    if args.check:
        return check(args.role)

    token_file = authorise(args.role, assume_published=args.assume_published)
    print(f"\nNow verify it: uv run python scripts/authorize_google.py --role {args.role} --check")
    return 0 if token_file.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
