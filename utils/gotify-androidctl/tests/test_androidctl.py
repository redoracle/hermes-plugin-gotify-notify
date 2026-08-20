#!/usr/bin/env python3
"""Regression tests for the ADB/UI safety boundary (stdlib unittest only)."""
import importlib.machinery
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader("gotify_androidctl", str(ROOT / "gotify-androidctl.py"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = MODULE
LOADER.exec_module(MODULE)


class AdbHarness(MODULE.ADB):
    def __init__(self):
        self.settings = types.SimpleNamespace(dry_run=False, android_user=0)
        self.calls = []
        self.responses = []

    def base(self, select_device=True):
        return ["adb", "-s", "test-device"]

    def user_args(self):
        return ["--user", "0"]

    def shell(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self.responses:
            return self.responses.pop(0)
        return subprocess.CompletedProcess(args, 0, "", "")


class AndroidCtlTests(unittest.TestCase):
    def test_channel_page_preflight_requires_semantic_title(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.ui = types.SimpleNamespace(has_visible_text=mock.Mock(side_effect=lambda rx: bool(MODULE.re.search(rx, "Normal priority messages (4–7)", MODULE.re.I))))
        self.assertTrue(controller.preflight_channel_page("normal"))
        self.assertFalse(controller.preflight_channel_page("high"))

    def test_configure_refuses_taps_when_channel_preflight_mismatches(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.channel_id = lambda app, cls: "5::gotify_messages_default_importance"
        controller.settings = types.SimpleNamespace(package="com.github.gotify", ui_wait=0.0)
        controller.console = types.SimpleNamespace(warning=lambda *a, **k: None)
        controller.adb = types.SimpleNamespace(open_channel_settings=lambda *args: True)
        controller.ui = types.SimpleNamespace(
            failure_artifacts=mock.Mock(),
        )
        controller.preflight_channel_page = lambda cls: False
        controller.ui_labels = lambda: self.fail("labels must not be read after preflight mismatch")
        app = MODULE.AppSpec(key="pager", name="PAGER", app_id=5)
        self.assertFalse(controller.configure_channel_ui(app, "normal", MODULE.ChannelPolicy(sound="pager.ogg", vibration=False)))
        controller.ui.failure_artifacts.assert_called_once()

    def test_postcondition_requires_zero_drift_for_exact_channel(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.channel_id = lambda app, cls: "5::gotify_messages_default_importance"
        controller.console = types.SimpleNamespace(warning=lambda *a, **k: None)
        controller.ui = types.SimpleNamespace(failure_artifacts=mock.Mock())
        app = MODULE.AppSpec(key="pager", name="PAGER", app_id=5)
        controller.audit_channels = lambda fail_on_drift=False: [
            MODULE.AuditEntry(app="PAGER", app_key="pager", app_id=5, channel="normal", channel_id="x", exists=True,
                              desired_sound="pager.ogg", actual_sound="pager.ogg", desired_vibration=False,
                              actual_vibration=False, desired_importance=3, actual_importance=3, drift=[])
        ]
        self.assertTrue(controller.verify_channel_postcondition(app, "normal"))
        controller.audit_channels = lambda fail_on_drift=False: [
            MODULE.AuditEntry(app="PAGER", app_key="pager", app_id=5, channel="normal", channel_id="x", exists=True,
                              desired_sound="pager.ogg", actual_sound="default", desired_vibration=False,
                              actual_vibration=True, desired_importance=3, actual_importance=3, drift=["sound:default->pager.ogg"])
        ]
        self.assertFalse(controller.verify_channel_postcondition(app, "normal"))
        controller.ui.failure_artifacts.assert_called_once()

    def test_only_drifted_repair_does_not_reopen_sound_picker_for_vibration_only(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.settings = types.SimpleNamespace(dry_run=False, ui_mode="auto", oem_profile="pixel", strict=True, non_interactive=True,
                                                    ui_retries=1, ui_wait=0.0, package="com.github.gotify")
        controller.apps = [MODULE.AppSpec(key="pager", name="PAGER", app_id=5, channels={"normal": MODULE.ChannelPolicy(sound="pager.ogg", vibration=False, importance=3)})]
        controller.resolve_app_ids = lambda allow_seed: None
        controller.audit_channels = lambda fail_on_drift=False: [MODULE.AuditEntry(app="PAGER", app_key="pager", app_id=5, channel="normal", channel_id="x", exists=True,
            desired_sound="pager.ogg", actual_sound="pager.ogg", desired_vibration=False, actual_vibration=True,
            desired_importance=3, actual_importance=3, drift=["vibration:True->False"])]
        controller.wait_for_channel = lambda _cid: True
        controller.channel_id = lambda _app, _cls: "x"
        controller.console = types.SimpleNamespace(warning=lambda *a, **k: None, success=lambda *a, **k: None)
        seen = []
        controller.configure_channel_ui = lambda _app, _cls, policy: seen.append(policy) or True
        controller.verify_channel_postcondition = lambda *_args: True
        controller.configure_channels(classes=["normal"], only_drifted=True)
        self.assertEqual(seen[0].sound, "keep")
        self.assertFalse(seen[0].vibration)

    def test_screenshot_reads_png_as_binary_once(self):
        adb = AdbHarness()
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "capture.png"
            result = subprocess.CompletedProcess([], 0, b"\x89PNG\r\n\x1a\nbytes", b"")
            with mock.patch.object(MODULE.subprocess, "run", return_value=result) as run:
                self.assertTrue(adb.screenshot(target))
            self.assertEqual(target.read_bytes(), result.stdout)
            self.assertEqual(run.call_count, 1)

    def test_screenshot_rejects_non_png_without_writing(self):
        adb = AdbHarness()
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "capture.png"
            result = subprocess.CompletedProcess([], 0, b"not a png", b"")
            with mock.patch.object(MODULE.subprocess, "run", return_value=result):
                self.assertFalse(adb.screenshot(target))
            self.assertFalse(target.exists())

    def test_launch_package_resolves_then_waits_for_activity(self):
        adb = AdbHarness()
        adb.responses = [
            subprocess.CompletedProcess([], 0, "com.github.gotify/.init.InitializationActivity\n", ""),
            subprocess.CompletedProcess([], 0, "Status: ok\n", ""),
        ]
        self.assertTrue(adb.launch_package("com.github.gotify"))
        self.assertIn("resolve-activity", adb.calls[0][0])
        self.assertEqual(adb.calls[1][0][:3], ["am", "start", "-W"])

    def test_keyguard_showing_parses_platform_policy(self):
        adb = AdbHarness()
        adb.responses = [subprocess.CompletedProcess([], 0, "KeyguardServiceDelegate\n  showing=true\n", "")]
        self.assertTrue(adb.keyguard_showing())
        adb.responses = [subprocess.CompletedProcess([], 0, "KeyguardServiceDelegate\n  showing=false\n", "")]
        self.assertFalse(adb.keyguard_showing())

    def test_open_channel_settings_resets_stale_settings_task(self):
        adb = AdbHarness()
        self.assertTrue(adb.open_channel_settings("com.github.gotify", "5::gotify_messages_default_importance"))
        self.assertEqual(adb.calls[0][0], ["am", "force-stop", "com.android.settings"])
        self.assertIn("android.settings.CHANNEL_NOTIFICATION_SETTINGS", adb.calls[1][0])

    def test_launch_package_refuses_unresolved_or_error_activity(self):
        adb = AdbHarness()
        adb.responses = [subprocess.CompletedProcess([], 0, "No activity found\n", "")]
        self.assertFalse(adb.launch_package("com.github.gotify"))
        adb.responses = [
            subprocess.CompletedProcess([], 0, "com.github.gotify/.Main\n", ""),
            subprocess.CompletedProcess([], 0, "Error: Activity not started\n", ""),
        ]
        self.assertFalse(adb.launch_package("com.github.gotify"))

    def test_channel_parser_and_drift_for_pixel_style_dump(self):
        dump = """NotificationChannel{mId='5::gotify_messages_min_importance', mName=Old, mImportance=1, mSound=null, mVibrationEnabled=false, mDeleted=true}\nNotificationChannel{mId='5::gotify_messages_min_importance', mName=Min, mImportance=1, mSound=null, mVibrationEnabled=false, mUserLockedFields=0}\nNotificationChannel{mId='5::gotify_messages_default_importance', mName=Default, mImportance=3, mSound=content://media/external/audio/media/42, mVibrationEnabled=true, mUserLockedFields=0}"""
        rows = MODULE.Controller.parse_notification_channels(dump)
        self.assertEqual(rows["5::gotify_messages_min_importance"][0]["importance"], 1)
        self.assertFalse(rows["5::gotify_messages_min_importance"][0]["vibration"])
        self.assertEqual(MODULE.Controller.sound_uri_to_name("content://media/external/audio/media/42", {"42": "pager.ogg"}), "pager.ogg")
        self.assertEqual(MODULE.Controller.sound_uri_to_name("null", {}), "silent")
        self.assertTrue(MODULE.Controller.is_effectively_silent({"importance": 1, "vibration": False}, "default", 1))
        self.assertFalse(MODULE.Controller.is_effectively_silent({"importance": 3, "vibration": False}, "default", 3))

    def test_all_ten_app_channel_ids_are_deterministic(self):
        for offset, row in enumerate(MODULE.DEFAULT_APPS, start=5):
            app = MODULE.AppSpec(key=row["id"], name=row["name"], app_id=offset)
            for cls, suffix in MODULE.CHANNEL_SUFFIXES.items():
                self.assertEqual(f"{app.app_id}::{suffix}", f"{offset}::{suffix}")

    def test_existing_per_app_channel_skips_launcher(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.settings = types.SimpleNamespace(ensure_separate_channels="auto", ui_mode="auto", dry_run=False, package="com.github.gotify", ui_wait=0.0)
        controller.device = types.SimpleNamespace(sdk=37)
        controller.apps = [MODULE.AppSpec(key="pager", name="PAGER", app_id=5)]
        controller.console = types.SimpleNamespace(success=lambda *a, **k: None, warning=lambda *a, **k: None)
        controller.adb = types.SimpleNamespace(dumpsys_notification=lambda _: "NotificationChannel{mId='5::gotify_messages_low_importance', mImportance=2}", launch_package=lambda _: self.fail("launcher must not run"))
        self.assertTrue(controller.ensure_separate_app_channels())

    def test_silent_channel_does_not_require_hidden_pixel_vibration_control(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.channel_id = lambda app, cls: "5::gotify_messages_min_importance"
        controller.settings = types.SimpleNamespace(package="com.github.gotify", ui_wait=0.0)
        controller.adb = types.SimpleNamespace(open_channel_settings=lambda *args: True)
        controller.ui = types.SimpleNamespace(find=mock.Mock(side_effect=self.fail), failure_artifacts=mock.Mock())
        controller.preflight_channel_page = lambda cls: True
        controller.ui_labels = lambda: {"silent": "^Silent$", "vibration": "^Vibration$"}
        controller._ui_set_silent = mock.Mock(return_value=True)
        app = MODULE.AppSpec(key="pager", name="PAGER", app_id=5)
        self.assertTrue(controller.configure_channel_ui(app, "min", MODULE.ChannelPolicy(sound="silent", vibration=False)))
        controller._ui_set_silent.assert_called_once()
        controller.ui.find.assert_not_called()

    def test_pixel_silent_selection_is_recognised_without_a_tap(self):
        controller = MODULE.Controller.__new__(MODULE.Controller)
        controller.ui = types.SimpleNamespace(find=lambda _: {"selected": True, "checked": False})
        self.assertTrue(controller._ui_set_silent({"silent": "^Silent$"}))

    def test_failure_artifacts_do_not_mask_configuration_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            ui = MODULE.UIAutomator.__new__(MODULE.UIAutomator)
            ui.settings = types.SimpleNamespace(dump_ui_on_failure=True, screenshot_on_failure=True)
            ui.temp_dir = pathlib.Path(tmp)
            ui.console = types.SimpleNamespace(warning=lambda *a, **k: None)
            ui.dump = mock.Mock(side_effect=UnicodeDecodeError("utf-8", b"\x89", 0, 1, "bad"))
            ui.adb = types.SimpleNamespace(screenshot=mock.Mock(side_effect=OSError("adb unavailable")))
            ui.failure_artifacts("pager/min")


if __name__ == "__main__":
    unittest.main(verbosity=2)
