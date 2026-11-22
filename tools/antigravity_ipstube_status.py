#!/usr/bin/env python3
"""Map Antigravity lifecycle hooks, live status, and quotas to the IPSTube display."""

import datetime
import fcntl
import hashlib
import json
import os
import re
import ssl
import struct
import subprocess
import sys
import time
import urllib.request


# User-level settings. Environment variables can override these values.
DEFAULT_IPSTUBE_URL = "http://ipstube.home"
DEFAULT_IPSTUBE_PROXY = ""
DEFAULT_STATUS_SCREEN = 1
DEFAULT_WORK_ANIMATION = "matrix"
DEFAULT_IDLE_REFRESH_SECONDS = 300
PARTIAL_IDLE_RETRY_SECONDS = 15.0
USAGE_QUERY_ATTEMPTS = 3
USAGE_RETRY_SECONDS = 2
USAGE_RPC_TIMEOUT_SECONDS = 5.0
WAIT_ANIMATION = "swirl"
DONE_ANIMATION = "squares"
WAIT_BACKLIGHT_COLOR = "#FF8000"
DONE_BACKLIGHT_COLOR = "#00FF00"
ANTIGRAVITY_BUNDLE_IDS = (
    "com.google.antigravity",
    "com.google.antigravity-ide",
)
ANTIGRAVITY_EXECUTABLES = (
    "/Applications/Antigravity.app/Contents/MacOS/Antigravity",
)
FOCUS_MARKER = "/tmp/antigravity-ipstube-done"
FOCUS_LOCK = "/tmp/antigravity-ipstube-focus.lock"
BACKLIGHT_LOCK = "/tmp/ipstube-backlight.lock"
STATE_FILE = "/tmp/antigravity-ipstube-state.json"
PEER_STATE_FILE = "/tmp/codex-ipstube-state.json"
PENDING_EVENT_FILE = "/tmp/antigravity-ipstube-pending.json"
HOOK_QUEUE_DIR = "/tmp/antigravity-ipstube-events"
APP_INSTANCE_FILE = "/tmp/antigravity-ipstube-app-instance"
IDLE_REFRESH_MARKER = "/tmp/antigravity-ipstube-refresh-idle"
IDLE_BMP = "/tmp/antigravity-ipstube-idle.bmp"
IDLE_HASH = "/tmp/antigravity-ipstube-idle.sha256"
DAEMON_DISCOVERY_DIR = os.path.expanduser("~/.gemini/antigravity/daemon")
DYNAMIC_IDLE_IMAGE = 248
IDLE_FALLBACK_IMAGE = 251
FIVE_HOUR_SECONDS = 5 * 3600
FIVE_HOUR_MINUTES = 5 * 60
WEEK_MINUTES = 7 * 24 * 60
HOOK_GRACE_SECONDS = 3.0
HOOKLESS_DONE_GRACE_SECONDS = 2.0

# 8-bit BMP palette: black background + light green, light orange (no white).
QUOTA_PALETTE = (
    (0, 0, 0),
    (144, 238, 168),
    (255, 192, 128),
)

# Ordered top-to-bottom: Gemini 5h, Gemini weekly, Claude&GPT 5h, Claude&GPT weekly.
QUOTA_ROWS = (
    ("gemini_5h", 1, 28, 44, "%H:%M", "--:--"),
    ("gemini_weekly", 1, 74, 90, "%m-%d", "-- --"),
    ("claude_gpt_5h", 2, 136, 152, "%H:%M", "--:--"),
    ("claude_gpt_weekly", 2, 182, 198, "%m-%d", "-- --"),
)

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
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}

EVENT_IMAGES = {
    "SessionStart": IDLE_FALLBACK_IMAGE,
    "Cancel": IDLE_FALLBACK_IMAGE,
    "Work": 252,
    "Wait": 253,
    "Done": 254,
}
EVENT_STATES = {
    "SessionStart": "idle",
    "Cancel": "idle",
    "Work": "work",
    "Wait": "wait",
    "Done": "done",
}
EVENT_ANIMATIONS = {
    "Wait": WAIT_ANIMATION,
    "Done": DONE_ANIMATION,
}
EVENT_BACKLIGHTS = {
    "SessionStart": ("rainbow", None),
    "Cancel": ("rainbow", None),
    "Work": ("rainbow", None),
    "Wait": ("pulse", WAIT_BACKLIGHT_COLOR),
    "Done": ("breath", DONE_BACKLIGHT_COLOR),
}
STATE_BACKLIGHTS = {
    "wait": ("pulse", WAIT_BACKLIGHT_COLOR),
    "done": ("breath", DONE_BACKLIGHT_COLOR),
}

RFC3339_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)

_CACHED_LS_ENDPOINT = None


def _normalize_event_name(hook_input):
    if not isinstance(hook_input, dict):
        return None
    raw_name = hook_input.get("hookEventName") or hook_input.get("hook_event_name")
    if not isinstance(raw_name, str) or not raw_name:
        return None
    if raw_name == "SessionStart":
        return "SessionStart"
    if raw_name in ("PreInvocation", "PostToolUse", "PostInvocation", "Work"):
        return "Work"
    if raw_name == "Wait":
        return "Wait"
    if raw_name in ("Interrupt", "Cancel"):
        return "Cancel"
    if raw_name == "Stop":
        reason = hook_input.get("terminationReason")
        if reason == "USER_CANCELED":
            return "Cancel"
        return "Done"
    return None


def image_for_event(event_name):
    if event_name in EVENT_IMAGES:
        return EVENT_IMAGES[event_name]
    normalized = _normalize_event_name({"hookEventName": event_name})
    return EVENT_IMAGES.get(normalized)


def _screen_from_environment():
    try:
        screen = int(os.environ.get("IPSTUBE_STATUS_SCREEN", DEFAULT_STATUS_SCREEN))
    except (TypeError, ValueError):
        return DEFAULT_STATUS_SCREEN
    return screen if 0 <= screen <= 5 else DEFAULT_STATUS_SCREEN


def _antigravity_bundle_ids():
    override = os.environ.get("ANTIGRAVITY_BUNDLE_ID", "").strip()
    if override:
        return (override,) + tuple(
            item for item in ANTIGRAVITY_BUNDLE_IDS if item != override
        )
    return ANTIGRAVITY_BUNDLE_IDS


def _antigravity_executables():
    override = os.environ.get("ANTIGRAVITY_APP_EXECUTABLE", "").strip()
    if override:
        return (override,) + tuple(
            item for item in ANTIGRAVITY_EXECUTABLES if item != override
        )
    return ANTIGRAVITY_EXECUTABLES


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
    else:
        command.extend(["--noproxy", "*"])
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
        # A disconnected clock must never interrupt Antigravity.
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
    else:
        command.extend(["--noproxy", "*"])
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


def _with_backlight_lock(callback):
    try:
        with open(BACKLIGHT_LOCK, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            return callback()
    except OSError:
        return callback()


def _resolve_backlight(event_name):
    state = EVENT_STATES.get(event_name)
    if state in ("wait", "done"):
        return EVENT_BACKLIGHTS[event_name]
    peer_state = _read_peer_state()
    if peer_state in STATE_BACKLIGHTS:
        return STATE_BACKLIGHTS[peer_state]
    return EVENT_BACKLIGHTS[event_name]


def _apply_backlight(event_name):
    # Acquire FOCUS_LOCK -> BACKLIGHT_LOCK only; never reverse this lock order.
    return _with_backlight_lock(lambda: _set_backlight(*_resolve_backlight(event_name)))


def _animation_for_event(event_name):
    if event_name == "Work":
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


def _write_state(state, source="hook"):
    temporary = STATE_FILE + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(
                {"state": state, "updated_at": time.time(), "source": source},
                handle,
                separators=(",", ":"),
            )
        os.replace(temporary, STATE_FILE)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _read_state_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            return None, 0.0, None
        state = value.get("state")
        updated_at = value.get("updated_at")
        source = value.get("source")
        return (
            state if isinstance(state, str) else None,
            float(updated_at) if isinstance(updated_at, (int, float)) else 0.0,
            source if isinstance(source, str) else None,
        )
    except Exception:
        return None, 0.0, None


def _read_state_record():
    return _read_state_file(STATE_FILE)


def _read_state():
    return _read_state_file(STATE_FILE)[0]


def _read_peer_state():
    return _read_state_file(PEER_STATE_FILE)[0]


def _write_focus_marker(hook_input):
    marker = {
        "conversation_id": hook_input.get("conversationId"),
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


def _pid_is_running(pid):
    if isinstance(pid, bool):
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _discover_daemon_file_endpoints():
    directory = os.environ.get("ANTIGRAVITY_DAEMON_DIR", "").strip() or DAEMON_DISCOVERY_DIR
    try:
        names = [name for name in os.listdir(directory) if name.endswith(".json")]
    except OSError:
        return []

    candidates = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        candidates.append((0 if name.startswith("hub_") else 1, -mtime, path))
    candidates.sort()

    endpoints = []
    for _, _, path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        csrf_token = data.get("csrfToken") or data.get("csrf_token")
        if not isinstance(csrf_token, str) or not csrf_token:
            continue
        pid = data.get("pid")
        if pid is not None and not _pid_is_running(pid):
            continue
        pid_str = str(int(pid)) if pid is not None else None
        for scheme, port_key in (("http", "httpPort"), ("https", "httpsPort")):
            port = data.get(port_key)
            if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
                endpoints.append((pid_str, "%s://127.0.0.1:%d" % (scheme, port), csrf_token))
    return endpoints


def _discover_ps_endpoints():
    try:
        ps_result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return []
    if ps_result.returncode != 0:
        return []

    processes = []
    for line in ps_result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid, command = parts[0], parts[1]
        if "language_server" not in command or "--csrf_token" not in command:
            continue
        token_match = re.search(r"--csrf_token(?:=|\s+)([^\s]+)", command)
        if not token_match:
            continue
        ext_match = re.search(r"--extension_server_port(?:=|\s+)(\d+)", command)
        ext_port = int(ext_match.group(1)) if ext_match else None
        priority = 0 if "antigravity" in command.lower() else 1
        processes.append((priority, pid, token_match.group(1), ext_port))

    processes.sort(key=lambda item: item[0])
    endpoints = []
    for _, pid, csrf_token, ext_port in processes:
        try:
            lsof_result = subprocess.run(
                ["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", pid],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except Exception:
            continue
        if lsof_result.returncode != 0:
            continue

        ports = []
        for match in re.finditer(
            r"(?:127\.0\.0\.1|\[::1\]|\*):(\d+)\s+\(LISTEN\)", lsof_result.stdout
        ):
            port = int(match.group(1))
            if port not in ports:
                ports.append(port)
        if ext_port in ports:
            ports.sort(key=lambda value: value == ext_port)

        for port in ports:
            endpoints.append((pid, "https://127.0.0.1:%d" % port, csrf_token))
            endpoints.append((pid, "http://127.0.0.1:%d" % port, csrf_token))
    return endpoints


def _discover_endpoints():
    override_url = os.environ.get("ANTIGRAVITY_LS_URL", "").strip()
    override_token = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "").strip()
    if override_url and override_token:
        return [(None, override_url.rstrip("/"), override_token)]

    endpoints = []
    seen = set()
    for endpoint in _discover_daemon_file_endpoints() + _discover_ps_endpoints():
        key = (endpoint[1], endpoint[2])
        if key not in seen:
            seen.add(key)
            endpoints.append(endpoint)
    return endpoints


def _rpc_post(base_url, method, csrf_token, payload=None, timeout=2.0):
    url = "%s/exa.language_server_pb.LanguageServerService/%s" % (base_url, method)
    body = json.dumps(payload if payload is not None else {}, separators=(",", ":")).encode(
        "utf-8"
    )
    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "X-Codeium-Csrf-Token": csrf_token,
    }
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    context = ssl._create_unverified_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            decoded = json.loads(response.read().decode("utf-8"))
        return decoded if isinstance(decoded, dict) else None
    except Exception:
        return None


def _call_language_server(method, payload=None, timeout=2.0):
    global _CACHED_LS_ENDPOINT
    cached = _CACHED_LS_ENDPOINT
    if cached is not None:
        _, base_url, csrf_token = cached
        result = _rpc_post(base_url, method, csrf_token, payload, timeout=timeout)
        if result is not None:
            return result
        _CACHED_LS_ENDPOINT = None

    for endpoint in _discover_endpoints():
        if endpoint == cached:
            continue
        _, base_url, csrf_token = endpoint
        result = _rpc_post(base_url, method, csrf_token, payload, timeout=timeout)
        if result is not None:
            _CACHED_LS_ENDPOINT = endpoint
            return result
    return None


def _parse_rfc3339_local(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(value))
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, dict):
        seconds = value.get("seconds")
        if isinstance(seconds, (int, float, str)):
            try:
                return datetime.datetime.fromtimestamp(float(seconds))
            except (OSError, OverflowError, ValueError):
                return None
        return None
    if not isinstance(value, str):
        return None

    text = value.strip()
    match = RFC3339_RE.match(text)
    if not match:
        return None
    date_part, time_part, fraction, tz_part = match.groups()
    iso = "%sT%s" % (date_part, time_part)
    if fraction:
        iso += "." + fraction[:6].ljust(6, "0")
    if tz_part:
        if tz_part == "Z":
            iso += "+00:00"
        elif len(tz_part) == 5 and ":" not in tz_part:
            iso += tz_part[:3] + ":" + tz_part[3:]
        else:
            iso += tz_part
    try:
        parsed = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone()
    return parsed


def _classify_quota_bucket(
    group_id, group_name, bucket_id, bucket_name, window, duration_mins
):
    exact = {
        "gemini-5h": "gemini_5h",
        "gemini-weekly": "gemini_weekly",
        "3p-5h": "claude_gpt_5h",
        "3p-weekly": "claude_gpt_weekly",
    }
    bucket_key = (bucket_id or "").strip().lower()
    if bucket_key in exact:
        return exact[bucket_key]

    combined = " ".join(
        part.lower()
        for part in (group_id, group_name, bucket_id, bucket_name)
        if isinstance(part, str) and part
    )
    window_text = (window or "").strip().lower()

    # Ignore legacy Argon-specific buckets so they never overwrite Gemini general buckets.
    if "argon" in combined:
        return None
    if any(token in combined for token in ("claude", "gpt", "3p", "third")):
        family = "claude_gpt"
    elif "gemini" in combined:
        family = "gemini"
    else:
        return None

    is_five_hour = (
        duration_mins == FIVE_HOUR_MINUTES
        or window_text in ("5h", "five_hour", "session")
        or any(token in combined for token in ("5h", "5-hour", "five hour", "five_hour"))
    )
    is_weekly = (
        duration_mins == WEEK_MINUTES
        or window_text in ("weekly", "7d", "week")
        or any(token in combined for token in ("weekly", "week", "7d"))
    )

    if is_five_hour and not is_weekly:
        return "%s_5h" % family
    if is_weekly:
        return "%s_weekly" % family
    return None


def _bucket_remaining_percent(bucket):
    remaining_fraction = bucket.get("remainingFraction")
    if isinstance(remaining_fraction, (int, float)):
        return max(0, min(100, int(round(float(remaining_fraction) * 100.0))))
    remaining_percent = bucket.get("remainingPercent")
    if isinstance(remaining_percent, (int, float)):
        return max(0, min(100, int(round(float(remaining_percent)))))
    used_fraction = bucket.get("usedFraction")
    if isinstance(used_fraction, (int, float)):
        return max(0, min(100, int(round((1.0 - float(used_fraction)) * 100.0))))
    used_percent = bucket.get("usedPercent")
    if isinstance(used_percent, (int, float)):
        return max(0, min(100, int(round(100.0 - float(used_percent)))))
    # Proto3 omits zero scalar fields; an active resetTime without remainingFraction means 0%.
    if bucket.get("resetTime") is not None:
        return 0
    return None


def _extract_quota_from_groups(groups):
    limits = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = group.get("id") or group.get("groupId") or group.get("quotaGroupId") or ""
        group_name = group.get("displayName") or group.get("name") or ""
        buckets = group.get("buckets") or group.get("quotaBuckets") or []
        if not isinstance(buckets, list):
            continue
        for bucket in buckets:
            if not isinstance(bucket, dict) or bucket.get("disabled") is True:
                continue
            bucket_id = bucket.get("bucketId") or bucket.get("id") or ""
            bucket_name = bucket.get("displayName") or bucket.get("name") or ""
            window = bucket.get("window") or ""
            duration = bucket.get("windowDurationMins")
            key = _classify_quota_bucket(
                group_id, group_name, bucket_id, bucket_name, window, duration
            )
            if key is None:
                continue
            remaining = _bucket_remaining_percent(bucket)
            if remaining is None:
                continue
            is_five_hour = key.endswith("_5h")
            reset_format = "%H:%M" if is_five_hour else "%m-%d"
            fallback_reset = "--:--" if is_five_hour else "-- --"
            reset_dt = _parse_rfc3339_local(bucket.get("resetTime"))
            reset_text = reset_dt.strftime(reset_format) if reset_dt else fallback_reset
            if key not in limits or remaining < limits[key][0]:
                limits[key] = (remaining, reset_text)
    return limits or None


def _extract_quota_from_user_status(payload):
    user_status = payload.get("userStatus")
    if not isinstance(user_status, dict):
        return None
    config_data = user_status.get("cascadeModelConfigData")
    if not isinstance(config_data, dict):
        return None
    model_configs = config_data.get("clientModelConfigs")
    if not isinstance(model_configs, list):
        return None

    now = datetime.datetime.now().astimezone()
    limits = {}
    for item in model_configs:
        if not isinstance(item, dict):
            continue
        quota_info = item.get("quotaInfo")
        if not isinstance(quota_info, dict):
            continue
        model_alias = item.get("modelOrAlias")
        alias_name = (
            model_alias.get("model") if isinstance(model_alias, dict) else ""
        )
        label = " ".join(
            str(part)
            for part in (item.get("label"), alias_name, item.get("model"))
            if part
        ).lower()
        if not label:
            continue
        remaining = _bucket_remaining_percent(quota_info)
        if remaining is None:
            continue
        reset_dt = _parse_rfc3339_local(quota_info.get("resetTime"))

        if "argon" in label:
            continue
        if any(token in label for token in ("claude", "gpt")):
            family = "claude_gpt"
        elif "gemini" in label:
            family = "gemini"
        else:
            continue
        if reset_dt is not None:
            delta = (reset_dt - now).total_seconds()
            window_suffix = "5h" if delta <= FIVE_HOUR_SECONDS + 3600 else "weekly"
        else:
            window_suffix = "weekly"
        key = "%s_%s" % (family, window_suffix)

        is_five_hour = key.endswith("_5h")
        reset_format = "%H:%M" if is_five_hour else "%m-%d"
        fallback_reset = "--:--" if is_five_hour else "-- --"
        reset_text = reset_dt.strftime(reset_format) if reset_dt else fallback_reset
        if key not in limits or remaining < limits[key][0]:
            limits[key] = (remaining, reset_text)
    return limits or None


def _extract_quota_limits(payload):
    if not isinstance(payload, dict):
        return None

    containers = [payload]
    for wrapper_key in ("response", "userQuotaSummary"):
        nested = payload.get(wrapper_key)
        if isinstance(nested, dict):
            containers.append(nested)

    for container in containers:
        for groups_key in ("groups", "quotaGroups"):
            groups = container.get(groups_key)
            if isinstance(groups, list):
                limits = _extract_quota_from_groups(groups)
                if limits:
                    return limits
        for buckets_key in ("buckets", "quotaBuckets"):
            buckets = container.get(buckets_key)
            if isinstance(buckets, list):
                limits = _extract_quota_from_groups([{"buckets": buckets}])
                if limits:
                    return limits

    return _extract_quota_from_user_status(payload)


def _has_complete_quota(limits):
    return isinstance(limits, dict) and all(row[0] in limits for row in QUOTA_ROWS)


def _read_quota_summary():
    summary = _call_language_server(
        "RetrieveUserQuotaSummary", {}, timeout=USAGE_RPC_TIMEOUT_SECONDS
    )
    return _extract_quota_limits(summary)


def _read_user_status_limits():
    user_status = _call_language_server(
        "GetUserStatus",
        {
            "metadata": {
                "ideName": "antigravity",
                "extensionName": "antigravity",
                "locale": "en",
            }
        },
        timeout=USAGE_RPC_TIMEOUT_SECONDS,
    )
    return _extract_quota_limits(user_status)


def _read_rate_limits():
    limits = _read_quota_summary()
    if limits is not None:
        return limits
    return _read_user_status_limits()


def _rate_limits():
    best = None
    for attempt in range(USAGE_QUERY_ATTEMPTS):
        limits = _read_quota_summary()
        if _has_complete_quota(limits):
            return limits
        if limits is not None and (best is None or len(limits) > len(best)):
            best = limits
        if attempt + 1 < USAGE_QUERY_ATTEMPTS:
            time.sleep(USAGE_RETRY_SECONDS)
    if best is not None:
        return best
    return _read_user_status_limits()


def _next_idle_refresh_delay(limits, refresh_seconds, app_running=True):
    if _has_complete_quota(limits):
        return refresh_seconds
    if limits is not None or app_running:
        return min(refresh_seconds, PARTIAL_IDLE_RETRY_SECONDS)
    return refresh_seconds


def _rounded_contains(px, py, x, y, width, height, radius):
    if x + radius <= px < x + width - radius:
        return y <= py < y + height
    if y + radius <= py < y + height - radius:
        return x <= px < x + width
    center_x = x + radius - 0.5 if px < x + radius else x + width - radius - 0.5
    center_y = y + radius - 0.5 if py < y + radius else y + height - radius - 0.5
    return (px - center_x) ** 2 + (py - center_y) ** 2 <= radius**2


def _draw_progress(rows, remaining, color_index, y):
    x, width, height, radius = 12, 111, 12, 6
    inner_x, inner_y = x + 2, y + 2
    inner_width, inner_height, inner_radius = width - 4, height - 4, radius - 2
    fill_width = int(round(inner_width * max(0, min(100, remaining)) / 100.0))
    for py in range(y, y + height):
        for px in range(x, x + width):
            outer = _rounded_contains(px, py, x, y, width, height, radius)
            inner = _rounded_contains(
                px, py, inner_x, inner_y, inner_width, inner_height, inner_radius
            )
            if outer and (not inner or (px - inner_x) < fill_width):
                rows[py][px] = color_index


def _draw_status_text(rows, text, color_index, start_y):
    scale = 2
    glyph_width = 5 * scale
    spacing = 2
    total_width = len(text) * glyph_width + max(0, len(text) - 1) * spacing
    start_x = max(0, (135 - total_width) // 2)
    for index, character in enumerate(text):
        glyph = FONT_5X7.get(character, FONT_5X7[" "])
        origin_x = start_x + index * (glyph_width + spacing)
        for glyph_y, line in enumerate(glyph):
            for glyph_x, value in enumerate(line):
                if value != "1":
                    continue
                for dy in range(scale):
                    py = start_y + glyph_y * scale + dy
                    if py >= 240:
                        continue
                    for dx in range(scale):
                        px = origin_x + glyph_x * scale + dx
                        if px < 135:
                            rows[py][px] = color_index


def _encode_indexed_bmp(rows, palette):
    width, height = 135, 240
    stride = (width + 3) & ~3
    padding = b"\x00" * (stride - width)
    palette_bytes = b"".join(
        struct.pack("<BBBB", blue, green, red, 0) for red, green, blue in palette
    )
    pixel_offset = 14 + 40 + len(palette_bytes)
    image_size = stride * height
    file_size = pixel_offset + image_size

    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset)
    dib_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        8,
        0,
        image_size,
        2835,
        2835,
        len(palette),
        len(palette),
    )
    pixels = b"".join(bytes(rows[y]) + padding for y in range(height - 1, -1, -1))
    return file_header + dib_header + palette_bytes + pixels


def _render_idle_bmp(limits, output_path=IDLE_BMP):
    try:
        rows = [bytearray(135) for _ in range(240)]
        for key, color_index, bar_y, text_y, _, fallback_reset in QUOTA_ROWS:
            entry = limits.get(key) if limits else None
            if entry is not None:
                remaining, reset_text = entry
                text = "%d%% %s" % (remaining, reset_text)
            else:
                remaining = 0
                text = "--%% %s" % fallback_reset
            _draw_progress(rows, remaining, color_index, bar_y)
            _draw_status_text(rows, text, color_index, text_y)

        bmp_bytes = _encode_indexed_bmp(rows, QUOTA_PALETTE)
        temporary = output_path + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(bmp_bytes)
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
    return _display_limits(_rate_limits())


def _display_limits(limits):
    if limits is None:
        return _post_image(IDLE_FALLBACK_IMAGE)
    if not _render_idle_bmp(limits):
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


def run(hook_input, source="hook"):
    event_name = _normalize_event_name(hook_input)
    if event_name is None:
        return 0
    # Queue before taking the device lock: hooks can expire while waiting for it.
    os.makedirs(HOOK_QUEUE_DIR, exist_ok=True)
    path = os.path.join(
        HOOK_QUEUE_DIR, "%020d-%d.json" % (time.monotonic_ns(), os.getpid())
    )
    event = {"event": event_name, "source": source}
    conversation_id = hook_input.get("conversationId")
    if isinstance(conversation_id, str) and conversation_id:
        event["conversationId"] = conversation_id
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(event, handle)
    os.replace(path + ".tmp", path)
    _with_focus_lock(_retry_pending_event)
    return 0


def _persist_event(queued_event):
    event_name = queued_event.get("event")
    if event_name not in EVENT_STATES:
        event_name = _normalize_event_name(queued_event)
    if event_name not in EVENT_STATES:
        return
    source = queued_event.get("source")
    if not isinstance(source, str) or not source:
        source = "hook"

    # Called under the device lock; acknowledge the queued event only after this.
    with open(PENDING_EVENT_FILE + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"event": event_name}, handle)
    os.replace(PENDING_EVENT_FILE + ".tmp", PENDING_EVENT_FILE)
    _write_state(EVENT_STATES[event_name], source=source)
    _clear_focus_marker()
    if EVENT_STATES[event_name] == "idle":
        _request_idle_refresh()
    if event_name == "Done":
        _write_focus_marker(queued_event)


def _clear_pending_event():
    try:
        os.unlink(PENDING_EVENT_FILE)
    except FileNotFoundError:
        pass


def _deliver_event(event_name):
    """Called under the focus lock; acknowledge only a complete device update."""
    animation = _animation_for_event(event_name)
    if animation is not None:
        display_updated = _start_animation(animation)
        if not display_updated:
            _post_image(image_for_event(event_name))
    else:
        display_updated = _post_image(image_for_event(event_name))
    backlight_updated = _apply_backlight(event_name)
    if display_updated and backlight_updated:
        _clear_pending_event()


def _retry_pending_event():
    try:
        queued = sorted(os.listdir(HOOK_QUEUE_DIR))
    except FileNotFoundError:
        queued = []
    for name in queued:
        if not name.endswith(".json"):
            continue
        path = os.path.join(HOOK_QUEUE_DIR, name)
        with open(path, encoding="utf-8") as handle:
            queued_event = json.load(handle)
        _persist_event(queued_event)
        os.unlink(path)

    try:
        with open(PENDING_EVENT_FILE, encoding="utf-8") as handle:
            pending = json.load(handle)
        event_name = pending.get("event") or _normalize_event_name(pending)
    except (OSError, ValueError, AttributeError):
        return
    if event_name in EVENT_STATES:
        _deliver_event(event_name)


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
        match = re.search(
            r'^\s*"?(?:CFBundleIdentifier|bundleID)"?\s*=\s*"([^"\r\n]+)"',
            info,
            re.MULTILINE,
        )
        return match.group(1) if match else ""
    except Exception:
        return ""


def _antigravity_application_instance():
    """Return a PID identity, an empty string if stopped, or None if unknown."""
    executable_paths = set(_antigravity_executables())
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,comm="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and fields[0].isdigit() and fields[1] in executable_paths:
                return "pid:" + fields[0]
        return ""
    except Exception:
        return None


def _read_app_instance():
    try:
        with open(APP_INSTANCE_FILE, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _write_app_instance(instance):
    temporary = APP_INSTANCE_FILE + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(instance)
        os.replace(temporary, APP_INSTANCE_FILE)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _extract_live_trajectory_state(payload):
    if not isinstance(payload, dict):
        return None
    summaries = payload.get("trajectorySummaries")
    if summaries is None:
        return "none"
    if isinstance(summaries, dict):
        entries = list(summaries.values())
    elif isinstance(summaries, list):
        entries = summaries
    else:
        return "none"

    has_running = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        statuses = []
        for field in ("status", "runStatus", "latestStepStatus", "stepStatus"):
            value = entry.get(field)
            if isinstance(value, str):
                statuses.append(value.upper())
        combined = " ".join(statuses)
        if "WAITING" in combined:
            return "wait"
        if "RUNNING" in combined:
            has_running = True
    return "work" if has_running else "none"


def _poll_live_trajectory_state():
    payload = _call_language_server("GetAllCascadeTrajectories", {}, timeout=1.5)
    return _extract_live_trajectory_state(payload)


def _reconcile_live_state(live_state, had_live_activity):
    if live_state is None:
        return had_live_activity

    current_state, updated_at, source = _read_state_record()
    age = time.time() - updated_at if updated_at > 0 else float("inf")

    if live_state == "wait":
        if current_state != "wait":
            run({"hookEventName": "Wait"}, source="daemon")
        return True

    if live_state == "work":
        if current_state == "wait":
            run({"hookEventName": "Work"}, source="daemon")
        elif current_state in (None, "idle", "done"):
            if source != "hook" or age >= HOOK_GRACE_SECONDS:
                run({"hookEventName": "Work"}, source="daemon")
        return True

    # live_state == "none"
    if current_state == "wait":
        run({"hookEventName": "Cancel"}, source="daemon")
        return False
    if current_state == "work" and had_live_activity:
        if source != "hook" or age >= HOOKLESS_DONE_GRACE_SECONDS:
            run({"hookEventName": "Stop"}, source="daemon")
            return False
    if current_state in (None, "idle", "done"):
        return False
    return had_live_activity


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
    next_idle_refresh_at = 0.0
    last_focus_attempt = 0.0
    last_observed_state = None
    had_live_activity = False
    last_app_instance = _read_app_instance()
    _daemon_log(
        "watcher started previous_app_instance=%s"
        % (last_app_instance or "none")
    )

    while True:
        now = time.monotonic()
        app_instance = _antigravity_application_instance()
        if app_instance is not None and app_instance != last_app_instance:
            if app_instance:
                _daemon_log(
                    "Antigravity application launch detected instance=%s"
                    % app_instance
                )
                had_live_activity = False
                run({"hookEventName": "SessionStart"}, source="daemon")
            else:
                _daemon_log("Antigravity application stopped")
                had_live_activity = False
                if _read_state() in ("work", "wait"):
                    run({"hookEventName": "Cancel"}, source="daemon")
            _write_app_instance(app_instance)
            last_app_instance = app_instance

        if app_instance:
            live_state = _poll_live_trajectory_state()
            had_live_activity = _reconcile_live_state(live_state, had_live_activity)

        _with_focus_lock(_retry_pending_event)
        current_state = _read_state()
        if current_state != last_observed_state:
            if current_state == "idle":
                next_idle_refresh_at = 0.0
                had_live_activity = False
            elif current_state == "done":
                had_live_activity = False
            last_observed_state = current_state

        if os.path.exists(IDLE_REFRESH_MARKER):
            limits = _rate_limits()

            def refresh_requested_idle():
                try:
                    if _read_state() == "idle":
                        return _display_limits(limits)
                    return False
                finally:
                    _clear_idle_refresh_request()

            refreshed = _with_focus_lock(refresh_requested_idle)
            usage_status = (
                "ok"
                if _has_complete_quota(limits)
                else ("partial" if limits is not None else "unavailable")
            )
            _daemon_log(
                "idle refresh completed usage=%s display=%s"
                % (usage_status, bool(refreshed))
            )
            next_idle_refresh_at = time.monotonic() + _next_idle_refresh_delay(
                limits, refresh_seconds, bool(app_instance)
            )
            last_observed_state = _read_state()

        bundle_ids = _antigravity_bundle_ids()
        focus_ready = (
            os.path.exists(FOCUS_MARKER)
            and now - last_focus_attempt >= 10.0
            and _frontmost_bundle_id() in bundle_ids
        )
        if focus_ready:
            last_focus_attempt = now
            limits = _rate_limits()

            def return_to_idle():
                if not os.path.exists(FOCUS_MARKER):
                    return
                if _frontmost_bundle_id() not in bundle_ids:
                    return
                _clear_pending_event()
                _write_state("idle", source="daemon")
                image_updated = _display_limits(limits)
                backlight_updated = _apply_backlight("SessionStart")
                if image_updated and backlight_updated:
                    _clear_focus_marker()

            _with_focus_lock(return_to_idle)
            next_idle_refresh_at = time.monotonic() + _next_idle_refresh_delay(
                limits, refresh_seconds, bool(app_instance)
            )
            last_observed_state = _read_state()

        now = time.monotonic()
        if _read_state() == "idle" and now >= next_idle_refresh_at:
            limits = _rate_limits()

            def refresh_if_still_idle():
                if _read_state() != "idle":
                    return
                _display_limits(limits)

            _with_focus_lock(refresh_if_still_idle)
            next_idle_refresh_at = time.monotonic() + _next_idle_refresh_delay(
                limits, refresh_seconds, bool(app_instance)
            )
        time.sleep(1.0)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--focus-daemon":
        return focus_daemon()
    if len(sys.argv) == 2 and sys.argv[1] == "--refresh-idle":
        def refresh_idle():
            _clear_pending_event()
            _clear_focus_marker()
            _write_state("idle", source="manual")
            updated = _refresh_idle_display()
            _apply_backlight("SessionStart")
            return updated

        updated = _with_focus_lock(refresh_idle)
        return 0 if updated else 1
    try:
        hook_input = json.load(sys.stdin)
        if isinstance(hook_input, dict):
            run(hook_input, source="hook")
    except Exception:
        pass
    print("{}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
