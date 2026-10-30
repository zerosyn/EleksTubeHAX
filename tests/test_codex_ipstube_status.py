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
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = mock.patch.object(
            MODULE, "PENDING_EVENT_FILE", os.path.join(temporary.name, "pending.json")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        queue_patcher = mock.patch.object(
            MODULE, "HOOK_QUEUE_DIR", os.path.join(temporary.name, "events")
        )
        queue_patcher.start()
        self.addCleanup(queue_patcher.stop)

    def test_stop_survives_timeout_waiting_for_device_lock(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=TimeoutError),
            mock.patch.object(MODULE, "_write_state") as state,
        ):
            with self.assertRaises(TimeoutError):
                MODULE.run({"hook_event_name": "Stop", "turn_id": "ended", "session_id": "session"})
            state.assert_not_called()
        self.assertEqual(len(os.listdir(MODULE.HOOK_QUEUE_DIR)), 1)
        with (
            mock.patch.object(MODULE, "_write_state") as state,
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_write_focus_marker") as marker,
            mock.patch.object(MODULE, "_deliver_event") as deliver,
        ):
            MODULE._retry_pending_event()
            state.assert_called_once_with("done")
            marker.assert_called_once_with({"hook_event_name": "Stop", "turn_id": "ended", "session_id": "session"})
            deliver.assert_called_once_with("Stop")
        self.assertEqual(os.listdir(MODULE.HOOK_QUEUE_DIR), [])

    def test_queued_events_preserve_order_without_saving_tool_arguments(self):
        with mock.patch.object(MODULE, "_with_focus_lock", side_effect=TimeoutError):
            for event in ("PermissionRequest", "PostToolUse", "Stop"):
                with self.assertRaises(TimeoutError):
                    MODULE.run({"hook_event_name": event, "tool_input": {"command": "private"}})
        for path in Path(MODULE.HOOK_QUEUE_DIR).glob("*.json"):
            self.assertNotIn("private", path.read_text())
        with (
            mock.patch.object(MODULE, "_write_state") as state,
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_write_focus_marker"),
            mock.patch.object(MODULE, "_deliver_event") as deliver,
        ):
            MODULE._retry_pending_event()
            self.assertEqual(state.call_args_list, [mock.call("wait"), mock.call("work"), mock.call("done")])
            deliver.assert_called_once_with("Stop")

    def test_event_stays_queued_until_state_is_persisted(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
            mock.patch.object(MODULE, "_write_state", side_effect=TimeoutError),
        ):
            with self.assertRaises(TimeoutError):
                MODULE.run({"hook_event_name": "Stop"})
        self.assertEqual(len(os.listdir(MODULE.HOOK_QUEUE_DIR)), 1)
        with (
            mock.patch.object(MODULE, "_write_state"),
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_write_focus_marker"),
            mock.patch.object(MODULE, "_deliver_event") as deliver,
        ):
            MODULE._retry_pending_event()
            deliver.assert_called_once_with("Stop")
        self.assertEqual(os.listdir(MODULE.HOOK_QUEUE_DIR), [])

    def test_failed_resume_is_retried_until_animation_and_light_succeed(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
            mock.patch.object(MODULE, "_write_state"),
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_post_image", return_value=True),
            mock.patch.object(MODULE, "_start_animation", side_effect=[False, True, True]) as animation,
            mock.patch.object(MODULE, "_set_backlight", side_effect=[False, False, True]) as light,
        ):
            MODULE.run({"hook_event_name": "PostToolUse"})
            self.assertTrue(os.path.exists(MODULE.PENDING_EVENT_FILE))
            MODULE._retry_pending_event()
            self.assertTrue(os.path.exists(MODULE.PENDING_EVENT_FILE))
            MODULE._retry_pending_event()
            self.assertFalse(os.path.exists(MODULE.PENDING_EVENT_FILE))
            MODULE._retry_pending_event()
            self.assertEqual(animation.call_args_list, [mock.call("matrix")] * 3)
            self.assertEqual(light.call_args_list, [mock.call("rainbow", None)] * 3)

    def test_resume_replaces_pending_wait_even_if_hook_is_interrupted(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
            mock.patch.object(MODULE, "_write_state"),
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_deliver_event", side_effect=TimeoutError),
        ):
            for event in ("PermissionRequest", "PostToolUse"):
                with self.assertRaises(TimeoutError):
                    MODULE.run({"hook_event_name": event})
        with mock.patch.object(MODULE, "_deliver_event") as deliver:
            MODULE._retry_pending_event()
            deliver.assert_called_once_with("PostToolUse")

    def test_event_mapping(self):
        self.assertEqual(MODULE.image_for_event("SessionStart"), 251)
        self.assertEqual(MODULE.image_for_event("Interrupt"), 251)
        self.assertEqual(MODULE.image_for_event("UserPromptSubmit"), 252)
        self.assertEqual(MODULE.image_for_event("PermissionRequest"), 253)
        self.assertEqual(MODULE.image_for_event("PostToolUse"), 252)
        self.assertEqual(MODULE.image_for_event("Stop"), 254)
        self.assertIsNone(MODULE.image_for_event("PreToolUse"))

    def test_usage_query_retries_failure_and_stops_on_success(self):
        limits = {"five_hour": (91, "02:55"), "weekly": (91, "11-05")}
        for failures in (0, 1, 2):
            with (
                self.subTest(failures=failures),
                mock.patch.object(MODULE, "_read_rate_limits", side_effect=[None] * failures + [limits]) as query,
                mock.patch.object(MODULE.time, "sleep") as sleep,
            ):
                self.assertEqual(MODULE._rate_limits(), limits)
                self.assertEqual(query.call_count, failures + 1)
                self.assertEqual(sleep.call_args_list, [mock.call(2)] * failures)

    def test_usage_query_gives_up_after_three_attempts(self):
        with (
            mock.patch.object(MODULE, "_read_rate_limits", return_value=None) as query,
            mock.patch.object(MODULE.time, "sleep") as sleep,
        ):
            self.assertIsNone(MODULE._rate_limits())
            self.assertEqual(query.call_count, 3)
            self.assertEqual(sleep.call_args_list, [mock.call(2), mock.call(2)])

    def test_usage_retry_does_not_replace_work_with_idle_display(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def query():
                calls.append(True)
                if len(calls) == 1:
                    MODULE._write_state("work")
                    return None
                return {"five_hour": (91, "02:55")}

            def sleep(seconds):
                if seconds == 1.0:
                    raise StopIteration

            with (
                mock.patch.object(MODULE, "STATE_FILE", os.path.join(directory, "state")),
                mock.patch.object(MODULE, "IDLE_REFRESH_MARKER", os.path.join(directory, "refresh")),
                mock.patch.object(MODULE, "FOCUS_MARKER", os.path.join(directory, "done")),
                mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
                mock.patch.object(MODULE, "_read_codex_instance", return_value="pid:1"),
                mock.patch.object(MODULE, "_codex_application_instance", return_value="pid:1"),
                mock.patch.object(MODULE, "_read_rate_limits", side_effect=query),
                mock.patch.object(MODULE, "_display_limits") as display,
                mock.patch.object(MODULE, "_daemon_log"),
                mock.patch.object(MODULE.time, "sleep", side_effect=sleep),
            ):
                MODULE._write_state("idle")
                MODULE._request_idle_refresh()
                with self.assertRaises(StopIteration):
                    MODULE.focus_daemon()
                self.assertEqual(len(calls), 2)
                self.assertEqual(MODULE._read_state(), "work")
                display.assert_not_called()

    def test_automatic_review_keeps_work_and_retries_work_instead_of_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory, "transcript.jsonl")
            transcript.write_text(MODULE.json.dumps({
                "type": "turn_context",
                "payload": {"turn_id": "current", "approvals_reviewer": "auto_review"},
            }) + '\n{"type":"response_item","payload":{}}\n')
            with (
                mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
                mock.patch.object(MODULE, "_write_state") as state,
                mock.patch.object(MODULE, "_clear_focus_marker"),
                mock.patch.object(MODULE, "_start_animation", side_effect=[False, True]) as animation,
                mock.patch.object(MODULE, "_post_image", return_value=True),
                mock.patch.object(MODULE, "_set_backlight", side_effect=[False, True]) as light,
            ):
                MODULE.run({
                    "hook_event_name": "PermissionRequest", "permission_mode": "default",
                    "turn_id": "current", "transcript_path": str(transcript),
                })
                state.assert_called_once_with("work")
                self.assertTrue(os.path.exists(MODULE.PENDING_EVENT_FILE))
                MODULE._retry_pending_event()
                self.assertFalse(os.path.exists(MODULE.PENDING_EVENT_FILE))
                self.assertEqual(animation.call_args_list, [mock.call("matrix")] * 2)
                self.assertEqual(light.call_args_list, [mock.call("rainbow", None)] * 2)

    def test_reviewer_detection_uses_latest_turn_and_defaults_to_manual_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory, "transcript.jsonl")
            auto = {"type": "turn_context", "payload": {
                "turn_id": "old", "approvals_reviewer": "auto_review",
            }}
            for payload in (
                {"turn_id": "current", "approvals_reviewer": "user"},
                {"turn_id": "other", "approvals_reviewer": "auto_review"},
                {"turn_id": "current"},
                None,
            ):
                with self.subTest(payload=payload):
                    transcript.write_text('\n'.join(MODULE.json.dumps(item) for item in (
                        auto, {"type": "turn_context", "payload": payload},
                    )) + '\n{"type":"turn_context"')
                    self.assertFalse(MODULE._uses_auto_review({
                        "turn_id": "current", "transcript_path": str(transcript),
                    }))
            for path in (None, "", str(transcript) + ".missing", directory):
                with self.subTest(path=path):
                    self.assertFalse(MODULE._uses_auto_review({"transcript_path": path}))

    def test_interrupt_clears_work_wait_and_done_and_retries_idle_delivery(self):
        for previous in ("work", "wait", "done"):
            with self.subTest(previous=previous), tempfile.TemporaryDirectory() as directory:
                with (
                    mock.patch.object(MODULE, "STATE_FILE", os.path.join(directory, "state")),
                    mock.patch.object(MODULE, "FOCUS_MARKER", os.path.join(directory, "done")),
                    mock.patch.object(MODULE, "FOCUS_LOCK", os.path.join(directory, "lock")),
                    mock.patch.object(MODULE, "IDLE_REFRESH_MARKER", os.path.join(directory, "refresh")),
                    mock.patch.object(MODULE, "_post_image", side_effect=[False, True]) as image,
                    mock.patch.object(MODULE, "_set_backlight", side_effect=[False, True]) as light,
                    mock.patch.object(MODULE, "_start_animation") as animation,
                ):
                    MODULE._write_state(previous)
                    MODULE._write_focus_marker({"turn_id": "old-turn"})
                    Path(MODULE.PENDING_EVENT_FILE).write_text('{"hook_event_name":"PermissionRequest"}')
                    self.assertEqual(MODULE.run({"hook_event_name": "Interrupt"}), 0)
                    self.assertEqual(MODULE._read_state(), "idle")
                    self.assertFalse(os.path.exists(MODULE.FOCUS_MARKER))
                    self.assertTrue(os.path.exists(MODULE.IDLE_REFRESH_MARKER))
                    self.assertTrue(os.path.exists(MODULE.PENDING_EVENT_FILE))
                    MODULE._retry_pending_event()
                    self.assertFalse(os.path.exists(MODULE.PENDING_EVENT_FILE))
                    self.assertEqual(image.call_args_list, [mock.call(251)] * 2)
                    self.assertEqual(light.call_args_list, [mock.call("rainbow", None)] * 2)
                    animation.assert_not_called()

    def test_example_config_registers_interrupt(self):
        config = MODULE.json.loads(SCRIPT.with_name("codex_ipstube_hooks.example.json").read_text())
        hook = config["hooks"]["Interrupt"][0]["hooks"][0]
        self.assertEqual(hook["type"], "command")
        self.assertIn("codex_ipstube_status.py", hook["command"])
        self.assertLessEqual(hook["timeout"], 3)

    @mock.patch.object(MODULE.subprocess, "run")
    def test_frontmost_bundle_id_accepts_macos_output_formats(self, run):
        for output, expected in (
            ('"CFBundleIdentifier"="com.openai.codex"', "com.openai.codex"),
            ('[ NULL ] ASN:0x0-0x2f12f1: (in front)\n    bundleID="com.openai.codex"\n', "com.openai.codex"),
            ('    bundleID = "com.apple.finder"\n', "com.apple.finder"),
            ('    bundleID=[ NULL ]\n', ""),
        ):
            with self.subTest(output=output):
                run.side_effect = [
                    mock.Mock(stdout="ASN:0x0-0x2f12f1:"),
                    mock.Mock(stdout=output),
                ]
                self.assertEqual(MODULE._frontmost_bundle_id(), expected)

    def test_done_returns_to_idle_only_when_codex_is_frontmost(self):
        for bundle_id in ("com.openai.codex", "com.apple.finder", ""):
            with self.subTest(bundle_id=bundle_id), tempfile.TemporaryDirectory() as directory:
                marker = os.path.join(directory, "done")
                Path(marker).touch()
                with (
                    mock.patch.object(MODULE, "FOCUS_MARKER", marker),
                    mock.patch.object(MODULE, "IDLE_REFRESH_MARKER", os.path.join(directory, "refresh")),
                    mock.patch.object(MODULE, "_read_codex_instance", return_value="pid:1"),
                    mock.patch.object(MODULE, "_codex_application_instance", return_value="pid:1"),
                    mock.patch.object(MODULE, "_frontmost_bundle_id", return_value=bundle_id),
                    mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
                    mock.patch.object(MODULE, "_read_state", return_value="done"),
                    mock.patch.object(MODULE, "_write_state") as write_state,
                    mock.patch.object(MODULE, "_rate_limits", return_value=None),
                    mock.patch.object(MODULE, "_display_limits", return_value=True) as display,
                    mock.patch.object(MODULE, "_set_backlight", return_value=True) as light,
                    mock.patch.object(MODULE, "_daemon_log"),
                    mock.patch.object(MODULE.time, "monotonic", return_value=100),
                    mock.patch.object(MODULE.time, "sleep", side_effect=StopIteration),
                ):
                    with self.assertRaises(StopIteration):
                        MODULE.focus_daemon()
                if bundle_id == "com.openai.codex":
                    write_state.assert_called_once_with("idle")
                    display.assert_called_once_with(None)
                    light.assert_called_once_with("rainbow", None)
                    self.assertFalse(os.path.exists(marker))
                else:
                    write_state.assert_not_called()
                    display.assert_not_called()
                    light.assert_not_called()
                    self.assertTrue(os.path.exists(marker))

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

    @mock.patch.object(MODULE.subprocess, "run")
    def test_instance_probe_distinguishes_failure_from_stopped(self, run):
        for result in (mock.Mock(returncode=1, stdout=""), TimeoutError("timeout")):
            with self.subTest(result=result):
                run.reset_mock()
                run.side_effect = [result]
                self.assertIsNone(MODULE._codex_application_instance())
                self.assertEqual(run.call_count, 1)
        run.side_effect = [mock.Mock(returncode=0, stdout="123 /other/app\n")]
        self.assertEqual(MODULE._codex_application_instance(), "")

    def test_instance_detection_does_not_reset_status_on_probe_failure_or_migration(self):
        for previous, observations, expected_events, expected_writes in (
            ("pid:1", [None, "pid:1"], 0, []),
            ("pid:1", [None, "pid:2"], 1, [mock.call("pid:2")]),
            ("pid:1", ["", "pid:2"], 1, [mock.call(""), mock.call("pid:2")]),
            ('ASN:0x0-0x123-"ChatGPT":', [None, "pid:1"], 0, [mock.call("pid:1")]),
        ):
            with self.subTest(previous=previous, observations=observations), tempfile.TemporaryDirectory() as directory:
                with (
                    mock.patch.object(MODULE, "FOCUS_MARKER", os.path.join(directory, "done")),
                    mock.patch.object(MODULE, "IDLE_REFRESH_MARKER", os.path.join(directory, "refresh")),
                    mock.patch.object(MODULE, "_read_codex_instance", return_value=previous),
                    mock.patch.object(MODULE, "_codex_application_instance", side_effect=observations),
                    mock.patch.object(MODULE, "_write_codex_instance") as write_instance,
                    mock.patch.object(MODULE, "run") as run,
                    mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
                    mock.patch.object(MODULE, "_read_state", return_value="work"),
                    mock.patch.object(MODULE, "_daemon_log"),
                    mock.patch.object(MODULE.time, "sleep", side_effect=[None, StopIteration]),
                ):
                    with self.assertRaises(StopIteration):
                        MODULE.focus_daemon()
                self.assertEqual(run.call_args_list, [mock.call({"hook_event_name": "SessionStart"})] * expected_events)
                self.assertEqual(write_instance.call_args_list, expected_writes)


if __name__ == "__main__":
    unittest.main()
