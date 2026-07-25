#!/usr/bin/env python3
"""Map Codex lifecycle hooks and weekly usage to the IPSTube display."""

import collections
import datetime
import fcntl
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import struct
import sys
import time


# User-level settings. Environment variables can override these values.
DEFAULT_IPSTUBE_URL = "http://ipstube.local"
DEFAULT_IPSTUBE_PROXY = "socks5h://127.0.0.1:3070"
DEFAULT_STATUS_SCREEN = 0
DEFAULT_WORK_ANIMATION = "matrix"
DEFAULT_IDLE_REFRESH_SECONDS = 300
WAIT_ANIMATION = "swirl"
DONE_ANIMATION = "squares"
WAIT_BACKLIGHT_COLOR = "#FF8000"
DONE_BACKLIGHT_COLOR = "#00FF00"
CODEX_BUNDLE_ID = "com.openai.codex"
FOCUS_MARKER = "/tmp/codex-ipstube-done"
FOCUS_LOCK = "/tmp/codex-ipstube-focus.lock"
STATE_FILE = "/tmp/codex-ipstube-state.json"
CODEX_INSTANCE_FILE = "/tmp/codex-ipstube-codex-instance"
IDLE_REFRESH_MARKER = "/tmp/codex-ipstube-refresh-idle"
IDLE_BMP = "/tmp/codex-ipstube-idle.bmp"
IDLE_HASH = "/tmp/codex-ipstube-idle.sha256"
DYNAMIC_IDLE_IMAGE = 249
IDLE_FALLBACK_IMAGE = 251
WEEK_MINUTES = 7 * 24 * 60
BLACK_HOLE_SHIFT_Y = -18

FONT_5X7 = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "%": ("11001", "11010", "00100", "01000", "10110", "00110", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}

EVENT_IMAGES = {
    "SessionStart": IDLE_FALLBACK_IMAGE,
    "UserPromptSubmit": 252,
    "PermissionRequest": 253,
    "PostToolUse": 252,
    "Stop": 254,
}
EVENT_STATES = {
    "SessionStart": "idle",
    "UserPromptSubmit": "work",
    "PostToolUse": "work",
    "PermissionRequest": "wait",
    "Stop": "done",
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


def _upload_image(image, path):
    base_url = os.environ.get("IPSTUBE_URL", DEFAULT_IPSTUBE_URL).rstrip("/")
    proxy = os.environ.get("IPSTUBE_PROXY", DEFAULT_IPSTUBE_PROXY)
    if not base_url or not os.path.isfile(path):
        return False

    command = [
        "/usr/bin/curl",
        "--silent",
        "--fail",
        "--output",
        "/dev/null",
        "--max-time",
        "4",
    ]
    if proxy:
        command.extend(["--proxy", proxy])
    command.extend(
        [
            "--request",
            "POST",
            "--form",
            "file=@" + path,
            "%s/api/images/%d" % (base_url, image),
        ]
    )
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


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


def _request_idle_refresh():
    try:
        with open(IDLE_REFRESH_MARKER, "w", encoding="ascii") as handle:
            handle.write(str(time.time()))
    except OSError:
        pass


def _clear_idle_refresh_request():
    try:
        os.unlink(IDLE_REFRESH_MARKER)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _write_state(state):
    temporary = STATE_FILE + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(
                {"state": state, "updated_at": time.time()},
                handle,
                separators=(",", ":"),
            )
        os.replace(temporary, STATE_FILE)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value.get("state") if isinstance(value, dict) else None
    except Exception:
        return None


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


def _codex_binary():
    override = os.environ.get("CODEX_APP_SERVER")
    candidates = [
        override,
        "/Applications/ChatGPT.app/Contents/Resources/codex",
        "/Applications/Codex.app/Contents/Resources/codex",
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
        shutil.which("codex"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _read_json_line(process, deadline):
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            return None
        line = process.stdout.readline()
        if not line:
            return None
        try:
            message = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(message, dict):
            return message
    return None


def _send_app_server_message(process, message):
    process.stdin.write(
        (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
    )
    process.stdin.flush()


def _wait_for_response(process, request_id, deadline):
    while time.monotonic() < deadline:
        message = _read_json_line(process, deadline)
        if message is None:
            return None
        if message.get("id") == request_id:
            return message
    return None


def _weekly_rate_limit():
    executable = _codex_binary()
    if executable is None:
        return None

    process = None
    try:
        process = subprocess.Popen(
            [executable, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        deadline = time.monotonic() + 5.0
        _send_app_server_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "codex-ipstube", "version": "1.0"}
                },
            },
        )
        initialized = _wait_for_response(process, 1, deadline)
        if not initialized or "result" not in initialized:
            return None

        _send_app_server_message(process, {"method": "initialized"})
        _send_app_server_message(
            process, {"id": 2, "method": "account/rateLimits/read"}
        )
        response = _wait_for_response(process, 2, deadline)
        result = response.get("result") if response else None
        if not isinstance(result, dict):
            return None

        snapshots = []
        by_id = result.get("rateLimitsByLimitId")
        if isinstance(by_id, dict):
            preferred = by_id.get("codex")
            if isinstance(preferred, dict):
                snapshots.append(preferred)
            snapshots.extend(
                item
                for key, item in by_id.items()
                if key != "codex" and isinstance(item, dict)
            )
        fallback = result.get("rateLimits")
        if isinstance(fallback, dict):
            snapshots.append(fallback)

        for snapshot in snapshots:
            for name in ("primary", "secondary"):
                window = snapshot.get(name)
                if not isinstance(window, dict):
                    continue
                if window.get("windowDurationMins") != WEEK_MINUTES:
                    continue
                used = window.get("usedPercent")
                reset = window.get("resetsAt")
                if not isinstance(used, (int, float)) or not isinstance(reset, int):
                    continue
                remaining = max(0, min(100, int(round(100 - used))))
                reset_date = datetime.datetime.fromtimestamp(reset).strftime("%m-%d")
                return remaining, reset_date
        return None
    except Exception:
        return None
    finally:
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=0.5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


def _template_path():
    override = os.environ.get("IPSTUBE_IDLE_TEMPLATE")
    candidates = [
        override,
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "codex_ipstube_idle_template.bmp",
        ),
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "251.bmp",
        ),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _load_indexed_bmp(path):
    with open(path, "rb") as handle:
        data = bytearray(handle.read())
    if data[:2] != b"BM" or len(data) < 54:
        raise ValueError("template is not a BMP")
    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bits = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if width != 135 or height != 240 or bits != 8 or compression != 0:
        raise ValueError("template must be an uncompressed 135x240 8-bit BMP")
    stride = (width + 3) & ~3
    rows = []
    for y in range(height):
        start = pixel_offset + (height - 1 - y) * stride
        rows.append(bytearray(data[start : start + width]))
    return data, pixel_offset, stride, rows


def _rounded_contains(px, py, x, y, width, height, radius):
    if x + radius <= px < x + width - radius:
        return y <= py < y + height
    if y + radius <= py < y + height - radius:
        return x <= px < x + width
    center_x = x + radius - 0.5 if px < x + radius else x + width - radius - 0.5
    center_y = y + radius - 0.5 if py < y + radius else y + height - radius - 0.5
    return (px - center_x) ** 2 + (py - center_y) ** 2 <= radius**2


def _draw_progress(rows, remaining, color):
    x, y, width, height, radius = 12, 166, 111, 14, 7
    inner_x, inner_y = x + 2, y + 2
    inner_width, inner_height, inner_radius = width - 4, height - 4, radius - 2
    fill_width = int(round(inner_width * remaining / 100.0))
    for py in range(y, y + height):
        for px in range(x, x + width):
            outer = _rounded_contains(px, py, x, y, width, height, radius)
            inner = _rounded_contains(
                px, py, inner_x, inner_y, inner_width, inner_height, inner_radius
            )
            if outer and (not inner or (px - inner_x) < fill_width):
                rows[py][px] = color


def _draw_status_text(rows, text, color):
    scale = 2
    glyph_width = 5 * scale
    spacing = 2
    total_width = len(text) * glyph_width + max(0, len(text) - 1) * spacing
    start_x = max(0, (135 - total_width) // 2)
    start_y = 199
    for index, character in enumerate(text):
        glyph = FONT_5X7[character]
        origin_x = start_x + index * (glyph_width + spacing)
        for glyph_y, line in enumerate(glyph):
            for glyph_x, value in enumerate(line):
                if value != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        rows[start_y + glyph_y * scale + dy][
                            origin_x + glyph_x * scale + dx
                        ] = color


def _render_idle_bmp(remaining, reset_date, output_path=IDLE_BMP):
    template = _template_path()
    if template is None:
        return False
    try:
        data, pixel_offset, stride, source_rows = _load_indexed_bmp(template)
        background = collections.Counter(
            pixel for row in source_rows for pixel in row
        ).most_common(1)[0][0]
        idle_colors = collections.Counter(
            source_rows[y][x]
            for y in range(185, 230)
            for x in range(30, 105)
            if source_rows[y][x] != background
        )
        if not idle_colors:
            return False
        idle_color = idle_colors.most_common(1)[0][0]

        rows = [bytearray([background]) * 135 for _ in range(240)]
        for source_y in range(0, 160):
            target_y = source_y + BLACK_HOLE_SHIFT_Y
            if 0 <= target_y < 240:
                rows[target_y][:] = source_rows[source_y]

        _draw_progress(rows, remaining, idle_color)
        _draw_status_text(rows, "%d%% %s" % (remaining, reset_date), idle_color)

        for y, row in enumerate(rows):
            start = pixel_offset + (239 - y) * stride
            data[start : start + 135] = row
            data[start + 135 : start + stride] = b"\x00" * (stride - 135)
        temporary = output_path + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(data)
        os.replace(temporary, output_path)
        return True
    except Exception:
        return False


def _upload_idle_if_changed():
    try:
        with open(IDLE_BMP, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        try:
            with open(IDLE_HASH, "r", encoding="ascii") as handle:
                previous = handle.read().strip()
        except OSError:
            previous = ""
        if digest == previous:
            return True
        if not _upload_image(DYNAMIC_IDLE_IMAGE, IDLE_BMP):
            return False
        temporary = IDLE_HASH + ".tmp"
        with open(temporary, "w", encoding="ascii") as handle:
            handle.write(digest)
        os.replace(temporary, IDLE_HASH)
        return True
    except OSError:
        return False


def _refresh_idle_display():
    return _display_weekly(_weekly_rate_limit())


def _display_weekly(weekly):
    if weekly is None:
        return _post_image(IDLE_FALLBACK_IMAGE)
    remaining, reset_date = weekly
    if not _render_idle_bmp(remaining, reset_date):
        return _post_image(IDLE_FALLBACK_IMAGE)
    if not _upload_idle_if_changed():
        return _post_image(IDLE_FALLBACK_IMAGE)
    if _post_image(DYNAMIC_IDLE_IMAGE):
        return True
    try:
        os.unlink(IDLE_HASH)
    except OSError:
        pass
    return _post_image(IDLE_FALLBACK_IMAGE)


def run(hook_input):
    event_name = hook_input.get("hook_event_name")
    image = image_for_event(event_name)
    if image is None:
        return 0

    def update_status():
        _write_state(EVENT_STATES[event_name])
        _clear_focus_marker()
        if event_name == "SessionStart":
            _request_idle_refresh()
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


def _codex_application_instance():
    executable_paths = {
        "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
        "/Applications/Codex.app/Contents/MacOS/Codex",
    }
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,comm="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = line.strip().split(None, 1)
                if len(fields) == 2 and fields[0].isdigit() and fields[1] in executable_paths:
                    return "pid:" + fields[0]
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["/usr/bin/lsappinfo", "find", "bundleid=" + CODEX_BUNDLE_ID],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        instance = result.stdout.strip()
        return instance if result.returncode == 0 and "NULL" not in instance else ""
    except Exception:
        return ""


def _read_codex_instance():
    try:
        with open(CODEX_INSTANCE_FILE, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _write_codex_instance(instance):
    temporary = CODEX_INSTANCE_FILE + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(instance)
        os.replace(temporary, CODEX_INSTANCE_FILE)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _daemon_log(message):
    print(
        "%s %s"
        % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )


def focus_daemon():
    try:
        refresh_seconds = max(
            60,
            int(
                os.environ.get(
                    "IPSTUBE_IDLE_REFRESH_SECONDS", DEFAULT_IDLE_REFRESH_SECONDS
                )
            ),
        )
    except (TypeError, ValueError):
        refresh_seconds = DEFAULT_IDLE_REFRESH_SECONDS
    last_idle_refresh = 0.0
    last_focus_attempt = 0.0
    last_observed_state = None
    last_codex_instance = _read_codex_instance()
    _daemon_log(
        "watcher started previous_codex_instance=%s"
        % (last_codex_instance or "none")
    )

    while True:
        now = time.monotonic()
        codex_instance = _codex_application_instance()
        if codex_instance != last_codex_instance:
            if codex_instance:
                _daemon_log(
                    "Codex application launch detected instance=%s" % codex_instance
                )
                run({"hook_event_name": "SessionStart"})
            else:
                _daemon_log("Codex application stopped")
            _write_codex_instance(codex_instance)
            last_codex_instance = codex_instance

        current_state = _read_state()
        if current_state != last_observed_state:
            if current_state == "idle":
                last_idle_refresh = 0.0
            last_observed_state = current_state

        if os.path.exists(IDLE_REFRESH_MARKER):
            weekly = _weekly_rate_limit()

            def refresh_requested_idle():
                try:
                    if _read_state() == "idle":
                        return _display_weekly(weekly)
                    return False
                finally:
                    _clear_idle_refresh_request()

            refreshed = _with_focus_lock(refresh_requested_idle)
            _daemon_log(
                "idle refresh completed usage=%s display=%s"
                % ("ok" if weekly is not None else "unavailable", bool(refreshed))
            )
            last_idle_refresh = time.monotonic()
            last_observed_state = _read_state()

        focus_ready = (
            os.path.exists(FOCUS_MARKER)
            and now - last_focus_attempt >= 10.0
            and _frontmost_bundle_id() == CODEX_BUNDLE_ID
        )
        if focus_ready:
            last_focus_attempt = now
            weekly = _weekly_rate_limit()

            def return_to_idle():
                if not os.path.exists(FOCUS_MARKER):
                    return
                if _frontmost_bundle_id() != CODEX_BUNDLE_ID:
                    return
                _write_state("idle")
                image_updated = _display_weekly(weekly)
                backlight_updated = _set_backlight(*EVENT_BACKLIGHTS["SessionStart"])
                if image_updated and backlight_updated:
                    _clear_focus_marker()

            _with_focus_lock(return_to_idle)
            last_idle_refresh = time.monotonic()
            last_observed_state = _read_state()

        now = time.monotonic()
        if _read_state() == "idle" and now - last_idle_refresh >= refresh_seconds:
            weekly = _weekly_rate_limit()

            def refresh_if_still_idle():
                if _read_state() != "idle":
                    return
                _display_weekly(weekly)

            _with_focus_lock(refresh_if_still_idle)
            last_idle_refresh = now
        time.sleep(1.0)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--focus-daemon":
        return focus_daemon()
    if len(sys.argv) == 2 and sys.argv[1] == "--refresh-idle":
        _write_state("idle")
        updated = _with_focus_lock(_refresh_idle_display)
        _set_backlight(*EVENT_BACKLIGHTS["SessionStart"])
        return 0 if updated else 1
    try:
        hook_input = json.load(sys.stdin)
        if not isinstance(hook_input, dict):
            return 0
    except Exception:
        return 0
    return run(hook_input)


if __name__ == "__main__":
    raise SystemExit(main())
