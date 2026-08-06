"""Reconnaissance for a possible Panopto transcript integration. Read-only.

Four questions decide whether the feature is buildable, and none of them can be
settled by reading documentation: they are properties of one particular campus.

  1. Are the recorded-class activities LTI modules, and do they point at Panopto?
  2. Does ``core_course_get_contents`` expose anything that identifies the Panopto
     folder, or only a display name?
  3. Is ``mod_lti_get_tool_launch_data`` exposed to the mobile service?
  4. If it is, do the signed launch parameters carry a folder or session id?

This works on raw payloads rather than the package's models on purpose. The models
declare ``extra="ignore"``, so the very fields worth discovering here (``instance``,
custom LTI parameters) are dropped before they reach a Section or Module object.

Output is redacted by default so it can be pasted into a public issue: names,
emails, ids, tokens and signatures are masked, structure is kept.

    uv run python tools/panopto_recon.py
    uv run python tools/panopto_recon.py --no-redact   # local eyes only
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from moodle_cli.auth import resolve_token
from moodle_cli.client import MoodleClient
from moodle_cli.config import load_config
from moodle_cli.errors import MoodleError

LTI_LAUNCH_FUNCTION = "mod_lti_get_tool_launch_data"

#: Substrings that suggest a module is backed by Panopto rather than another tool.
PANOPTO_HINTS = ("panopto", "lti.aspx")

#: Launch/config keys worth reporting in full: these are what a folder id would ride in.
INTERESTING_KEYS = re.compile(r"folder|session|context|custom|resource_link|tool", re.IGNORECASE)

#: Keys whose values are secrets or personal data, masked even in a redacted dump.
SENSITIVE_KEYS = re.compile(
    r"signature|secret|token|password|oauth_nonce|email|user_id|lis_person", re.IGNORECASE
)


def redact(value: Any, key: str = "", *, enabled: bool = True) -> Any:
    """Mask identifying values while preserving shape, so the dump stays readable."""
    if not enabled:
        return value
    if isinstance(value, dict):
        return {k: redact(v, k, enabled=True) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key, enabled=True) for v in value]
    if isinstance(value, str):
        if SENSITIVE_KEYS.search(key):
            return f"<redacted:{len(value)} chars>"
        # A GUID is exactly what a Panopto folder/session id looks like: keep the fact
        # that it is one, drop the value.
        return re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "<GUID>",
            value,
            flags=re.IGNORECASE,
        )
    return value


def looks_like_panopto(module: dict[str, Any]) -> bool:
    blob = json.dumps(module).casefold()
    return any(hint in blob for hint in PANOPTO_HINTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="print raw values; do not paste this output anywhere public",
    )
    parser.add_argument(
        "--course", help="limit to one course id or shortname, e.g. IOS460", default=None
    )
    args = parser.parse_args()
    hide = not args.no_redact

    config = load_config()
    client = MoodleClient(config.base_url, resolve_token(config))

    with client:
        info = client.get_site_info()
        functions = info.function_names

        print("=" * 72)
        print("SITE")
        print("=" * 72)
        print(f"  release              : {info.release}")
        print(f"  functions exposed    : {len(functions)}")
        print(f"  {LTI_LAUNCH_FUNCTION} : {'YES' if LTI_LAUNCH_FUNCTION in functions else 'NO'}")
        lti_functions = sorted(f for f in functions if "lti" in f.casefold())
        print(f"  all lti functions    : {lti_functions or 'none'}")
        print()

        courses = client.list_courses(view="all-including-hidden")
        if args.course:
            resolved = client.resolve_course(args.course)
            courses = [c for c in courses if c.id == resolved.id]

        print("=" * 72)
        print(f"SCANNING {len(courses)} COURSES FOR LTI MODULES")
        print("=" * 72)

        total_lti = 0
        total_panopto = 0

        for course in courses:
            try:
                # Raw, not client.get_course_contents: the models discard `instance`
                # and any custom parameters, which is exactly what we are looking for.
                sections = client._call("core_course_get_contents", courseid=course.id)
            except MoodleError as exc:
                print(f"  [skip] {course.shortname}: {exc}")
                continue

            for section in sections:
                for module in section.get("modules", []):
                    if module.get("modname") != "lti":
                        continue
                    total_lti += 1
                    panopto = looks_like_panopto(module)
                    total_panopto += panopto

                    print()
                    print(f"  course   : {course.shortname} (id {course.id})")
                    print(f"  section  : {section.get('section')} {section.get('name')!r}")
                    print(f"  module   : {module.get('name')!r}")
                    print(f"  cmid     : {module.get('id')}  instance: {module.get('instance')}")
                    print(f"  panopto? : {'LIKELY' if panopto else 'no signal'}")
                    print("  raw module payload:")
                    print(
                        "    "
                        + json.dumps(
                            redact(module, enabled=hide), indent=2, ensure_ascii=False
                        ).replace("\n", "\n    ")
                    )

                    instance = module.get("instance")
                    if LTI_LAUNCH_FUNCTION not in functions or instance is None:
                        continue

                    # The payload that would carry a folder id, if anything does.
                    try:
                        launch = client._call(LTI_LAUNCH_FUNCTION, toolid=instance)
                    except MoodleError as exc:
                        print(f"  launch data: unavailable ({exc})")
                        continue

                    print("  launch data:")
                    print(f"    endpoint: {redact(launch.get('endpoint', ''), enabled=hide)}")
                    params = launch.get("parameters", [])
                    for param in params:
                        name = str(param.get("name", ""))
                        if not INTERESTING_KEYS.search(name):
                            continue
                        value = redact(param.get("value"), name, enabled=hide)
                        print(f"      {name} = {value}")
                    print(f"    ({len(params)} parameters total)")

        print()
        print("=" * 72)
        print(f"SUMMARY: {total_lti} LTI modules, {total_panopto} that look like Panopto")
        print("=" * 72)
        if total_lti == 0:
            print("  No LTI modules at all. Recorded classes are delivered some other way;")
            print("  re-run without --course, or check what modname the recordings use.")
        elif total_panopto == 0:
            print("  LTI modules exist but none mention Panopto. Check the endpoint above:")
            print("  the campus may use Zoom, Teams, Kaltura or an in-house tool instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
