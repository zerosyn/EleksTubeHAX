import datetime
import importlib.util
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "antigravity_ipstube_status.py"
SPEC = importlib.util.spec_from_file_location("antigravity_ipstube_status", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AntigravityIPSTubeStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tempdir = temporary.name
        for attr, name in (
            ("PENDING_EVENT_FILE", "pending.json"),
            ("HOOK_QUEUE_DIR", "events"),
            ("STATE_FILE", "state.json"),
            ("PEER_STATE_FILE", "peer-state.json"),
            ("FOCUS_MARKER", "done"),
            ("FOCUS_LOCK", "focus.lock"),
            ("BACKLIGHT_LOCK", "backlight.lock"),
            ("IDLE_REFRESH_MARKER", "refresh"),
            ("APP_INSTANCE_FILE", "app-instance"),
            ("IDLE_BMP", "idle.bmp"),
            ("IDLE_HASH", "idle.sha256"),
            ("DAEMON_DISCOVERY_DIR", "daemon"),
        ):
            patcher = mock.patch.object(
                MODULE, attr, os.path.join(self.tempdir, name)
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        cache_patcher = mock.patch.object(MODULE, "_CACHED_LS_ENDPOINT", None)
        cache_patcher.start()
        self.addCleanup(cache_patcher.stop)

    def test_defaults_use_screen_one_and_dynamic_image_248(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(MODULE._screen_from_environment(), 1)
        self.assertEqual(MODULE.DYNAMIC_IDLE_IMAGE, 248)
        self.assertEqual(MODULE.IDLE_FALLBACK_IMAGE, 251)

    def test_event_mapping_and_hook_normalization(self):
        self.assertEqual(MODULE.image_for_event("SessionStart"), 251)
        self.assertEqual(MODULE.image_for_event("PreInvocation"), 252)
        self.assertEqual(MODULE.image_for_event("PostToolUse"), 252)
        self.assertEqual(MODULE.image_for_event("PostInvocation"), 252)
        self.assertEqual(MODULE.image_for_event("Wait"), 253)
        self.assertEqual(MODULE.image_for_event("Stop"), 254)
        self.assertIsNone(MODULE.image_for_event("PreToolUse"))

        self.assertEqual(
            MODULE._normalize_event_name(
                {"hookEventName": "Stop", "terminationReason": "USER_CANCELED"}
            ),
            "Cancel",
        )
        self.assertEqual(
            MODULE._normalize_event_name(
                {"hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL"}
            ),
            "Done",
        )

    def test_main_hook_always_prints_empty_json_and_exits_zero(self):
        for raw_stdin in (
            '{"hookEventName":"PreInvocation","conversationId":"conv-1"}',
            "not json",
        ):
            stdout = io.StringIO()
            with (
                self.subTest(raw_stdin=raw_stdin),
                mock.patch.object(MODULE.sys, "argv", ["antigravity_ipstube_status.py"]),
                mock.patch.object(MODULE.sys, "stdin", io.StringIO(raw_stdin)),
                mock.patch.object(MODULE.sys, "stdout", stdout),
                mock.patch.object(MODULE, "_start_animation", return_value=True),
                mock.patch.object(MODULE, "_post_image", return_value=True),
                mock.patch.object(MODULE, "_set_backlight", return_value=True),
            ):
                code = MODULE.main()
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip(), "{}")

    def test_stop_survives_timeout_waiting_for_device_lock(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=TimeoutError),
            mock.patch.object(MODULE, "_write_state") as state,
        ):
            with self.assertRaises(TimeoutError):
                MODULE.run(
                    {
                        "hookEventName": "Stop",
                        "terminationReason": "NO_TOOL_CALL",
                        "conversationId": "conv-1",
                    }
                )
            state.assert_not_called()
        self.assertEqual(len(os.listdir(MODULE.HOOK_QUEUE_DIR)), 1)
        with (
            mock.patch.object(MODULE, "_write_state") as state,
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_write_focus_marker") as marker,
            mock.patch.object(MODULE, "_deliver_event") as deliver,
        ):
            MODULE._retry_pending_event()
            state.assert_called_once_with("done", source="hook")
            marker.assert_called_once()
            deliver.assert_called_once_with("Done")
        self.assertEqual(os.listdir(MODULE.HOOK_QUEUE_DIR), [])

    def test_queued_events_preserve_order_without_saving_tool_arguments(self):
        with mock.patch.object(MODULE, "_with_focus_lock", side_effect=TimeoutError):
            for payload in (
                {
                    "hookEventName": "PreInvocation",
                    "lastUserInput": "secret prompt",
                    "toolCall": {"args": {"CommandLine": "private"}},
                },
                {"hookEventName": "Wait"},
                {"hookEventName": "PostToolUse"},
                {"hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL"},
            ):
                with self.assertRaises(TimeoutError):
                    MODULE.run(payload)
        for path in Path(MODULE.HOOK_QUEUE_DIR).glob("*.json"):
            content = path.read_text()
            self.assertNotIn("secret prompt", content)
            self.assertNotIn("private", content)
        with (
            mock.patch.object(MODULE, "_write_state") as state,
            mock.patch.object(MODULE, "_clear_focus_marker"),
            mock.patch.object(MODULE, "_write_focus_marker"),
            mock.patch.object(MODULE, "_deliver_event") as deliver,
        ):
            MODULE._retry_pending_event()
            self.assertEqual(
                state.call_args_list,
                [
                    mock.call("work", source="hook"),
                    mock.call("wait", source="hook"),
                    mock.call("work", source="hook"),
                    mock.call("done", source="hook"),
                ],
            )
            deliver.assert_called_once_with("Done")

    def test_failed_resume_is_retried_until_animation_and_light_succeed(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
            mock.patch.object(MODULE, "_post_image", return_value=True),
            mock.patch.object(
                MODULE, "_start_animation", side_effect=[False, True, True]
            ) as animation,
            mock.patch.object(
                MODULE, "_set_backlight", side_effect=[False, False, True]
            ) as light,
        ):
            MODULE.run({"hookEventName": "PostToolUse"})
            self.assertTrue(os.path.exists(MODULE.PENDING_EVENT_FILE))
            MODULE._retry_pending_event()
            self.assertTrue(os.path.exists(MODULE.PENDING_EVENT_FILE))
            MODULE._retry_pending_event()
            self.assertFalse(os.path.exists(MODULE.PENDING_EVENT_FILE))
            MODULE._retry_pending_event()
            self.assertEqual(animation.call_args_list, [mock.call("matrix")] * 3)
            self.assertEqual(light.call_args_list, [mock.call("rainbow", None)] * 3)

    def test_cancel_stop_and_wait_animations_match_codex(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
            mock.patch.object(MODULE, "_start_animation", return_value=True) as animation,
            mock.patch.object(MODULE, "_post_image", return_value=True) as image,
            mock.patch.object(MODULE, "_set_backlight", return_value=True) as light,
        ):
            MODULE.run({"hookEventName": "PreInvocation"})
            MODULE.run({"hookEventName": "Wait"}, source="daemon")
            MODULE.run({"hookEventName": "Stop"})
            MODULE.run({"hookEventName": "Stop", "terminationReason": "USER_CANCELED"})

        self.assertEqual(
            animation.call_args_list,
            [mock.call("matrix"), mock.call("swirl"), mock.call("squares")],
        )
        image.assert_called_once_with(251)
        self.assertEqual(
            light.call_args_list,
            [
                mock.call("rainbow", None),
                mock.call("pulse", "#FF8000"),
                mock.call("breath", "#00FF00"),
                mock.call("rainbow", None),
            ],
        )

    def test_backlight_coordination_overwrites_on_wait_done_and_preserves_codex_on_work_idle(
        self,
    ):
        for peer_state in ("wait", "done", "work", "idle", None):
            with self.subTest(peer_state=peer_state):
                if os.path.exists(MODULE.PEER_STATE_FILE):
                    os.unlink(MODULE.PEER_STATE_FILE)
                if peer_state is not None:
                    Path(MODULE.PEER_STATE_FILE).write_text(
                        MODULE.json.dumps({"state": peer_state})
                    )
                with (
                    mock.patch.object(
                        MODULE, "_with_focus_lock", side_effect=lambda cb: cb()
                    ),
                    mock.patch.object(MODULE, "_start_animation", return_value=True),
                    mock.patch.object(MODULE, "_post_image", return_value=True),
                    mock.patch.object(
                        MODULE, "_set_backlight", return_value=True
                    ) as light,
                ):
                    MODULE.run({"hookEventName": "Wait"}, source="daemon")
                    MODULE.run({"hookEventName": "Stop"})
                    MODULE.run({"hookEventName": "PreInvocation"})
                    MODULE.run({"hookEventName": "SessionStart"})
                expected_passive = {
                    "wait": mock.call("pulse", "#FF8000"),
                    "done": mock.call("breath", "#00FF00"),
                }.get(peer_state, mock.call("rainbow", None))
                self.assertEqual(
                    light.call_args_list,
                    [
                        mock.call("pulse", "#FF8000"),
                        mock.call("breath", "#00FF00"),
                        expected_passive,
                        expected_passive,
                    ],
                )

    def test_extracts_four_buckets_and_ignores_legacy_argon_bucket(self):
        payload = {
            "response": {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {
                                "bucketId": "gemini-weekly",
                                "window": "weekly",
                                "remainingFraction": 0.9411773,
                                "resetTime": "2026-11-26T16:28:35Z",
                            },
                            {
                                "bucketId": "gemini-5h",
                                "window": "5h",
                                "remainingFraction": 0.8091205,
                                "resetTime": "2026-11-19T21:28:35.123456789Z",
                            },
                        ],
                    },
                    {
                        "displayName": "Claude and GPT models",
                        "buckets": [
                            {
                                "bucketId": "3p-weekly",
                                "window": "weekly",
                                "remainingFraction": 0.72,
                                "resetTime": "2026-11-26T19:27:37Z",
                            },
                            {
                                "bucketId": "3p-5h",
                                "window": "5h",
                                "remainingFraction": 0.5,
                                "resetTime": "2026-11-20T00:27:37Z",
                            },
                        ],
                    },
                    {
                        "displayName": "Gemini 4 Argon",
                        "buckets": [
                            {
                                "bucketId": "gemini-argon-wtu-weekly",
                                "window": "weekly",
                                "remainingFraction": 0.12,
                                "resetTime": "2026-11-25T08:41:35Z",
                            }
                        ],
                    },
                ]
            }
        }
        limits = MODULE._extract_quota_limits(payload)
        self.assertNotIn("argon_weekly", limits)
        self.assertEqual(limits["gemini_5h"][0], 81)
        self.assertEqual(limits["gemini_weekly"][0], 94)
        self.assertEqual(limits["claude_gpt_5h"][0], 50)
        self.assertEqual(limits["claude_gpt_weekly"][0], 72)

        expected_5h = MODULE._parse_rfc3339_local("2026-11-19T21:28:35Z").strftime("%H:%M")
        expected_wk = MODULE._parse_rfc3339_local("2026-11-26T16:28:35Z").strftime("%m-%d")
        self.assertEqual(limits["gemini_5h"][1], expected_5h)
        self.assertEqual(limits["gemini_weekly"][1], expected_wk)

    def test_proto3_omitted_zero_disabled_buckets_and_missing_reset(self):
        payload = {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "bucketId": "gemini-5h",
                            "resetTime": "2026-11-19T21:00:00Z",
                        },
                        {
                            "bucketId": "gemini-weekly",
                            "remainingFraction": 1.0,
                        },
                        {
                            "bucketId": "gemini-weekly",
                            "remainingFraction": 0.1,
                            "disabled": True,
                        },
                    ],
                },
                {
                    "displayName": "Gemini 4 Argon",
                    "buckets": [
                        {
                            "bucketId": "gemini-argon-wtu-weekly",
                            "remainingFraction": 1,
                        }
                    ],
                },
            ]
        }
        limits = MODULE._extract_quota_limits(payload)
        self.assertNotIn("argon_weekly", limits)
        self.assertEqual(limits["gemini_5h"][0], 0)
        self.assertEqual(limits["gemini_weekly"], (100, "-- --"))

    def test_get_user_status_fallback_extraction(self):
        soon = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=2)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        later = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=5)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "userStatus": {
                "cascadeModelConfigData": {
                    "clientModelConfigs": [
                        {
                            "label": "Gemini 4 Neon",
                            "quotaInfo": {"remainingFraction": 0.82, "resetTime": soon},
                        },
                        {
                            "label": "Gemini 4 Hydrogen",
                            "quotaInfo": {"remainingFraction": 0.91, "resetTime": later},
                        },
                        {
                            "label": "Gemini 4 Argon",
                            "quotaInfo": {"remainingFraction": 0.65, "resetTime": later},
                        },
                        {
                            "label": "Claude Opus 5.5",
                            "quotaInfo": {"remainingFraction": 0.4, "resetTime": soon},
                        },
                        {
                            "label": "GPT-OSS 120B",
                            "quotaInfo": {"remainingFraction": 0.75, "resetTime": later},
                        },
                    ]
                }
            }
        }
        limits = MODULE._extract_quota_limits(payload)
        self.assertNotIn("argon_weekly", limits)
        self.assertEqual(limits["gemini_5h"][0], 82)
        self.assertEqual(limits["gemini_weekly"][0], 91)
        self.assertEqual(limits["claude_gpt_5h"][0], 40)
        self.assertEqual(limits["claude_gpt_weekly"][0], 75)

    def test_usage_query_retries_summary_before_falling_back_to_get_user_status(self):
        full_summary = {
            "response": {
                "groups": [
                    {
                        "buckets": [
                            {
                                "bucketId": "gemini-5h",
                                "remainingFraction": 0.9,
                                "resetTime": "2026-11-19T21:00:00Z",
                            },
                            {
                                "bucketId": "gemini-weekly",
                                "remainingFraction": 0.88,
                                "resetTime": "2026-11-26T16:00:00Z",
                            },
                            {
                                "bucketId": "3p-5h",
                                "remainingFraction": 1.0,
                                "resetTime": "2026-11-19T22:00:00Z",
                            },
                            {
                                "bucketId": "3p-weekly",
                                "remainingFraction": 0.51,
                                "resetTime": "2026-11-26T19:00:00Z",
                            },
                        ]
                    }
                ]
            }
        }
        partial_summary = {
            "response": {
                "groups": [
                    {
                        "buckets": [
                            {
                                "bucketId": "gemini-5h",
                                "remainingFraction": 0.85,
                                "resetTime": "2026-11-19T21:00:00Z",
                            }
                        ]
                    }
                ]
            }
        }

        # Cold-start failure or partial summary retries RetrieveUserQuotaSummary without calling GetUserStatus.
        with (
            mock.patch.object(
                MODULE,
                "_call_language_server",
                side_effect=[None, partial_summary, full_summary],
            ) as call_ls,
            mock.patch.object(MODULE.time, "sleep") as sleep,
        ):
            limits = MODULE._rate_limits()
        self.assertEqual(limits["gemini_5h"][0], 90)
        self.assertEqual(limits["gemini_weekly"][0], 88)
        self.assertEqual(limits["claude_gpt_5h"][0], 100)
        self.assertEqual(limits["claude_gpt_weekly"][0], 51)
        self.assertEqual(
            [c.args[0] for c in call_ls.call_args_list],
            [
                "RetrieveUserQuotaSummary",
                "RetrieveUserQuotaSummary",
                "RetrieveUserQuotaSummary",
            ],
        )
        self.assertEqual(sleep.call_args_list, [mock.call(2), mock.call(2)])

        # Only after all 3 RetrieveUserQuotaSummary attempts fail does GetUserStatus run once as fallback.
        with (
            mock.patch.object(
                MODULE,
                "_call_language_server",
                side_effect=[None, None, None, partial_summary],
            ) as call_ls,
            mock.patch.object(MODULE.time, "sleep") as sleep,
        ):
            fallback_limits = MODULE._rate_limits()
        self.assertEqual(fallback_limits["gemini_5h"][0], 85)
        self.assertEqual(
            [c.args[0] for c in call_ls.call_args_list],
            [
                "RetrieveUserQuotaSummary",
                "RetrieveUserQuotaSummary",
                "RetrieveUserQuotaSummary",
                "GetUserStatus",
            ],
        )
        self.assertEqual(sleep.call_args_list, [mock.call(2), mock.call(2)])

    def test_next_idle_refresh_delay_retries_faster_when_quota_is_incomplete(self):
        complete = {
            "gemini_5h": (83, "05:43"),
            "gemini_weekly": (89, "12-01"),
            "claude_gpt_5h": (100, "06:40"),
            "claude_gpt_weekly": (51, "11-27"),
        }
        partial = {"gemini_5h": (83, "05:43"), "claude_gpt_5h": (100, "06:40")}
        self.assertEqual(MODULE._next_idle_refresh_delay(complete, 300, True), 300)
        self.assertEqual(MODULE._next_idle_refresh_delay(partial, 300, True), 15.0)
        self.assertEqual(MODULE._next_idle_refresh_delay(None, 300, True), 15.0)
        self.assertEqual(MODULE._next_idle_refresh_delay(None, 300, False), 300)

    def test_renders_valid_8bit_bmp_without_white_and_in_expected_order_and_colors(self):
        limits = {
            "gemini_5h": (81, "05:28"),
            "gemini_weekly": (94, "11-27"),
            "claude_gpt_5h": (65, "08:27"),
            "claude_gpt_weekly": (100, "11-27"),
        }
        output = os.path.join(self.tempdir, "idle.bmp")
        with mock.patch.object(
            MODULE, "_draw_status_text", wraps=MODULE._draw_status_text
        ) as draw_text:
            self.assertTrue(MODULE._render_idle_bmp(limits, output))

        self.assertEqual(
            [c.args[1] for c in draw_text.call_args_list],
            [
                "81% 05:28",
                "94% 11-27",
                "65% 08:27",
                "100% 11-27",
            ],
        )
        self.assertEqual([c.args[2] for c in draw_text.call_args_list], [1, 1, 2, 2])
        self.assertEqual(
            [c.args[3] for c in draw_text.call_args_list],
            [44, 90, 152, 198],
        )

        raw = Path(output).read_bytes()
        self.assertEqual(raw[:2], b"BM")
        self.assertLessEqual(len(raw), 102400)
        declared_size, _, _, pixel_offset = struct.unpack_from("<IHHI", raw, 2)
        dib_size, width, height, planes, bpp, comp, _, _, _, clr_used, _ = (
            struct.unpack_from("<IiiHHIIiiII", raw, 14)
        )
        self.assertEqual(declared_size, len(raw))
        self.assertEqual((dib_size, width, height, planes, bpp, comp), (40, 135, 240, 1, 8, 0))
        self.assertEqual(clr_used, 3)
        self.assertEqual(pixel_offset, 14 + 40 + 3 * 4)
        self.assertEqual(len(raw), pixel_offset + 136 * 240)

        palette = [
            struct.unpack_from("<BBBB", raw, 54 + i * 4)[:3][::-1]
            for i in range(clr_used)
        ]
        self.assertEqual(palette[0], (0, 0, 0))
        self.assertNotIn((255, 255, 255), palette)
        self.assertEqual(palette, list(MODULE.QUOTA_PALETTE))

        # Check palette index usage per vertical band in decoded top-down pixel array.
        stride = 136
        rows = [
            raw[pixel_offset + (239 - y) * stride : pixel_offset + (239 - y) * stride + 135]
            for y in range(240)
        ]
        for band_y_start, band_y_end, expected_idx in (
            (28, 58, 1),
            (74, 104, 1),
            (136, 166, 2),
            (182, 212, 2),
        ):
            colors = {px for y in range(band_y_start, band_y_end) for px in rows[y] if px != 0}
            self.assertEqual(colors, {expected_idx})

    def test_extract_live_trajectory_state_prioritizes_waiting_then_running(self):
        self.assertIsNone(MODULE._extract_live_trajectory_state(None))
        self.assertEqual(
            MODULE._extract_live_trajectory_state({"trajectorySummaries": {}}), "none"
        )
        self.assertEqual(
            MODULE._extract_live_trajectory_state(
                {
                    "trajectorySummaries": {
                        "a": {"status": "CASCADE_RUN_STATUS_IDLE"},
                        "b": {"status": "CASCADE_RUN_STATUS_RUNNING"},
                        "c": {"status": "CASCADE_RUN_STATUS_WAITING_FOR_USER"},
                    }
                }
            ),
            "wait",
        )
        self.assertEqual(
            MODULE._extract_live_trajectory_state(
                {
                    "trajectorySummaries": {
                        "a": {"status": "CASCADE_RUN_STATUS_IDLE"},
                        "b": {"status": "CASCADE_RUN_STATUS_RUNNING"},
                    }
                }
            ),
            "work",
        )

    def test_live_state_reconcile_detects_wait_resume_cancel_and_hookless_done(self):
        with (
            mock.patch.object(MODULE, "_with_focus_lock", side_effect=lambda cb: cb()),
            mock.patch.object(MODULE, "_start_animation", return_value=True),
            mock.patch.object(MODULE, "_post_image", return_value=True),
            mock.patch.object(MODULE, "_set_backlight", return_value=True),
        ):
            MODULE._write_state("work", source="hook")
            had = MODULE._reconcile_live_state("wait", False)
            self.assertTrue(had)
            self.assertEqual(MODULE._read_state(), "wait")

            # Approved by user -> resumes work immediately.
            had = MODULE._reconcile_live_state("work", had)
            self.assertTrue(had)
            self.assertEqual(MODULE._read_state(), "work")

            # Wait then user rejects/cancels -> returns to idle.
            had = MODULE._reconcile_live_state("wait", had)
            self.assertEqual(MODULE._read_state(), "wait")
            had = MODULE._reconcile_live_state("none", had)
            self.assertFalse(had)
            self.assertEqual(MODULE._read_state(), "idle")

            # Hookless work -> idle trajectory triggers Done after grace.
            MODULE._write_state("work", source="daemon")
            had = MODULE._reconcile_live_state("none", True)
            self.assertFalse(had)
            self.assertEqual(MODULE._read_state(), "done")
            self.assertTrue(os.path.exists(MODULE.FOCUS_MARKER))

            # Recent Stop hook is not clobbered by stale RUNNING poll within grace window.
            MODULE._write_state("done", source="hook")
            MODULE._reconcile_live_state("work", False)
            self.assertEqual(MODULE._read_state(), "done")

    def test_done_returns_to_idle_only_when_antigravity_is_frontmost(self):
        for bundle_id in ("com.google.antigravity", "com.apple.finder", ""):
            with self.subTest(bundle_id=bundle_id):
                Path(MODULE.FOCUS_MARKER).touch()
                MODULE._write_state("done", source="hook")
                with (
                    mock.patch.object(MODULE, "_read_app_instance", return_value="pid:1"),
                    mock.patch.object(
                        MODULE, "_antigravity_application_instance", return_value="pid:1"
                    ),
                    mock.patch.object(
                        MODULE, "_poll_live_trajectory_state", return_value="none"
                    ),
                    mock.patch.object(
                        MODULE, "_frontmost_bundle_id", return_value=bundle_id
                    ),
                    mock.patch.object(
                        MODULE, "_with_focus_lock", side_effect=lambda cb: cb()
                    ),
                    mock.patch.object(MODULE, "_rate_limits", return_value=None),
                    mock.patch.object(
                        MODULE, "_display_limits", return_value=True
                    ) as display,
                    mock.patch.object(
                        MODULE, "_set_backlight", return_value=True
                    ) as light,
                    mock.patch.object(MODULE, "_daemon_log"),
                    mock.patch.object(MODULE.time, "monotonic", return_value=100),
                    mock.patch.object(MODULE.time, "sleep", side_effect=StopIteration),
                ):
                    with self.assertRaises(StopIteration):
                        MODULE.focus_daemon()
                if bundle_id == "com.google.antigravity":
                    self.assertEqual(MODULE._read_state(), "idle")
                    display.assert_called_once_with(None)
                    light.assert_called_once_with("rainbow", None)
                    self.assertFalse(os.path.exists(MODULE.FOCUS_MARKER))
                else:
                    self.assertEqual(MODULE._read_state(), "done")
                    display.assert_not_called()
                    light.assert_not_called()
                    self.assertTrue(os.path.exists(MODULE.FOCUS_MARKER))

    def test_example_hooks_config_uses_official_antigravity_schema(self):
        config = MODULE.json.loads(
            SCRIPT.with_name("antigravity_ipstube_hooks.example.json").read_text()
        )
        group = config["ipstube-status"]
        for flat_event in ("SessionStart", "PreInvocation", "Stop"):
            handler = group[flat_event][0]
            self.assertEqual(handler["type"], "command")
            self.assertIn("antigravity_ipstube_status.py", handler["command"])
            self.assertLessEqual(handler["timeout"], 3)
        post_tool = group["PostToolUse"][0]
        self.assertEqual(post_tool["matcher"], "*")
        self.assertIn("antigravity_ipstube_status.py", post_tool["hooks"][0]["command"])
        self.assertNotIn("PreToolUse", group)

    def test_discover_endpoints_reads_live_daemon_file_and_skips_stale_pid(self):
        daemon_dir = Path(MODULE.DAEMON_DISCOVERY_DIR)
        daemon_dir.mkdir(parents=True, exist_ok=True)
        live_pid = os.getpid()
        stale_pid = 999999

        other_file = daemon_dir / "sidecar_11111.json"
        other_file.write_text(
            MODULE.json.dumps(
                {
                    "pid": live_pid,
                    "httpPort": 11111,
                    "httpsPort": 11112,
                    "csrfToken": "other-token",
                }
            )
        )
        hub_file = daemon_dir / "hub_64738.json"
        hub_file.write_text(
            MODULE.json.dumps(
                {
                    "pid": live_pid,
                    "httpPort": 64738,
                    "httpsPort": 64737,
                    "csrfToken": "hub-token",
                }
            )
        )
        stale_file = daemon_dir / "hub_99999.json"
        stale_file.write_text(
            MODULE.json.dumps(
                {
                    "pid": stale_pid,
                    "httpPort": 60000,
                    "httpsPort": 60001,
                    "csrfToken": "stale-token",
                }
            )
        )

        with (
            mock.patch.object(
                MODULE,
                "_pid_is_running",
                side_effect=lambda pid: int(pid) == live_pid,
            ),
            mock.patch.object(MODULE, "_discover_ps_endpoints", return_value=[]),
        ):
            endpoints = MODULE._discover_endpoints()

        self.assertEqual(
            endpoints,
            [
                (str(live_pid), "http://127.0.0.1:64738", "hub-token"),
                (str(live_pid), "https://127.0.0.1:64737", "hub-token"),
                (str(live_pid), "http://127.0.0.1:11111", "other-token"),
                (str(live_pid), "https://127.0.0.1:11112", "other-token"),
            ],
        )

    def test_gemini_group_description_mentioning_argon_is_not_dropped(self):
        payload = {
            "response": {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "description": (
                            "Models within this group: Gemini 4 Neon, Gemini 4 Carbon, "
                            "Gemini 4 Argon, Gemini 4 Hydrogen, Gemini 3.8 Flash"
                        ),
                        "buckets": [
                            {
                                "bucketId": "gemini-weekly",
                                "displayName": "Weekly Limit Remaining",
                                "window": "weekly",
                                "remainingFraction": 0.9806805,
                                "resetTime": "2026-12-01T11:43:42Z",
                            },
                            {
                                "bucketId": "gemini-5h",
                                "displayName": "Five Hour Limit Remaining",
                                "window": "5h",
                                "remainingFraction": 0.92272204,
                                "resetTime": "2026-11-24T16:43:42Z",
                            },
                        ],
                    }
                ]
            }
        }
        limits = MODULE._extract_quota_limits(payload)
        self.assertEqual(limits["gemini_weekly"][0], 98)
        self.assertEqual(limits["gemini_5h"][0], 92)
        self.assertNotIn("argon_weekly", limits)


if __name__ == "__main__":
    unittest.main()
