#!/usr/bin/env python3
"""Map Codex lifecycle hooks to the generic IPSTube display endpoint."""

import json
import os
import sys
import urllib.request


EVENT_IMAGES = {
    "SessionStart": 251,
    "UserPromptSubmit": 252,
    "PermissionRequest": 253,
    "PostToolUse": 252,
    "Stop": 254,
}


def image_for_event(event_name):
    return EVENT_IMAGES.get(event_name)


def _screen_from_environment():
    try:
        screen = int(os.environ.get("IPSTUBE_STATUS_SCREEN", "5"))
    except ValueError:
        return 5
    return screen if 0 <= screen <= 5 else 5


def run(hook_input):
    image = image_for_event(hook_input.get("hook_event_name"))
    base_url = os.environ.get("IPSTUBE_URL", "").rstrip("/")
    if image is None or not base_url:
        return 0

    body = json.dumps(
        {"screen": _screen_from_environment(), "image": image, "save": False},
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url + "/api/display",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=0.5) as response:
            response.read()
    except Exception:
        pass
    return 0


def main():
    try:
        hook_input = json.load(sys.stdin)
        if not isinstance(hook_input, dict):
            return 0
    except Exception:
        return 0
    return run(hook_input)


if __name__ == "__main__":
    raise SystemExit(main())
