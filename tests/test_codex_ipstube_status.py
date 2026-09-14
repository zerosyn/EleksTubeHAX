import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "codex_ipstube_status.py"
SPEC = importlib.util.spec_from_file_location("codex_ipstube_status", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CodexIPSTubeStatusTests(unittest.TestCase):
    def test_event_mapping(self):
        self.assertEqual(MODULE.image_for_event("SessionStart"), 251)
        self.assertEqual(MODULE.image_for_event("UserPromptSubmit"), 252)
        self.assertEqual(MODULE.image_for_event("PermissionRequest"), 253)
        self.assertEqual(MODULE.image_for_event("PostToolUse"), 252)
        self.assertEqual(MODULE.image_for_event("Stop"), 254)
        self.assertIsNone(MODULE.image_for_event("PreToolUse"))

    @mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda callback: callback())
    @mock.patch.object(MODULE, "_set_backlight")
    @mock.patch.object(MODULE, "_start_animation", return_value=True)
    @mock.patch.object(MODULE, "_post_image")
    @mock.patch.object(MODULE, "_clear_focus_marker")
    @mock.patch.object(MODULE, "_write_state")
    def test_permission_request_starts_wait_animation(
        self,
        write_state,
        clear_focus_marker,
        post_image,
        start_animation,
        set_backlight,
        with_focus_lock,
    ):
        self.assertEqual(MODULE.run({"hook_event_name": "PermissionRequest"}), 0)
        write_state.assert_called_once_with("wait")
        clear_focus_marker.assert_called_once_with()
        start_animation.assert_called_once_with("swirl")
        post_image.assert_not_called()
        set_backlight.assert_called_once_with("pulse", "#FF8000")

    @mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda callback: callback())
    @mock.patch.object(MODULE, "_set_backlight")
    @mock.patch.object(MODULE, "_post_image")
    @mock.patch.object(MODULE, "_request_idle_refresh")
    @mock.patch.object(MODULE, "_clear_focus_marker")
    @mock.patch.object(MODULE, "_write_state")
    def test_session_start_requests_usage_refresh(
        self,
        write_state,
        clear_focus_marker,
        request_idle_refresh,
        post_image,
        set_backlight,
        with_focus_lock,
    ):
        self.assertEqual(MODULE.run({"hook_event_name": "SessionStart"}), 0)
        write_state.assert_called_once_with("idle")
        clear_focus_marker.assert_called_once_with()
        request_idle_refresh.assert_called_once_with()
        post_image.assert_called_once_with(MODULE.IDLE_FALLBACK_IMAGE)
        set_backlight.assert_called_once_with("rainbow", None)

    @mock.patch.object(MODULE, "_with_focus_lock")
    def test_unsupported_event_is_a_no_op(self, with_focus_lock):
        self.assertEqual(MODULE.run({"hook_event_name": "PreToolUse"}), 0)
        with_focus_lock.assert_not_called()

    def test_focus_daemon_consumes_startup_refresh_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_file = os.path.join(temporary, "state.json")
            refresh_marker = os.path.join(temporary, "refresh")
            focus_marker = os.path.join(temporary, "done")
            focus_lock = os.path.join(temporary, "focus.lock")
            codex_instance_file = os.path.join(temporary, "codex-instance")
            with open(state_file, "w", encoding="utf-8") as handle:
                handle.write('{"state":"idle","updated_at":1}')
            with open(refresh_marker, "w", encoding="ascii") as handle:
                handle.write("1")

            with (
                mock.patch.object(MODULE, "STATE_FILE", state_file),
                mock.patch.object(MODULE, "IDLE_REFRESH_MARKER", refresh_marker),
                mock.patch.object(MODULE, "FOCUS_MARKER", focus_marker),
                mock.patch.object(MODULE, "FOCUS_LOCK", focus_lock),
                mock.patch.object(MODULE, "CODEX_INSTANCE_FILE", codex_instance_file),
                mock.patch.object(MODULE, "_codex_application_instance", return_value=""),
                mock.patch.object(MODULE, "_daemon_log"),
                mock.patch.object(
                    MODULE,
                    "_rate_limits",
                    return_value={
                        "five_hour": (96, "03:34"),
                        "weekly": (94, "09-19"),
                    },
                ) as rate_limits,
                mock.patch.object(
                    MODULE, "_display_limits", return_value=True
                ) as display_limits,
                mock.patch.object(MODULE.time, "sleep", side_effect=StopIteration),
            ):
                with self.assertRaises(StopIteration):
                    MODULE.focus_daemon()

            rate_limits.assert_called_once_with()
            display_limits.assert_called_once_with(
                {"five_hour": (96, "03:34"), "weekly": (94, "09-19")}
            )
            self.assertFalse(os.path.exists(refresh_marker))

    def test_extracts_five_hour_and_weekly_limits_by_duration(self):
        reset = 1789412092
        result = {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": 4,
                        "windowDurationMins": 300,
                        "resetsAt": reset,
                    },
                    "secondary": {
                        "usedPercent": 6,
                        "windowDurationMins": 10080,
                        "resetsAt": reset,
                    },
                }
            }
        }
        limits = MODULE._extract_rate_limits(result)
        self.assertEqual(limits["five_hour"][0], 96)
        self.assertEqual(limits["weekly"][0], 94)
        self.assertEqual(
            limits["five_hour"][1],
            MODULE.datetime.datetime.fromtimestamp(reset).strftime("%H:%M"),
        )
        self.assertEqual(
            limits["weekly"][1],
            MODULE.datetime.datetime.fromtimestamp(reset).strftime("%m-%d"),
        )

    def test_extracts_limits_when_primary_and_secondary_are_reversed(self):
        result = {
            "rateLimits": {
                "primary": {
                    "usedPercent": 25,
                    "windowDurationMins": 10080,
                    "resetsAt": 1789811716,
                },
                "secondary": {
                    "usedPercent": 40,
                    "windowDurationMins": 300,
                    "resetsAt": 1789412092,
                },
            }
        }
        limits = MODULE._extract_rate_limits(result)
        self.assertEqual(limits["five_hour"][0], 60)
        self.assertEqual(limits["weekly"][0], 75)

    def test_renders_both_limits_at_one_hundred_percent(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = os.path.join(temporary, "idle.bmp")
            with mock.patch.object(
                MODULE, "_draw_status_text", wraps=MODULE._draw_status_text
            ) as draw_status_text:
                self.assertTrue(
                    MODULE._render_idle_bmp(
                        {
                            "five_hour": (100, "03:34"),
                            "weekly": (100, "09-19"),
                        },
                        output,
                    )
                )
            self.assertEqual(draw_status_text.call_args_list[0].args[1], "100% 03:34")
            self.assertEqual(draw_status_text.call_args_list[1].args[1], "100% 09-19")
            self.assertGreater(os.path.getsize(output), 0)

    @mock.patch.object(MODULE, "_daemon_log")
    @mock.patch.object(MODULE.time, "sleep", side_effect=StopIteration)
    @mock.patch.object(MODULE, "_read_state", return_value="work")
    @mock.patch.object(MODULE, "run")
    @mock.patch.object(MODULE, "_write_codex_instance")
    @mock.patch.object(MODULE, "_read_codex_instance", return_value="")
    @mock.patch.object(MODULE, "_codex_application_instance", return_value="pid:40566")
    def test_focus_daemon_treats_new_codex_instance_as_session_start(
        self,
        codex_application_instance,
        read_codex_instance,
        write_codex_instance,
        run,
        read_state,
        sleep,
        daemon_log,
    ):
        with self.assertRaises(StopIteration):
            MODULE.focus_daemon()
        run.assert_called_once_with({"hook_event_name": "SessionStart"})
        write_codex_instance.assert_called_once_with("pid:40566")

    @mock.patch.object(MODULE.subprocess, "run")
    def test_codex_application_instance_uses_main_process_id(self, run):
        run.return_value = mock.Mock(
            returncode=0,
            stdout=(
                "31393 /some/helper/ChatGPT for Chrome\n"
                "40566 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT\n"
            ),
        )
        self.assertEqual(MODULE._codex_application_instance(), "pid:40566")
        self.assertEqual(
            run.call_args.args[0], ["/bin/ps", "-axo", "pid=,comm="]
        )

    @mock.patch.object(MODULE.sys, "stdin", io.StringIO("not json"))
    def test_invalid_stdin_exits_successfully(self):
        self.assertEqual(MODULE.main(), 0)


if __name__ == "__main__":
    unittest.main()
