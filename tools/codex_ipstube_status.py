#!/usr/bin/env python3
"""Map Codex lifecycle hooks to the IPSTube display endpoint."""

import json
import fcntl
import os
import re
import subprocess
import sys
import time


# User-level settings. Environment variables can override these values.
DEFAULT_IPSTUBE_URL = "http://ipstube.local"
DEFAULT_IPSTUBE_PROXY = "socks5h://127.0.0.1:3070"
DEFAULT_STATUS_SCREEN = 0
DEFAULT_WORK_ANIMATION = "matrix"
WAIT_ANIMATION = "swirl"
DONE_ANIMATION = "squares"
WAIT_BACKLIGHT_COLOR = "#FF8000"
DONE_BACKLIGHT_COLOR = "#00FF00"
CODEX_BUNDLE_ID = "com.openai.codex"
FOCUS_MARKER = "/tmp/codex-ipstube-done"
FOCUS_LOCK = "/tmp/codex-ipstube-focus.lock"

EVENT_IMAGES = {
    "SessionStart": 251,
    "UserPromptSubmit": 252,
    "PermissionRequest": 253,
    "PostToolUse": 252,
    "Stop": 254,
}
WORK_EVENTS = {"UserPromptSubmit", "PostToolUse"}
EVENT_ANIMATIONS = {
    "PermissionRequest": WAIT_ANIMATION,
    "Stop": DONE_ANIMATION,
}
EVENT_BACKLIGHTS = {
    "SessionStart": ("rainbow", None),
    "UserPromptSubmit": ("rainbow", None),
    "PostToolUse": ("rainbow", None),
    "PermissionRequest": ("pulse", WAIT_BACKLIGHT_COLOR),
    "Stop": ("breath", DONE_BACKLIGHT_COLOR),
}


def image_for_event(event_name):
    return EVENT_IMAGES.get(event_name)


def _screen_from_environment():
    try:
        screen = int(os.environ.get("IPSTUBE_STATUS_SCREEN", DEFAULT_STATUS_SCREEN))
    except (TypeError, ValueError):
        return DEFAULT_STATUS_SCREEN
    return screen if 0 <= screen <= 5 else DEFAULT_STATUS_SCREEN


def _post_json(path, payload):
    base_url = os.environ.get("IPSTUBE_URL", DEFAULT_IPSTUBE_URL).rstrip("/")
    proxy = os.environ.get("IPSTUBE_PROXY", DEFAULT_IPSTUBE_PROXY)
    if not base_url:
        return False

    body = json.dumps(payload, separators=(",", ":"))
    command = [
        "/usr/bin/curl",
        "--silent",
        "--fail",
        "--output",
        "/dev/null",
        "--max-time",
        "0.75",
    ]
    if proxy:
        command.extend(["--proxy", proxy])
    command.extend(
        [
            "--request",
            "POST",
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            body,
            base_url + path,
        ]
    )
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        # A disconnected clock must never interrupt Codex.
        return False


def _post_image(image):
    if image is None:
        return False
    return _post_json(
        "/api/display",
        {"screen": _screen_from_environment(), "image": image, "save": False},
    )


def _start_animation(animation):
    return _post_json(
        "/api/animation",
        {
            "screen": _screen_from_environment(),
            "animation": animation,
            "save": False,
        },
    )


def _set_backlight(effect, color=None):
    payload = {"effect": effect, "save": False}
    if color is not None:
        payload["color"] = color
    return _post_json("/api/backlight", payload)


def _animation_for_event(event_name):
    if event_name in WORK_EVENTS:
        return os.environ.get("IPSTUBE_WORK_ANIMATION", DEFAULT_WORK_ANIMATION)
    return EVENT_ANIMATIONS.get(event_name)


def _clear_focus_marker():
    try:
        os.unlink(FOCUS_MARKER)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _write_focus_marker(hook_input):
    marker = {
        "session_id": hook_input.get("session_id"),
        "turn_id": hook_input.get("turn_id"),
        "created_at": time.time(),
    }
    temporary = FOCUS_MARKER + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(marker, handle, separators=(",", ":"))
        os.replace(temporary, FOCUS_MARKER)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _with_focus_lock(callback):
    try:
        with open(FOCUS_LOCK, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            return callback()
    except OSError:
        return callback()


def run(hook_input):
    event_name = hook_input.get("hook_event_name")
    image = image_for_event(event_name)
    if image is None:
        return 0

    def update_status():
        _clear_focus_marker()
        animation = _animation_for_event(event_name)
        if animation is not None:
            if not _start_animation(animation):
                _post_image(image)
        else:
            _post_image(image)
        backlight = EVENT_BACKLIGHTS.get(event_name)
        if backlight is not None:
            _set_backlight(*backlight)
        if event_name == "Stop":
            _write_focus_marker(hook_input)

    _with_focus_lock(update_status)
    return 0


def _frontmost_bundle_id():
    try:
        front = subprocess.run(
            ["/usr/bin/lsappinfo", "front"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        ).stdout.strip()
        if not front or "NULL" in front:
            return ""
        info = subprocess.run(
            ["/usr/bin/lsappinfo", "info", "-only", "bundleid", front],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        ).stdout
        match = re.search(r'"CFBundleIdentifier"="([^"]+)"', info)
        return match.group(1) if match else ""
    except Exception:
        return ""


def focus_daemon():
    while True:
        if os.path.exists(FOCUS_MARKER) and _frontmost_bundle_id() == CODEX_BUNDLE_ID:
            def return_to_idle():
                if not os.path.exists(FOCUS_MARKER):
                    return
                if _frontmost_bundle_id() != CODEX_BUNDLE_ID:
                    return
                image_updated = _post_image(EVENT_IMAGES["SessionStart"])
                backlight_updated = _set_backlight(*EVENT_BACKLIGHTS["SessionStart"])
                if image_updated and backlight_updated:
                    _clear_focus_marker()

            _with_focus_lock(return_to_idle)
        time.sleep(1.0)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--focus-daemon":
        return focus_daemon()
    try:
        hook_input = json.load(sys.stdin)
        if not isinstance(hook_input, dict):
            return 0
    except Exception:
        return 0
    return run(hook_input)


if __name__ == "__main__":
    raise SystemExit(main())
