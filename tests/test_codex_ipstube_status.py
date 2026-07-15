import importlib.util
import io
import json
import os
from pathlib import Path
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

    @mock.patch.dict(
        os.environ,
        {"IPSTUBE_URL": "http://ipstube.local/", "IPSTUBE_STATUS_SCREEN": "4"},
        clear=True,
    )
    @mock.patch("urllib.request.urlopen")
    def test_posts_generic_display_request(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{}'
        result = MODULE.run({"hook_event_name": "PermissionRequest"})
        self.assertEqual(result, 0)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ipstube.local/api/display")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(json.loads(request.data), {"screen": 4, "image": 253, "save": False})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 0.5)

    @mock.patch.dict(os.environ, {"IPSTUBE_URL": "http://offline"}, clear=True)
    @mock.patch("urllib.request.urlopen", side_effect=OSError("offline"))
    def test_network_failure_does_not_block_codex(self, urlopen):
        self.assertEqual(MODULE.run({"hook_event_name": "Stop"}), 0)
        urlopen.assert_called_once()

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("urllib.request.urlopen")
    def test_missing_url_is_a_no_op(self, urlopen):
        self.assertEqual(MODULE.run({"hook_event_name": "Stop"}), 0)
        urlopen.assert_not_called()

    @mock.patch.dict(os.environ, {"IPSTUBE_URL": "http://device"}, clear=True)
    @mock.patch("urllib.request.urlopen")
    def test_unsupported_event_is_a_no_op(self, urlopen):
        self.assertEqual(MODULE.run({"hook_event_name": "PreToolUse"}), 0)
        urlopen.assert_not_called()

    @mock.patch.object(MODULE.sys, "stdin", io.StringIO("not json"))
    def test_invalid_stdin_exits_successfully(self):
        self.assertEqual(MODULE.main(), 0)


if __name__ == "__main__":
    unittest.main()
