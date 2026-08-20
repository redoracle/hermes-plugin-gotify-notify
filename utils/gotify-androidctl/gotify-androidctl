#!/usr/bin/env python3
"""
gotify-androidctl
=================
Enterprise-grade macOS/Linux provisioning and audit utility for Gotify Android
notification channels, Gotify Application icons, and custom notification sounds.

Design principles
-----------------
* Stock Android compatible: no root and no private Android APIs required.
* Idempotent where Android permits it (sound deployment, app-id resolution,
  discovery/audit). Channel behavior changes are performed through the system UI,
  because Android makes NotificationChannel behavior user-controlled after creation.
* Uses deterministic Gotify Android per-application channel IDs:
    <applicationId>::gotify_messages_{min|low|default|high}_importance
* Declarative Gotify Application lifecycle management: discover/create missing
  categories, upload configured Application images, capture one-time Gotify 3 tokens immediately, persist one dedicated
  0600 token file per category, and generate a redacted provisioning manifest.
* Explicit application-token rotation via PUT /application/{id}/security with
  Gotify 3 step-up-auth awareness and one-time-token recovery safeguards.
* Application IDs are resolved from config/state, Gotify management API, or the
  response from a seed push; stale ID/name conflicts are refused during provisioning.
* Secrets are sourced from protected environment variables/files or the managed
  secret store; app tokens are never placed in URLs or normal logs. curl
  authentication headers are placed in a temporary 0600 file.
* UI automation is best-effort and OEM-safe: it only taps nodes it can identify
  semantically. If it cannot prove what to tap it falls back to guided mode or
  fails in non-interactive/strict mode.

Python: 3.8+
Runtime dependencies: adb, curl
Optional: none (standard library only)
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fnmatch
import hashlib
import json
import mimetypes
import os
import pathlib
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


TOOL_NAME = "gotify-androidctl"
CONFIG_VERSION = 1
MIN_GOTIFY_ANDROID_FOR_APP_CHANNELS = (2, 6, 0)
DEFAULT_PACKAGE = "com.github.gotify"
DEFAULT_ASSETS_ROOT = "."
DEFAULT_ICONS_DIR = "icons"
DEFAULT_SOUNDS_DIR = "sounds"
DEFAULT_REMOTE_SOUNDS_DIR = "/sdcard/Notifications/Gotify"
DEFAULT_STATE_FILE = os.path.expanduser("~/.config/gotify-androidctl/state.json")
DEFAULT_REPORT_FILE = "./gotify-android-report.json"
DEFAULT_SECRET_DIR = os.path.expanduser("~/.config/gotify-androidctl/secrets")
DEFAULT_AUDIO_CACHE_DIR = os.path.expanduser("~/.cache/gotify-androidctl/audio")
SUPPORTED_AUDIO_FORMATS = ("ogg", "wav", "mp3")
DEFAULT_AUDIO_SOURCE_PREFERENCE = ("wav", "ogg", "mp3")
DEFAULT_PROVISIONING_FILENAME = "gotify-application-provisioning.json"

CHANNEL_SUFFIXES: Mapping[str, str] = {
    "min": "gotify_messages_min_importance",
    "low": "gotify_messages_low_importance",
    "normal": "gotify_messages_default_importance",
    "high": "gotify_messages_high_importance",
}
CHANNEL_EXPECTED_IMPORTANCE: Mapping[str, int] = {
    "min": 1,      # NotificationManager.IMPORTANCE_MIN
    "low": 2,      # NotificationManager.IMPORTANCE_LOW
    "normal": 3,   # NotificationManager.IMPORTANCE_DEFAULT
    "high": 4,     # NotificationManager.IMPORTANCE_HIGH
}
PRIORITY_TO_CHANNEL = {
    "min": "<=0",
    "low": "1-3",
    "normal": "4-7",
    "high": ">=8",
}

# Default policy mirrors the design discussed in this conversation. The normal
# channel is explicitly configured with vibration OFF even though Gotify creates
# its normal/default channel with vibration enabled by default.
DEFAULT_APPS: List[Dict[str, Any]] = [
    {"id": "pager", "name": "🚨 PAGER", "description": "Critical paging and escalation events", "default_priority": 8, "sound": "pager.ogg", "icon": "pager.png", "token_env": "TOKEN_PAGER"},
    {"id": "security", "name": "🛡 SECURITY", "description": "Authentication, firewall, access and security events", "default_priority": 2, "sound": "security.ogg", "icon": "security.png", "token_env": "TOKEN_SECURITY"},
    {"id": "infra", "name": "🧱 INFRA", "description": "Hosts, network, storage, filesystem and hardware events", "default_priority": 2, "sound": "infra.ogg", "icon": "infra.png", "token_env": "TOKEN_INFRA"},
    {"id": "platform", "name": "🐳 PLATFORM", "description": "Containers, system services, proxies and application platform events", "default_priority": 2, "sound": "platform.ogg", "icon": "platform.png", "token_env": "TOKEN_PLATFORM"},
    {"id": "automation", "name": "⚙ AUTOMATION", "description": "Cron, workflow, job and orchestration events", "default_priority": 2, "sound": "automation.ogg", "icon": "automation.png", "token_env": "TOKEN_AUTOMATION"},
    {"id": "dev", "name": "🧪 DEV", "description": "Development tooling, builds, tests and interactive engineering events", "default_priority": 2, "sound": "dev.ogg", "icon": "dev.png", "token_env": "TOKEN_DEV"},
    {"id": "digest", "name": "📊 DIGEST", "description": "Reports, summaries, housekeeping and low-noise operational digests", "default_priority": 0, "sound": "silent", "icon": "digest.png", "token_env": "TOKEN_DIGEST"},
    {"id": "money_in", "name": "💰 MONEY · IN", "description": "External incoming financial movements and credits", "default_priority": 5, "sound": "cash-in.ogg", "icon": "money_in.png", "token_env": "TOKEN_MONEY_IN"},
    {"id": "money_out", "name": "💸 MONEY · OUT", "description": "External outgoing financial movements, debits and payments", "default_priority": 5, "sound": "cash-out.ogg", "icon": "money_out.png", "token_env": "TOKEN_MONEY_OUT"},
    {"id": "trading", "name": "📈 TRADING", "description": "Trading order, execution, position and market-operation events", "default_priority": 2, "sound": "trading.ogg", "icon": "trading.png", "token_env": "TOKEN_TRADING"},
]


class ExitCode:
    OK = 0
    USAGE = 2
    PREFLIGHT = 10
    DEVICE = 11
    NETWORK = 12
    CONFIG = 13
    PROVISION = 20
    UI = 21
    AUDIT_DRIFT = 30
    PARTIAL = 40


class ToolError(RuntimeError):
    def __init__(self, message: str, code: int = ExitCode.PROVISION):
        super().__init__(message)
        self.code = code


@dataclasses.dataclass
class ChannelPolicy:
    sound: Optional[str] = None     # filename | "silent" | "default" | "keep"
    vibration: Optional[bool] = None
    importance: Optional[int] = None


@dataclasses.dataclass
class AppSpec:
    key: str
    name: str
    enabled: bool = True
    app_id: Optional[int] = None
    token_env: Optional[str] = None
    token_file: Optional[str] = None
    description: str = ""
    icon: Optional[str] = None
    default_priority: int = 0
    channels: Dict[str, ChannelPolicy] = dataclasses.field(default_factory=dict)

    def token(self) -> Optional[str]:
        if self.token_env:
            value = os.environ.get(self.token_env, "").strip()
            if value:
                return value
        if self.token_file:
            path = pathlib.Path(os.path.expanduser(self.token_file))
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
        return None


@dataclasses.dataclass
class RuntimeSettings:
    config_path: Optional[str]
    no_config: bool
    state_file: str
    gotify_url: Optional[str]
    package: str
    assets_root: str
    icons_dir: str
    sounds_dir: str
    remote_sounds_dir: str
    audio_format: str
    audio_source_preference: List[str]
    audio_cache_dir: str
    ffmpeg: str
    audio_vorbis_quality: float
    serial: Optional[str]
    transport_id: Optional[int]
    android_user: int
    adb: str
    curl: str
    adb_host: Optional[str]
    adb_port: Optional[int]
    allow_emulator: bool
    allow_legacy: bool
    wait_device: float
    dry_run: bool
    non_interactive: bool
    assume_yes: bool
    strict: bool
    continue_on_error: bool
    log_level: str
    log_file: Optional[str]
    color: str
    report_file: Optional[str]
    json_console: bool
    include_apps: List[str]
    exclude_apps: List[str]
    # HTTP
    insecure: bool
    cacert: Optional[str]
    client_cert: Optional[str]
    client_key: Optional[str]
    client_p12: Optional[str]
    client_p12_password_env: Optional[str]
    proxy: Optional[str]
    no_proxy: Optional[str]
    http_user: Optional[str]
    http_password_env: Optional[str]
    http_bearer_env: Optional[str]
    headers: List[str]
    header_envs: List[str]
    connect_timeout: float
    request_timeout: float
    retries: int
    retry_delay: float
    # Gotify auth / application lifecycle management
    client_token_env: Optional[str]
    client_token_file: Optional[str]
    gotify_username: Optional[str]
    gotify_password_env: Optional[str]
    gotify_password_file: Optional[str]
    secret_dir: str
    provisioning_output: Optional[str]
    # UI
    ui_mode: str
    ui_wait: float
    ui_retries: int
    ui_scrolls: int
    ui_locale: str
    oem_profile: str
    screenshot_on_failure: bool
    dump_ui_on_failure: bool
    guided_timeout: float
    ensure_separate_channels: str
    # device behavior
    wake_device: bool
    keep_awake: bool
    grant_notifications: bool
    battery_whitelist: bool
    # seed
    seed_priority: int
    seed_all_priorities: bool
    seed_wait: float
    channel_wait: float
    seed_title_prefix: str
    seed_message: str
    cleanup_seeds: bool
    # sound
    media_scan: str
    verify_hash: bool
    force_sound_push: bool
    remove_orphan_sounds: bool
    # diagnostics
    preserve_temp: bool
    sensitive_dump: bool


@dataclasses.dataclass
class DeviceInfo:
    serial: str = ""
    model: str = ""
    manufacturer: str = ""
    product: str = ""
    android_version: str = ""
    sdk: int = 0
    fingerprint: str = ""
    gotify_version: str = ""
    gotify_version_code: str = ""
    package_uid: str = ""
    oem_profile: str = "generic"


@dataclasses.dataclass
class Event:
    timestamp: str
    level: str
    component: str
    item: str
    message: str


@dataclasses.dataclass
class AuditEntry:
    app: str
    app_key: str
    app_id: Optional[int]
    channel: str
    channel_id: Optional[str]
    exists: bool
    desired_sound: Optional[str]
    actual_sound: Optional[str]
    desired_vibration: Optional[bool]
    actual_vibration: Optional[bool]
    desired_importance: Optional[int]
    actual_importance: Optional[int]
    drift: List[str] = dataclasses.field(default_factory=list)


class Console:
    LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}
    ANSI = {
        "debug": "\033[2m",
        "info": "\033[1;34m",
        "success": "\033[1;32m",
        "warning": "\033[1;33m",
        "error": "\033[1;31m",
        "reset": "\033[0m",
    }

    def __init__(self, level: str, color: str, log_file: Optional[str], json_console: bool, event_sink: Optional[Any] = None):
        self.level = self.LEVELS.get(level, 20)
        self.event_sink = event_sink
        self.color_mode = color
        self.log_file = pathlib.Path(log_file).expanduser() if log_file else None
        self.json_console = json_console
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _use_color(self) -> bool:
        return self.color_mode == "always" or (self.color_mode == "auto" and sys.stderr.isatty())

    def emit(self, level: str, message: str, component: str = "core", item: str = "") -> None:
        severity = "info" if level == "success" else level
        if self.LEVELS.get(severity, 20) < self.level:
            return
        ts = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        if self.event_sink is not None:
            mapped = {"success": "ok", "warning": "warning", "error": "error"}.get(level, level)
            try:
                self.event_sink(mapped, component, item, message)
            except Exception:
                pass
        if self.json_console:
            payload = {"timestamp": ts, "level": level, "component": component, "item": item, "message": message}
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        else:
            marker = {"debug": "·", "info": "==>", "success": "✔", "warning": "WARN", "error": "ERROR"}.get(level, "-")
            prefix = f"[{ts}] {marker}"
            if self._use_color():
                prefix = f"{self.ANSI.get(level, '')}{prefix}{self.ANSI['reset']}"
            print(f"{prefix} {message}", file=sys.stderr)
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"timestamp": ts, "level": level, "component": component, "item": item, "message": message}, ensure_ascii=False) + "\n")

    def debug(self, m: str, **kw: Any) -> None: self.emit("debug", m, **kw)
    def info(self, m: str, **kw: Any) -> None: self.emit("info", m, **kw)
    def success(self, m: str, **kw: Any) -> None: self.emit("success", m, **kw)
    def warning(self, m: str, **kw: Any) -> None: self.emit("warning", m, **kw)
    def error(self, m: str, **kw: Any) -> None: self.emit("error", m, **kw)


class Report:
    def __init__(self, command: str):
        self.command = command
        self.started_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        self.finished_at: Optional[str] = None
        self.events: List[Event] = []
        self.audit: List[AuditEntry] = []
        self.device: Dict[str, Any] = {}
        self.server: Dict[str, Any] = {}
        self.summary = {"ok": 0, "warning": 0, "error": 0, "skipped": 0}

    def add(self, level: str, component: str, item: str, message: str) -> None:
        ts = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        self.events.append(Event(ts, level, component, item, message))
        if level in self.summary:
            self.summary[level] += 1

    def finish(self) -> None:
        self.finished_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": {"name": TOOL_NAME},
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "device": self.device,
            "server": self.server,
            "audit": [dataclasses.asdict(x) for x in self.audit],
            "events": [dataclasses.asdict(x) for x in self.events],
        }


class Runner:
    def __init__(self, console: Console, settings: RuntimeSettings):
        self.console = console
        self.settings = settings

    def run(
        self,
        cmd: Sequence[str],
        *,
        timeout: Optional[float] = None,
        check: bool = True,
        capture: bool = True,
        input_text: Optional[str] = None,
        redact: Sequence[str] = (),
        env: Optional[Mapping[str, str]] = None,
        mutating: bool = False,
    ) -> subprocess.CompletedProcess:
        shown: List[str] = []
        secrets = [x for x in redact if x]
        for arg in cmd:
            value = str(arg)
            for secret in secrets:
                value = value.replace(secret, "***")
            shown.append(value)
        self.console.debug("$ " + " ".join(shlex.quote(x) for x in shown), component="exec")
        if self.settings.dry_run and mutating:
            self.console.info("DRY-RUN: would execute: " + " ".join(shlex.quote(x) for x in shown), component="dry-run")
            return subprocess.CompletedProcess(list(cmd), 0, "", "")
        try:
            cp = subprocess.run(
                list(cmd),
                input=input_text,
                text=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
                timeout=timeout,
                env=dict(os.environ, **(dict(env) if env else {})),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"Command timed out after {timeout}s: {shown[0]}", ExitCode.DEVICE) from exc
        except OSError as exc:
            raise ToolError(f"Failed to execute {shown[0]}: {exc}", ExitCode.PREFLIGHT) from exc
        if check and cp.returncode != 0:
            stderr = (cp.stderr or "").strip()
            for secret in secrets:
                stderr = stderr.replace(secret, "***")
            raise ToolError(f"Command failed ({cp.returncode}): {' '.join(shown)}{': ' + stderr if stderr else ''}")
        return cp


class ADB:
    def __init__(self, runner: Runner, settings: RuntimeSettings):
        self.runner = runner
        self.settings = settings
        self.serial: Optional[str] = settings.serial
        self.keep_awake_enabled = False

    def base(self, select_device: bool = True) -> List[str]:
        args = [self.settings.adb]
        if self.settings.adb_host:
            args += ["-H", self.settings.adb_host]
        if self.settings.adb_port:
            args += ["-P", str(self.settings.adb_port)]
        if select_device:
            if self.settings.transport_id is not None:
                args += ["-t", str(self.settings.transport_id)]
            elif self.serial:
                args += ["-s", self.serial]
        return args

    def run(self, args: Sequence[str], *, select_device: bool = True, **kwargs: Any) -> subprocess.CompletedProcess:
        return self.runner.run(self.base(select_device) + list(args), **kwargs)

    def shell(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return self.run(["shell"] + list(args), **kwargs)

    def start_server(self) -> None:
        self.run(["start-server"], select_device=False, check=True)

    def devices(self) -> List[Dict[str, str]]:
        cp = self.run(["devices", "-l"], select_device=False)
        rows: List[Dict[str, str]] = []
        for raw in (cp.stdout or "").splitlines()[1:]:
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split()
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "unknown"
            meta: Dict[str, str] = {"serial": serial, "state": state}
            for p in parts[2:]:
                if ":" in p:
                    k, v = p.split(":", 1)
                    meta[k] = v
            rows.append(meta)
        return rows

    def select(self) -> str:
        self.start_server()
        deadline = time.monotonic() + max(0.0, self.settings.wait_device)
        last_rows: List[Dict[str, str]] = []
        while True:
            rows = self.devices()
            last_rows = rows
            if self.serial:
                matches = [r for r in rows if r["serial"] == self.serial]
                if matches and matches[0]["state"] == "device":
                    return self.serial
                if matches and matches[0]["state"] == "unauthorized":
                    raise ToolError(f"Device {self.serial} is unauthorized; approve the RSA prompt on the phone.", ExitCode.DEVICE)
            elif self.settings.transport_id is not None:
                # -t transport selection is handled by adb; use get-serialno as validation.
                cp = self.run(["get-serialno"], check=False)
                if cp.returncode == 0 and (cp.stdout or "").strip() not in ("", "unknown"):
                    self.serial = (cp.stdout or "").strip()
                    return self.serial
            else:
                candidates = [r for r in rows if r["state"] == "device"]
                if not self.settings.allow_emulator:
                    candidates = [r for r in candidates if not r["serial"].startswith("emulator-")]
                if len(candidates) == 1:
                    self.serial = candidates[0]["serial"]
                    return self.serial
                if len(candidates) > 1:
                    listing = ", ".join(r["serial"] for r in candidates)
                    raise ToolError(f"Multiple Android devices are online ({listing}); use --serial or --transport-id.", ExitCode.DEVICE)
            if time.monotonic() >= deadline:
                break
            time.sleep(1.0)
        if last_rows:
            detail = "; ".join(f"{r['serial']}={r['state']}" for r in last_rows)
            raise ToolError(f"No usable Android device selected. adb devices: {detail}", ExitCode.DEVICE)
        raise ToolError("No Android device found. Enable USB debugging or use the connect/pair commands.", ExitCode.DEVICE)

    def prop(self, key: str) -> str:
        cp = self.shell(["getprop", key], check=False)
        return (cp.stdout or "").strip().replace("\r", "")

    def current_user(self) -> int:
        cp = self.shell(["am", "get-current-user"], check=False)
        try:
            return int((cp.stdout or "").strip())
        except ValueError:
            return 0

    def user_args(self) -> List[str]:
        return ["--user", str(self.settings.android_user)]

    def package_installed(self, package: str) -> bool:
        cp = self.shell(["pm", "path", "--user", str(self.settings.android_user), package], check=False)
        if cp.returncode == 0 and "package:" in (cp.stdout or ""):
            return True
        # Fallback for devices whose pm path syntax does not accept --user.
        cp = self.shell(["cmd", "package", "list", "packages", "--user", str(self.settings.android_user), package], check=False)
        return package in (cp.stdout or "")

    def package_uid(self, package: str) -> str:
        cp = self.shell(["cmd", "package", "list", "packages", "-U", "--user", str(self.settings.android_user), package], check=False)
        m = re.search(r"uid:(\d+)", cp.stdout or "")
        return m.group(1) if m else ""

    def package_version(self, package: str) -> Tuple[str, str]:
        cp = self.shell(["dumpsys", "package", package], check=False)
        text = cp.stdout or ""
        m1 = re.search(r"\bversionName=([^\s]+)", text)
        m2 = re.search(r"\bversionCode=(\d+)", text)
        return (m1.group(1) if m1 else "", m2.group(1) if m2 else "")

    def keyguard_showing(self) -> Optional[bool]:
        """Best-effort lock-state check; unknown is intentionally non-blocking.

        Android/OEM policy dumps differ, so callers only refuse automation when
        the platform positively reports a visible keyguard.  This avoids
        attempting Settings taps on a lock screen without assuming one OEM UI.
        """
        cp = self.shell(["dumpsys", "window", "policy"], check=False)
        text = cp.stdout or ""
        match = re.search(r"KeyguardServiceDelegate\s+showing=(true|false)", text)
        if not match:
            match = re.search(r"(?:mShowingLockscreen|isStatusBarKeyguard)=(true|false)", text)
        return (match.group(1) == "true") if match else None

    def wake(self) -> None:
        self.shell(["input", "keyevent", "KEYCODE_WAKEUP"], check=False, mutating=True)
        self.shell(["wm", "dismiss-keyguard"], check=False, mutating=True)

    def keep_awake(self, enabled: bool) -> None:
        if enabled:
            self.shell(["svc", "power", "stayon", "usb"], check=False, mutating=True)
            self.keep_awake_enabled = True
        elif self.keep_awake_enabled:
            self.shell(["svc", "power", "stayon", "false"], check=False, mutating=True)
            self.keep_awake_enabled = False

    def screenshot(self, path: pathlib.Path) -> bool:
        if self.settings.dry_run:
            return True
        # Runner uses text=True for normal ADB command output. `screencap -p`
        # emits binary PNG, so using Runner first raises UnicodeDecodeError and
        # can hide the original UI-automation failure we are trying to diagnose.
        cmd = self.base(True) + ["exec-out", "screencap", "-p"]
        try:
            raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=15)
            if raw.returncode == 0 and raw.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
                path.write_bytes(raw.stdout)
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        return False

    def dumpsys_notification(self, sensitive: bool = False) -> str:
        args = ["dumpsys", "notification"]
        if sensitive:
            args.append("--noredact")
        cp = self.shell(args, check=False, timeout=30)
        return cp.stdout or ""

    def open_app_notification_settings(self, package: str) -> bool:
        args = ["am", "start"] + self.user_args() + [
            "-a", "android.settings.APP_NOTIFICATION_SETTINGS",
            "--es", "android.provider.extra.APP_PACKAGE", package,
        ]
        return self.shell(args, check=False, mutating=True).returncode == 0

    def open_channel_settings(self, package: str, channel_id: str) -> bool:
        # Pixel Settings may retain a previous CHANNEL_ID in SubSettings even
        # when Activity Manager accepts the new intent.  Resetting only the
        # Settings task is reversible and prevents stale-page configuration;
        # the controller still performs a semantic title preflight afterwards.
        self.shell(["am", "force-stop", "com.android.settings"], check=False, mutating=True)
        args = ["am", "start"] + self.user_args() + [
            "-a", "android.settings.CHANNEL_NOTIFICATION_SETTINGS",
            "--es", "android.provider.extra.APP_PACKAGE", package,
            "--es", "android.provider.extra.CHANNEL_ID", channel_id,
        ]
        return self.shell(args, check=False, mutating=True).returncode == 0

    def launch_package(self, package: str) -> bool:
        # `monkey` exits zero even when it does not actually resolve/launch the
        # requested package on some OEM/API combinations. Resolve the launcher
        # activity explicitly, then wait for Activity Manager's result.
        resolve = self.shell([
            "cmd", "package", "resolve-activity", "--brief", *self.user_args(),
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package,
        ], check=False)
        component = next((line.strip() for line in (resolve.stdout or "").splitlines() if "/" in line), "")
        if resolve.returncode != 0 or not component:
            return False
        cp = self.shell(["am", "start", "-W", *self.user_args(), "-n", component], check=False, mutating=True)
        output = ((cp.stdout or "") + "\n" + (cp.stderr or "")).lower()
        return cp.returncode == 0 and "error:" not in output and "exception" not in output

    def push(self, local: pathlib.Path, remote: str) -> bool:
        cp = self.run(["push", str(local), remote], check=False, timeout=120, mutating=True)
        return cp.returncode == 0

    def remote_sha256(self, remote: str) -> Optional[str]:
        for cmd in (["toybox", "sha256sum", remote], ["sha256sum", remote]):
            cp = self.shell(list(cmd), check=False, timeout=20)
            if cp.returncode == 0:
                m = re.match(r"([0-9a-fA-F]{64})", (cp.stdout or "").strip())
                if m:
                    return m.group(1).lower()
        return None

    def list_remote_files(self, remote_dir: str) -> List[str]:
        cp = self.shell(["find", remote_dir, "-maxdepth", "1", "-type", "f", "-print"], check=False)
        if cp.returncode != 0:
            cp = self.shell(["ls", "-1", remote_dir], check=False)
            if cp.returncode != 0:
                return []
            return [remote_dir.rstrip("/") + "/" + x.strip() for x in (cp.stdout or "").splitlines() if x.strip()]
        return [x.strip() for x in (cp.stdout or "").splitlines() if x.strip()]

    def remove_remote(self, remote: str) -> bool:
        return self.shell(["rm", "-f", remote], check=False, mutating=True).returncode == 0

    def media_scan(self, remote: str) -> bool:
        uri = "file://" + remote
        cp = self.shell(["am", "broadcast"] + self.user_args() + [
            "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", uri
        ], check=False, mutating=True)
        return cp.returncode == 0

    def media_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        uris = [
            "content://media/external/audio/media",
            "content://media/external_primary/audio/media",
        ]
        for uri in uris:
            cp = self.shell(["content", "query"] + self.user_args() + [
                "--uri", uri, "--projection", "_id:_display_name"
            ], check=False, timeout=30)
            if cp.returncode != 0:
                continue
            for line in (cp.stdout or "").splitlines():
                mid = re.search(r"\b_id=(\d+)", line)
                name = re.search(r"\b_display_name=([^,]+)", line)
                if mid and name:
                    mapping[mid.group(1)] = name.group(1).strip()
        return mapping


class CurlClient:
    def __init__(self, runner: Runner, settings: RuntimeSettings, temp_dir: pathlib.Path):
        self.runner = runner
        self.settings = settings
        self.temp_dir = temp_dir

    @staticmethod
    def _escape_config(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")

    def _secret_config(
        self,
        token: Optional[str],
        basic_auth: Optional[Tuple[str, str]] = None,
    ) -> Tuple[pathlib.Path, List[str]]:
        path = self.temp_dir / f"curl-auth-{time.time_ns()}.cfg"
        lines: List[str] = []
        secrets: List[str] = []
        if token:
            lines.append(f'header = "X-Gotify-Key: {self._escape_config(token)}"')
            secrets.append(token)

        # --http-user belongs to an upstream/reverse-proxy authentication layer.
        # Gotify management Basic auth is supplied separately so the two cannot be
        # silently conflated.
        proxy_basic: Optional[Tuple[str, str]] = None
        if self.settings.http_user:
            password = ""
            if self.settings.http_password_env:
                password = os.environ.get(self.settings.http_password_env, "")
            proxy_basic = (self.settings.http_user, password)

        if basic_auth and proxy_basic and basic_auth != proxy_basic:
            raise ToolError(
                "Gotify management Basic auth and --http-user request different credentials. "
                "curl cannot emit two independent HTTP Basic Authorization headers to the same origin. "
                "Use a proxy-specific header/auth mechanism or a Gotify client token instead.",
                ExitCode.CONFIG,
            )
        selected_basic = basic_auth or proxy_basic
        if selected_basic:
            username, password = selected_basic
            credential = f"{username}:{password}"
            lines.append(f'user = "{self._escape_config(credential)}"')
            if password:
                secrets.append(password)
        if self.settings.http_bearer_env:
            bearer = os.environ.get(self.settings.http_bearer_env, "")
            if bearer:
                lines.append(f'header = "Authorization: Bearer {self._escape_config(bearer)}"')
                secrets.append(bearer)
        for header in self.settings.headers:
            lines.append(f'header = "{self._escape_config(header)}"')
        for spec in self.settings.header_envs:
            if "=" not in spec:
                raise ToolError(f"Invalid --header-env '{spec}'; expected 'Header-Name=ENV_VAR'.", ExitCode.CONFIG)
            name, env_name = spec.split("=", 1)
            value = os.environ.get(env_name, "")
            if not value:
                raise ToolError(f"Environment variable {env_name} required by --header-env is empty.", ExitCode.CONFIG)
            lines.append(f'header = "{self._escape_config(name)}: {self._escape_config(value)}"')
            secrets.append(value)
        if self.settings.client_p12 and self.settings.client_p12_password_env:
            password = os.environ.get(self.settings.client_p12_password_env, "")
            if password:
                lines.append(f'cert = "{self._escape_config(self.settings.client_p12)}:{self._escape_config(password)}"')
                lines.append('cert-type = "P12"')
                secrets.append(password)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        return path, secrets

    def request(
        self,
        method: str,
        path: str,
        *,
        token: Optional[str] = None,
        basic_auth: Optional[Tuple[str, str]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        form_file: Optional[Tuple[str, pathlib.Path]] = None,
        accept: Sequence[int] = (200, 201, 204),
    ) -> Tuple[int, str]:
        if not self.settings.gotify_url:
            raise ToolError("Gotify URL is not configured; use --gotify-url, GOTIFY_URL, or config file.", ExitCode.CONFIG)
        base = self.settings.gotify_url.rstrip("/")
        url = base + (path if path.startswith("/") else "/" + path)
        if self.settings.dry_run and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            self.runner.console.info(f"DRY-RUN: would send {method.upper()} {url}", component="dry-run")
            return (accept[0] if accept else 200), "{}"
        auth_cfg, secrets = self._secret_config(token, basic_auth=basic_auth)
        body_file = self.temp_dir / f"http-body-{time.time_ns()}.txt"
        payload_file: Optional[pathlib.Path] = None
        cmd = [
            self.settings.curl, "--silent", "--show-error", "--location",
            "--request", method.upper(),
            "--connect-timeout", str(self.settings.connect_timeout),
            "--max-time", str(self.settings.request_timeout),
            "--output", str(body_file),
            "--write-out", "%{http_code}",
            "--config", str(auth_cfg),
        ]
        if self.settings.insecure:
            cmd.append("--insecure")
        if self.settings.cacert:
            cmd += ["--cacert", self.settings.cacert]
        if self.settings.client_cert:
            cmd += ["--cert", self.settings.client_cert]
        if self.settings.client_key:
            cmd += ["--key", self.settings.client_key]
        if self.settings.client_p12 and not self.settings.client_p12_password_env:
            cmd += ["--cert-type", "P12", "--cert", self.settings.client_p12]
        if self.settings.proxy:
            cmd += ["--proxy", self.settings.proxy]
        if self.settings.no_proxy:
            cmd += ["--noproxy", self.settings.no_proxy]
        if json_body is not None and form_file is not None:
            raise ToolError("HTTP request cannot contain both json_body and form_file.", ExitCode.CONFIG)
        if json_body is not None:
            payload_file = self.temp_dir / f"http-payload-{time.time_ns()}.json"
            payload_file.write_text(json.dumps(json_body, ensure_ascii=False), encoding="utf-8")
            os.chmod(payload_file, 0o600)
            cmd += ["--header", "Content-Type: application/json", "--data-binary", f"@{payload_file}"]
        if form_file is not None:
            field, file_path = form_file
            file_path = pathlib.Path(file_path)
            if not file_path.is_file():
                raise ToolError(f"Multipart upload file does not exist: {file_path}", ExitCode.CONFIG)
            mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            cmd += ["--form", f"{field}=@{file_path};type={mime}"]
        cmd.append(url)

        last_error = ""
        attempts = max(1, self.settings.retries + 1)
        for attempt in range(1, attempts + 1):
            cp = self.runner.run(cmd, check=False, timeout=self.settings.request_timeout + 5, redact=secrets)
            status_text = (cp.stdout or "").strip()
            body = body_file.read_text(encoding="utf-8", errors="replace") if body_file.exists() else ""
            try:
                status = int(status_text[-3:]) if len(status_text) >= 3 else 0
            except ValueError:
                status = 0
            if cp.returncode == 0 and status in accept:
                return status, body
            last_error = (cp.stderr or "").strip() or f"HTTP {status}: {body[:500]}"
            # Do not retry deterministic client/auth failures. Retrying these can
            # obscure authorization/elevation errors and unnecessarily hammer the API.
            if 400 <= status < 500 and status not in (408, 409, 425, 429):
                break
            if attempt < attempts:
                sleep_for = self.settings.retry_delay * (2 ** (attempt - 1))
                self.runner.console.warning(
                    f"HTTP attempt {attempt}/{attempts} failed ({last_error[:240]}), retrying in {sleep_for:.1f}s",
                    component="http",
                )
                time.sleep(sleep_for)
        raise ToolError(f"HTTP request failed: {method} {url}: {last_error}", ExitCode.NETWORK)


class StateStore:
    def __init__(self, path: str, url: Optional[str], console: Console):
        self.path = pathlib.Path(os.path.expanduser(path))
        self.url = (url or "").rstrip("/")
        self.console = console
        self.data: Dict[str, Any] = {"version": 1, "servers": {}}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.data = data
        except Exception as exc:
            self.console.warning(f"Ignoring unreadable state file {self.path}: {exc}", component="state")

    def get_app_id(self, key: str) -> Optional[int]:
        servers = self.data.get("servers", {})
        server = servers.get(self.url, {}) if isinstance(servers, dict) else {}
        apps = server.get("apps", {}) if isinstance(server, dict) else {}
        value = apps.get(key) if isinstance(apps, dict) else None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def set_app_id(self, key: str, app_id: int) -> None:
        self.data.setdefault("version", 1)
        servers = self.data.setdefault("servers", {})
        server = servers.setdefault(self.url, {})
        apps = server.setdefault("apps", {})
        apps[key] = int(app_id)

    def get_asset_hash(self, key: str, asset: str) -> Optional[str]:
        servers = self.data.get("servers", {})
        server = servers.get(self.url, {}) if isinstance(servers, dict) else {}
        assets = server.get("assets", {}) if isinstance(server, dict) else {}
        app_assets = assets.get(key, {}) if isinstance(assets, dict) else {}
        value = app_assets.get(asset) if isinstance(app_assets, dict) else None
        return str(value) if value else None

    def set_asset_hash(self, key: str, asset: str, digest: str) -> None:
        self.data.setdefault("version", 1)
        servers = self.data.setdefault("servers", {})
        server = servers.setdefault(self.url, {})
        assets = server.setdefault("assets", {})
        app_assets = assets.setdefault(key, {})
        app_assets[asset] = str(digest)

    def save(self) -> None:
        if not self.url:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        os.chmod(self.path, 0o600)


class ManagedSecretStore:
    """Durable filesystem-backed Gotify application token store.

    Each category gets exactly one raw-token file with mode 0600. Provisioning
    metadata never contains raw tokens. All replacements are atomic and fsynced.
    The server-specific namespace includes a hash of the complete Gotify base URL,
    avoiding collisions between multiple instances on the same host.
    """

    def __init__(self, base_dir: str, server_url: Optional[str], console: Console):
        self.base_dir = pathlib.Path(os.path.expanduser(base_dir)).resolve()
        self.server_url = (server_url or "unconfigured").rstrip("/")
        parsed = urllib.parse.urlparse(
            self.server_url if "://" in self.server_url else "https://" + self.server_url
        )
        host = (parsed.hostname or "gotify").lower()
        slug = re.sub(r"[^a-z0-9.-]+", "-", host).strip("-.") or "gotify"
        digest = hashlib.sha256(self.server_url.encode("utf-8")).hexdigest()[:12]
        self.root = self.base_dir / f"{slug}-{digest}"
        self.apps_dir = self.root / "apps"
        self.console = console

    @staticmethod
    def mask(token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        if len(token) <= 12:
            return token[:2] + "…" + token[-2:]
        return token[:7] + "…" + token[-5:]

    @staticmethod
    def fingerprint(token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def prepare(self) -> None:
        base_existed = self.base_dir.exists()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # Never chmod an arbitrary pre-existing parent supplied by the operator.
        if not base_existed:
            with contextlib.suppress(OSError):
                os.chmod(self.base_dir, 0o700)
        self.root.mkdir(parents=True, exist_ok=True)
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        os.chmod(self.apps_dir, 0o700)

    def token_path(self, key: str) -> pathlib.Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", key).strip("-.")
        if not safe:
            raise ToolError(f"Unsafe/empty application key for token file: {key!r}", ExitCode.CONFIG)
        return self.apps_dir / f"{safe}.token"

    def read_token(self, key: str) -> Optional[str]:
        path = self.token_path(key)
        if not path.is_file() or path.is_symlink():
            return None
        try:
            mode = path.stat().st_mode & 0o777
            if mode & 0o077:
                try:
                    os.chmod(path, 0o600)
                    self.console.warning(
                        f"Hardened overly permissive managed token file {path} from {oct(mode)} to 0o600",
                        component="secrets", item=key,
                    )
                except OSError as exc:
                    raise ToolError(
                        f"Managed token file {path} is too permissive ({oct(mode)}) and could not be hardened: {exc}",
                        ExitCode.CONFIG,
                    ) from exc
            value = path.read_text(encoding="utf-8").strip()
            return value or None
        except ToolError:
            raise
        except OSError as exc:
            self.console.warning(
                f"Could not read managed token file {path}: {exc}",
                component="secrets", item=key,
            )
            return None

    def preflight_write(self, key: str) -> pathlib.Path:
        self.prepare()
        target = self.token_path(key)
        if target.exists() and target.is_symlink():
            raise ToolError(f"Refusing to write token through symlink: {target}", ExitCode.CONFIG)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(self.apps_dir))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as fh:
                fh.write(b"preflight\n")
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
        return target

    @staticmethod
    def _fsync_dir(path: pathlib.Path) -> None:
        with contextlib.suppress(OSError):
            fd = os.open(str(path), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def write_token(self, key: str, token: str) -> pathlib.Path:
        token = (token or "").strip()
        if not token or "\n" in token or "\r" in token:
            raise ToolError(f"Refusing to persist invalid token for {key}.", ExitCode.PROVISION)
        if len(token) > 8192:
            raise ToolError(f"Refusing unexpectedly large token for {key}.", ExitCode.PROVISION)
        target = self.preflight_write(key)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(self.apps_dir))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as fh:
                fh.write(token + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.close(fd)
            fd = -1
            os.replace(tmp_name, target)
            os.chmod(target, 0o600)
            self._fsync_dir(self.apps_dir)
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
        return target

    def provisioning_path(self, configured: Optional[str] = None) -> pathlib.Path:
        self.prepare()
        if configured:
            return pathlib.Path(os.path.expanduser(configured)).resolve()
        return self.root / DEFAULT_PROVISIONING_FILENAME

    def write_json_atomic(
        self, path: pathlib.Path, payload: Mapping[str, Any], mode: int = 0o600
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_symlink():
            raise ToolError(f"Refusing to overwrite symlink: {path}", ExitCode.CONFIG)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            os.fchmod(fd, mode)
            data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.close(fd)
            fd = -1
            os.replace(tmp_name, path)
            os.chmod(path, mode)
            self._fsync_dir(path.parent)
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)

    def export_bundle(
        self,
        path: str,
        apps: Sequence[AppSpec],
        token_lookup,
        fmt: str = "env",
    ) -> pathlib.Path:
        target = pathlib.Path(os.path.expanduser(path)).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.is_symlink():
            raise ToolError(f"Refusing to overwrite symlink: {target}", ExitCode.CONFIG)
        tokens: Dict[str, str] = {}
        for app in apps:
            token = token_lookup(app)
            if token:
                tokens[app.key] = token

        if fmt == "json":
            # JSON bundle is explicit opt-in and does contain the raw tokens.
            self.write_json_atomic(target, tokens, mode=0o600)
        elif fmt == "env":
            lines: List[str] = []
            for app in apps:
                token = tokens.get(app.key)
                if not token:
                    continue
                env_name = app.token_env or (
                    "TOKEN_" + re.sub(r"[^A-Za-z0-9]+", "_", app.key).upper()
                )
                escaped = token.replace("'", "'\\''")
                lines.append(f"{env_name}='{escaped}'")
            fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as fh:
                    fh.write("\n".join(lines) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.close(fd)
                fd = -1
                os.replace(tmp_name, target)
                os.chmod(target, 0o600)
                self._fsync_dir(target.parent)
            finally:
                if fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_name)
        else:
            raise ToolError(f"Unsupported token bundle format: {fmt}", ExitCode.CONFIG)
        return target


class UIAutomator:
    def __init__(self, adb: ADB, console: Console, settings: RuntimeSettings, temp_dir: pathlib.Path):
        self.adb = adb
        self.console = console
        self.settings = settings
        self.temp_dir = temp_dir
        self.dump_counter = 0

    def dump(self) -> Optional[pathlib.Path]:
        self.dump_counter += 1
        remote = f"/sdcard/.gotify-ui-{os.getpid()}.xml"
        local = self.temp_dir / f"ui-{self.dump_counter:04d}.xml"
        cp = self.adb.shell(["uiautomator", "dump", remote], check=False, timeout=20)
        if cp.returncode != 0:
            return None
        if self.settings.dry_run:
            local.write_text("<hierarchy/>", encoding="utf-8")
            return local
        cp = self.adb.run(["pull", remote, str(local)], check=False, timeout=20)
        self.adb.shell(["rm", "-f", remote], check=False)
        return local if cp.returncode == 0 and local.exists() else None

    @staticmethod
    def _bounds_center(bounds: str) -> Optional[Tuple[int, int]]:
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
        if not m:
            return None
        x1, y1, x2, y2 = map(int, m.groups())
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def find(self, regex: str, *, checked: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        path = self.dump()
        if not path:
            return None
        try:
            root = ET.parse(str(path)).getroot()
        except Exception:
            return None
        rx = re.compile(regex, re.IGNORECASE)

        def walk(node: ET.Element, parents: List[ET.Element]) -> Optional[Dict[str, Any]]:
            text = " ".join(filter(None, [node.attrib.get("text", ""), node.attrib.get("content-desc", "")])).strip()
            if rx.search(text):
                # Prefer a clickable ancestor if the text node itself is not clickable.
                candidates = [node] + list(reversed(parents))
                selected = node
                for cand in candidates:
                    if cand.attrib.get("clickable") == "true":
                        selected = cand
                        break
                chk = selected.attrib.get("checked")
                if chk not in ("true", "false"):
                    # Look for a switch/checkable descendant in the matched subtree.
                    for desc in selected.iter():
                        if desc.attrib.get("checked") in ("true", "false"):
                            chk = desc.attrib.get("checked")
                            # Android Settings may make the Switch child
                            # checkable but not mark it clickable; its bounds
                            # are still the only semantic target that reliably
                            # toggles the preference on current Pixel UI.
                            selected = desc
                            break
                if checked is not None and chk in ("true", "false") and (chk == "true") != checked:
                    pass
                center = self._bounds_center(selected.attrib.get("bounds", ""))
                if center:
                    return {
                        "x": center[0], "y": center[1], "text": text,
                        "checked": None if chk not in ("true", "false") else chk == "true",
                        "selected": selected.attrib.get("selected") == "true",
                        "resource_id": selected.attrib.get("resource-id", ""),
                        "class": selected.attrib.get("class", ""),
                        "enabled": selected.attrib.get("enabled", "true") == "true",
                    }
            for child in list(node):
                found = walk(child, parents + [node])
                if found:
                    return found
            return None

        return walk(root, [])

    def has_visible_text(self, regex: str) -> bool:
        """Return true only when the current UI dump proves an expected label.

        Android Settings may reuse a prior ``SubSettings`` intent.  A successful
        ``am start`` is therefore insufficient evidence that the requested
        notification channel is actually on screen.  This method intentionally
        performs no interaction: callers must fail closed before the first tap.
        """
        path = self.dump()
        if not path:
            return False
        try:
            root = ET.parse(str(path)).getroot()
        except Exception:
            return False
        rx = re.compile(regex, re.IGNORECASE)
        for node in root.iter():
            text = " ".join(filter(None, [node.attrib.get("text", ""), node.attrib.get("content-desc", "")])).strip()
            if text and rx.search(text):
                return True
        return False

    def tap_node(self, node: Mapping[str, Any]) -> bool:
        if node.get("enabled") is False:
            return False
        cp = self.adb.shell(["input", "tap", str(node["x"]), str(node["y"])], check=False, mutating=True)
        if cp.returncode == 0:
            time.sleep(self.settings.ui_wait)
            return True
        return False

    def tap(self, regex: str, *, desired_checked: Optional[bool] = None, required: bool = False) -> bool:
        node = self.find(regex)
        if not node:
            if required:
                self.console.warning(f"UI element not found: /{regex}/", component="ui")
            return False
        if desired_checked is not None and node.get("checked") is not None and node["checked"] == desired_checked:
            return True
        return self.tap_node(node)

    def find_with_scroll(self, regex: str) -> Optional[Dict[str, Any]]:
        node = self.find(regex)
        if node:
            return node
        # Only swipe after a semantic search failed; no blind tap is performed.
        size = self.screen_size()
        if not size:
            return None
        w, h = size
        x = w // 2
        for _ in range(max(0, self.settings.ui_scrolls)):
            self.adb.shell(["input", "swipe", str(x), str(int(h * 0.78)), str(x), str(int(h * 0.28)), "350"], check=False, mutating=True)
            time.sleep(self.settings.ui_wait)
            node = self.find(regex)
            if node:
                return node
        return None

    def screen_size(self) -> Optional[Tuple[int, int]]:
        cp = self.adb.shell(["wm", "size"], check=False)
        m = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", cp.stdout or "")
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    def failure_artifacts(self, label: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "ui-failure"
        if self.settings.dump_ui_on_failure:
            try:
                path = self.dump()
                if path:
                    target = self.temp_dir / f"failure-{safe}.xml"
                    shutil.copy2(path, target)
                    self.console.warning(f"UI dump captured: {target}", component="ui")
            # Diagnostics are strictly best-effort: a malformed/partially
            # transferred UI dump must never replace the original failure.
            except Exception:
                pass
        if self.settings.screenshot_on_failure:
            try:
                target = self.temp_dir / f"failure-{safe}.png"
                if self.adb.screenshot(target):
                    self.console.warning(f"Screenshot captured: {target}", component="ui")
            except Exception:
                pass


class Controller:
    def __init__(self, args: argparse.Namespace, settings: RuntimeSettings, apps: List[AppSpec]):
        self.args = args
        self.settings = settings
        self.report = Report(args.command)
        self.console = Console(settings.log_level, settings.color, settings.log_file, settings.json_console, event_sink=self.report.add)
        self.temp_obj = tempfile.TemporaryDirectory(prefix="gotify-androidctl-")
        self.temp_dir = pathlib.Path(self.temp_obj.name)
        self.runner = Runner(self.console, settings)
        self.adb = ADB(self.runner, settings)
        self.http = CurlClient(self.runner, settings, self.temp_dir)
        self.state = StateStore(settings.state_file, settings.gotify_url, self.console)
        self.ui = UIAutomator(self.adb, self.console, settings, self.temp_dir)
        self.all_apps = [app for app in apps if app.enabled]
        self.apps = self._filter_apps(apps)
        self.secrets = ManagedSecretStore(settings.secret_dir, settings.gotify_url, self.console)
        self.token_overrides: Dict[str, str] = {}
        self.provisioning_actions: Dict[str, str] = {}
        self.server_app_meta: Dict[str, Dict[str, Any]] = {}
        self.asset_actions: Dict[str, Dict[str, Any]] = {}
        self.server_version: str = ""
        self.device = DeviceInfo()
        self.seed_message_ids: List[int] = []
        self._ogg_encoders: Dict[str, str] = {}
        self._interrupted = False
        self._normalize_sound_policy_names()

    @staticmethod
    def _special_sound(value: Optional[str]) -> bool:
        return (value or "").strip().lower() in ("", "keep", "inherit", "silent", "none", "default", "-")

    def _canonical_sound_name(self, value: str) -> str:
        if self._special_sound(value):
            return value
        raw = value.strip()
        if pathlib.Path(raw).name != raw:
            raise ToolError(f"Sound asset must be a filename, not a path: {raw!r}", ExitCode.CONFIG)
        stem = pathlib.Path(raw).stem if pathlib.Path(raw).suffix else raw
        return f"{stem}.{self.settings.audio_format}"

    def _normalize_sound_policy_names(self) -> None:
        # Channel settings, audit and deployment must agree on the exact filename that
        # Android will see. The source may still be WAV/MP3 and is resolved later.
        for app in self.all_apps:
            for policy in app.channels.values():
                if policy.sound and not self._special_sound(policy.sound):
                    policy.sound = self._canonical_sound_name(policy.sound)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.adb.keep_awake(False)
        if self.settings.report_file:
            with contextlib.suppress(Exception):
                self.write_report(self.settings.report_file)
        if self.settings.preserve_temp:
            self.console.info(f"Preserving temporary directory: {self.temp_dir}", component="core")
            # Detach the finalizer so the directory survives process exit.
            finalizer = getattr(self.temp_obj, "_finalizer", None)
            if finalizer is not None:
                finalizer.detach()
        else:
            self.temp_obj.cleanup()

    def event(self, level: str, component: str, item: str, message: str) -> None:
        self.report.add(level, component, item, message)
        getattr(self.console, "success" if level == "ok" else level if hasattr(self.console, level) else "info")(message, component=component, item=item)

    def _filter_apps(self, apps: List[AppSpec]) -> List[AppSpec]:
        out: List[AppSpec] = []
        include = self.settings.include_apps
        exclude = self.settings.exclude_apps
        for app in apps:
            if not app.enabled:
                continue
            hay = [app.key, app.name]
            if include and not any(fnmatch.fnmatchcase(x.lower(), pat.lower()) for x in hay for pat in include):
                continue
            if exclude and any(fnmatch.fnmatchcase(x.lower(), pat.lower()) for x in hay for pat in exclude):
                continue
            out.append(app)
        return out

    def require_tools(self) -> None:
        adb_path = shutil.which(self.settings.adb) if os.path.sep not in self.settings.adb else self.settings.adb
        if not adb_path or not os.path.exists(adb_path):
            raise ToolError("adb not found. On macOS: brew install android-platform-tools", ExitCode.PREFLIGHT)
        curl_path = shutil.which(self.settings.curl) if os.path.sep not in self.settings.curl else self.settings.curl
        if not curl_path or not os.path.exists(curl_path):
            raise ToolError("curl not found. Use --curl /path/to/curl.", ExitCode.PREFLIGHT)
        self.console.success("Required tools found: adb, curl", component="preflight")

    def inspect_device(self) -> DeviceInfo:
        serial = self.adb.select()
        self.settings.serial = serial
        self.device.serial = serial
        self.device.model = self.adb.prop("ro.product.model")
        self.device.manufacturer = self.adb.prop("ro.product.manufacturer")
        self.device.product = self.adb.prop("ro.product.name")
        self.device.android_version = self.adb.prop("ro.build.version.release")
        self.device.fingerprint = self.adb.prop("ro.build.fingerprint")
        try:
            self.device.sdk = int(self.adb.prop("ro.build.version.sdk") or "0")
        except ValueError:
            self.device.sdk = 0
        self.device.gotify_version, self.device.gotify_version_code = self.adb.package_version(self.settings.package)
        self.device.package_uid = self.adb.package_uid(self.settings.package)
        self.device.oem_profile = self.detect_oem_profile()
        self.report.device = dataclasses.asdict(self.device)
        return self.device

    def detect_oem_profile(self) -> str:
        if self.settings.oem_profile != "auto":
            return self.settings.oem_profile
        m = (self.device.manufacturer or "").lower()
        if "samsung" in m:
            return "samsung"
        if any(x in m for x in ("xiaomi", "redmi", "poco")):
            return "xiaomi"
        if any(x in m for x in ("oneplus",)):
            return "oneplus"
        if any(x in m for x in ("oppo", "realme")):
            return "oppo"
        if "google" in m:
            return "pixel"
        if "motorola" in m:
            return "motorola"
        return "aosp"

    @staticmethod
    def semver_tuple(version: str) -> Tuple[int, int, int]:
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version or "")
        if not m:
            return (0, 0, 0)
        return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)

    def preflight(self, require_server: bool = False, require_channels: bool = False) -> None:
        self.require_tools()
        info = self.inspect_device()
        self.console.info(
            f"Device {info.serial}: {info.manufacturer} {info.model}, Android {info.android_version} (API {info.sdk}), user {self.settings.android_user}",
            component="preflight",
        )
        if not self.adb.package_installed(self.settings.package):
            raise ToolError(f"Gotify package '{self.settings.package}' is not installed for Android user {self.settings.android_user}.", ExitCode.PREFLIGHT)
        self.console.success(f"Gotify Android {info.gotify_version or 'version unknown'} is installed", component="preflight")
        if require_channels and info.sdk < 26 and not self.settings.allow_legacy:
            raise ToolError("Android notification channels require Android 8.0 / API 26+. Use --allow-legacy only for non-channel operations.", ExitCode.PREFLIGHT)
        if self.semver_tuple(info.gotify_version) and self.semver_tuple(info.gotify_version) < MIN_GOTIFY_ANDROID_FOR_APP_CHANNELS:
            self.console.warning(
                f"Gotify Android {info.gotify_version} predates per-application notification channels (introduced in 2.6.0).",
                component="preflight",
            )
        if self.settings.wake_device:
            self.adb.wake()
        if self.settings.keep_awake:
            self.adb.keep_awake(True)
        if self.settings.grant_notifications and info.sdk >= 33:
            self.grant_notification_permission()
        if self.settings.battery_whitelist:
            self.apply_battery_whitelist()
        if require_server:
            self.check_server()
        if info.oem_profile == "samsung":
            self.console.warning(
                "Samsung One UI may hide per-app notification categories unless 'Manage notification categories for each app' is enabled in system notification advanced settings.",
                component="preflight",
            )

    def grant_notification_permission(self) -> None:
        cp = self.adb.shell([
            "pm", "grant", "--user", str(self.settings.android_user),
            self.settings.package, "android.permission.POST_NOTIFICATIONS"
        ], check=False, mutating=True)
        if cp.returncode == 0:
            self.console.success("POST_NOTIFICATIONS granted", component="android")
        else:
            self.console.warning("Could not grant POST_NOTIFICATIONS via adb; verify it manually in app settings.", component="android")

    def apply_battery_whitelist(self) -> None:
        cp = self.adb.shell(["dumpsys", "deviceidle", "whitelist", "+" + self.settings.package], check=False, mutating=True)
        if cp.returncode == 0:
            self.console.success("Added Gotify to device-idle whitelist", component="android")
        else:
            self.console.warning("Could not modify device-idle whitelist on this device.", component="android")

    def client_token(self) -> Optional[str]:
        if self.settings.client_token_env:
            value = os.environ.get(self.settings.client_token_env, "").strip()
            if value:
                return value
        if self.settings.client_token_file:
            p = pathlib.Path(os.path.expanduser(self.settings.client_token_file))
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        return None

    def app_token(self, app: AppSpec) -> Optional[str]:
        """Resolve the current application token without ever querying Gotify GET APIs.

        Managed tokens have precedence over legacy env/file sources because a rotation
        performed by this tool makes the managed copy authoritative immediately.
        """
        value = self.token_overrides.get(app.key)
        if value:
            return value
        value = self.secrets.read_token(app.key)
        if value:
            return value
        return app.token()

    def gotify_basic_credentials(self) -> Optional[Tuple[str, str]]:
        username = (self.settings.gotify_username or "").strip()
        password = ""
        if self.settings.gotify_password_env:
            password = os.environ.get(self.settings.gotify_password_env, "")
        elif self.settings.gotify_password_file:
            path = pathlib.Path(os.path.expanduser(self.settings.gotify_password_file))
            if path.is_file():
                password = path.read_text(encoding="utf-8").rstrip("\r\n")
        if not username:
            return None
        if not password:
            raise ToolError(
                "Gotify username is configured but the management password is empty. "
                "Set --gotify-password-env/--gotify-password-file.",
                ExitCode.CONFIG,
            )
        return username, password

    def management_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Mapping[str, Any]] = None,
        form_file: Optional[Tuple[str, pathlib.Path]] = None,
        sensitive: bool = False,
        accept: Sequence[int] = (200, 201, 204),
    ) -> Tuple[int, str]:
        """Call a Gotify management endpoint.

        For sensitive Gotify 3.x operations (notably token rotation), HTTP Basic is
        preferred because Gotify documents Basic requests as already elevated. A
        client token is supported, but it must already have session elevation.
        """
        basic = self.gotify_basic_credentials()
        token = self.client_token()
        if not basic and not token:
            raise ToolError(
                "Gotify management authentication is required. Configure "
                "--gotify-username with --gotify-password-env/--gotify-password-file, "
                "or --client-token-env/--client-token-file.",
                ExitCode.CONFIG,
            )
        try:
            return self.http.request(
                method, path,
                token=None if basic else token,
                basic_auth=basic,
                json_body=json_body,
                form_file=form_file,
                accept=accept,
            )
        except ToolError as exc:
            text = str(exc)
            if sensitive and ("HTTP 403" in text or "403:" in text):
                raise ToolError(
                    f"Gotify refused the sensitive request {method} {path} with HTTP 403. "
                    "Token rotation requires elevated authentication in Gotify 3.x. "
                    "Use Gotify HTTP Basic management credentials or an already-elevated client token.",
                    ExitCode.PROVISION,
                ) from exc
            raise

    def require_http_tool(self) -> None:
        curl_path = shutil.which(self.settings.curl) if os.path.sep not in self.settings.curl else self.settings.curl
        if not curl_path or not os.path.exists(curl_path):
            raise ToolError("curl not found. Use --curl /path/to/curl.", ExitCode.PREFLIGHT)

    def server_preflight(self) -> None:
        self.require_http_tool()
        self.check_server()

    def list_server_applications(self) -> List[Dict[str, Any]]:
        _, body = self.management_request("GET", "/application", accept=(200,))
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Invalid JSON from GET /application: {exc}", ExitCode.NETWORK) from exc
        if not isinstance(payload, list):
            raise ToolError("GET /application did not return an array.", ExitCode.NETWORK)
        result: List[Dict[str, Any]] = []
        for row in payload:
            if isinstance(row, dict) and "id" in row and "name" in row:
                result.append(dict(row))
        return result

    def _match_server_application(
        self, app: AppSpec, server_apps: Sequence[Mapping[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        by_id: Optional[Dict[str, Any]] = None
        if app.app_id is not None:
            for row in server_apps:
                with contextlib.suppress(TypeError, ValueError):
                    if int(row.get("id")) == int(app.app_id):
                        by_id = dict(row)
                        break
            if by_id is not None and str(by_id.get("name", "")) != app.name:
                raise ToolError(
                    f"Configured/cached application ID {app.app_id} for {app.key} belongs to "
                    f"{by_id.get('name')!r}, not {app.name!r}. Refusing to act on a possibly stale ID.",
                    ExitCode.CONFIG,
                )
        exact = [dict(x) for x in server_apps if str(x.get("name", "")) == app.name]
        if len(exact) > 1:
            raise ToolError(
                f"Multiple Gotify Applications have the exact name {app.name!r}; "
                "set app_id explicitly before provisioning.",
                ExitCode.CONFIG,
            )
        if by_id and exact and int(by_id["id"]) != int(exact[0]["id"]):
            raise ToolError(
                f"Gotify Application identity conflict for {app.name}: configured ID "
                f"{app.app_id} differs from exact-name ID {exact[0]['id']}.",
                ExitCode.CONFIG,
            )
        return by_id or (exact[0] if exact else None)

    def _store_token_or_preserve_recovery(self, app: AppSpec, token: str) -> pathlib.Path:
        """Persist a one-time token; retain a recovery copy if normal persistence fails."""
        try:
            path = self.secrets.write_token(app.key, token)
            self.token_overrides[app.key] = token
            return path
        except Exception as exc:
            recovery = self.temp_dir / f"RECOVERY-{app.key}.token"
            try:
                fd = os.open(str(recovery), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(token + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(recovery, 0o600)
                self.settings.preserve_temp = True
            except Exception as recovery_exc:
                raise ToolError(
                    f"CRITICAL: Gotify returned a new one-time token for {app.name}, but both "
                    f"the managed secret store and recovery file failed. Primary error: {exc}; "
                    f"recovery error: {recovery_exc}",
                    ExitCode.PROVISION,
                ) from recovery_exc
            raise ToolError(
                f"Gotify returned a new one-time token for {app.name}, but normal persistence failed: {exc}. "
                f"A 0600 recovery copy was retained at {recovery}; temporary directory will be preserved.",
                ExitCode.PROVISION,
            ) from exc

    def create_application(self, app: AppSpec) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": app.name,
            "description": app.description,
            "defaultPriority": int(app.default_priority),
        }
        if self.settings.dry_run:
            self.console.info(f"DRY-RUN: would create Gotify Application {app.name}", component="provision", item=app.key)
            self.provisioning_actions[app.key] = "would-create"
            return {}
        _, body = self.management_request("POST", "/application", json_body=payload, accept=(200, 201))
        try:
            obj = json.loads(body)
            app_id = int(obj["id"])
            raw_token = obj["token"]
            if not isinstance(raw_token, str) or not raw_token.strip():
                raise TypeError("token is missing/non-string")
        except Exception as exc:
            raise ToolError(
                f"Gotify created/returned an invalid Application response for {app.name}; "
                f"cannot safely capture its one-time token: {exc}",
                ExitCode.PROVISION,
            ) from exc
        app.app_id = app_id
        self.state.set_app_id(app.key, app_id)
        path = self._store_token_or_preserve_recovery(app, raw_token)
        self.provisioning_actions[app.key] = "created"
        self.server_app_meta[app.key] = dict(obj)
        self.console.success(
            f"Created {app.name} -> application ID {app_id}; token saved to {path}",
            component="provision", item=app.key,
        )
        return dict(obj)

    def reconcile_application_metadata(self, app: AppSpec, server_app: Mapping[str, Any]) -> None:
        if app.app_id is None:
            return
        desired = {
            "name": app.name,
            "description": app.description,
            "defaultPriority": int(app.default_priority),
        }
        current = {
            "name": str(server_app.get("name", "")),
            "description": str(server_app.get("description", "")),
            "defaultPriority": int(server_app.get("defaultPriority", 0) or 0),
        }
        if desired == current:
            return
        if self.settings.dry_run:
            self.console.info(
                f"DRY-RUN: would reconcile Gotify metadata for {app.name}",
                component="provision", item=app.key,
            )
            return
        self.management_request(
            "PUT", f"/application/{app.app_id}", json_body=desired, accept=(200,),
        )
        self.console.success(
            f"Reconciled Gotify metadata for {app.name}",
            component="provision", item=app.key,
        )

    def _rotation_confirmed(self, apps: Sequence[AppSpec]) -> bool:
        if self.settings.dry_run:
            return True
        if getattr(self.args, "confirm_token_rotation", False) or self.settings.assume_yes:
            return True
        names = ", ".join(a.name for a in apps)
        if self.settings.non_interactive:
            raise ToolError(
                "Token rotation requested in non-interactive mode without "
                "--confirm-token-rotation (or --yes). Refusing.",
                ExitCode.USAGE,
            )
        print(
            "\nWARNING: rotating a Gotify Application token immediately invalidates the old token "
            "used by existing producers.\nSelected: " + names,
            file=sys.stderr,
        )
        try:
            answer = input("Type ROTATE to continue: ").strip()
        except EOFError:
            answer = ""
        if answer != "ROTATE":
            raise ToolError("Token rotation cancelled.", ExitCode.USAGE)
        return True

    def rotate_application_token(self, app: AppSpec, reason: str = "") -> None:
        if app.app_id is None:
            raise ToolError(f"Application ID unresolved for {app.name}.", ExitCode.PROVISION)
        old = self.app_token(app)
        old_fp = self.secrets.fingerprint(old)
        if self.settings.dry_run:
            self.console.info(
                f"DRY-RUN: would rotate token for {app.name} via /application/{app.app_id}/security",
                component="rotation", item=app.key,
            )
            self.provisioning_actions[app.key] = "would-rotate"
            return
        _, body = self.management_request(
            "PUT", f"/application/{app.app_id}/security",
            json_body={"regenerateToken": True},
            sensitive=True,
            accept=(200,),
        )
        try:
            obj = json.loads(body)
            raw_token = obj["regenerateToken"]["token"]
            if not isinstance(raw_token, str) or not raw_token.strip():
                raise TypeError("regenerateToken.token is not a string")
        except Exception as exc:
            raise ToolError(
                f"Invalid token-rotation response for {app.name}: {exc}",
                ExitCode.PROVISION,
            ) from exc
        path = self._store_token_or_preserve_recovery(app, raw_token)
        self.provisioning_actions[app.key] = "rotated"
        self.console.success(
            f"Rotated token for {app.name}; new token saved to {path}; "
            f"old fingerprint={(old_fp[:12] if old_fp else 'unknown')}",
            component="rotation", item=app.key,
        )
        if reason:
            self.console.info(f"Rotation reason: {reason}", component="rotation", item=app.key)

    def sync_application_icons(
        self,
        server_apps: Optional[Sequence[Mapping[str, Any]]] = None,
        *,
        force: bool = False,
        require_icons: bool = False,
    ) -> None:
        """Upload configured Gotify Application images idempotently.

        Gotify exposes POST /application/{id}/image as multipart/form-data. Since the
        server API does not expose an image-content digest, local SHA-256 state is used
        to avoid needless re-uploads. --force-icon-upload intentionally bypasses it.
        """
        icons_dir = pathlib.Path(self.settings.icons_dir)
        if not icons_dir.is_dir():
            msg = f"Icons directory does not exist: {icons_dir}"
            if require_icons or self.settings.strict:
                raise ToolError(msg, ExitCode.CONFIG)
            self.console.warning(msg, component="icons")
            return
        if server_apps is None:
            server_apps = self.list_server_applications()
        changed = False
        for app in self.apps:
            if not app.icon:
                continue
            if pathlib.Path(app.icon).name != app.icon:
                raise ToolError(f"App {app.key}: icon must be a filename, not a path: {app.icon!r}", ExitCode.CONFIG)
            icon = icons_dir / app.icon
            if not icon.is_file():
                msg = f"Missing icon {icon} for {app.name}"
                if require_icons or self.settings.strict:
                    raise ToolError(msg, ExitCode.CONFIG)
                self.console.warning(msg, component="icons", item=app.key)
                self.asset_actions.setdefault(app.key, {})["icon"] = "missing"
                continue
            row = self._match_server_application(app, server_apps)
            if app.app_id is None and row is not None:
                app.app_id = int(row["id"])
            if app.app_id is None:
                msg = f"Cannot upload icon for {app.name}: application ID unresolved"
                if self.settings.strict:
                    raise ToolError(msg, ExitCode.PROVISION)
                self.console.warning(msg, component="icons", item=app.key)
                continue
            digest = self.local_sha256(icon)
            cached = self.state.get_asset_hash(app.key, "icon_sha256")
            server_has_image = bool(row and row.get("image"))
            if not force and cached == digest and server_has_image:
                self.console.success(f"Icon up-to-date: {app.name} <- {icon.name}", component="icons", item=app.key)
                self.asset_actions.setdefault(app.key, {})["icon"] = "up-to-date"
                continue
            if self.settings.dry_run:
                self.console.info(
                    f"DRY-RUN: would upload {icon} -> /application/{app.app_id}/image",
                    component="dry-run", item=app.key,
                )
                self.asset_actions.setdefault(app.key, {})["icon"] = "would-upload"
                continue
            self.management_request(
                "POST", f"/application/{app.app_id}/image",
                form_file=("file", icon), accept=(200,),
            )
            self.state.set_asset_hash(app.key, "icon_sha256", digest)
            changed = True
            self.asset_actions.setdefault(app.key, {})["icon"] = "uploaded"
            self.console.success(f"Uploaded Gotify icon: {app.name} <- {icon.name}", component="icons", item=app.key)
        if changed:
            self.state.save()

    def provisioning_manifest(self, server_apps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        entries: List[Dict[str, Any]] = []
        for app in self.all_apps:
            server_app = self._match_server_application(app, server_apps) if server_apps else None
            token = self.app_token(app)
            token_path = self.secrets.token_path(app.key)
            effective_app_id = app.app_id
            if effective_app_id is None and server_app is not None:
                with contextlib.suppress(TypeError, ValueError):
                    effective_app_id = int(server_app.get("id"))
            entries.append({
                "category": app.key,
                "name": app.name,
                "applicationId": effective_app_id,
                "description": app.description,
                "defaultPriority": app.default_priority,
                "status": self.provisioning_actions.get(app.key, "existing" if server_app else "unresolved"),
                "tokenPresent": bool(token),
                "tokenFile": str(token_path) if token_path.is_file() else None,
                "tokenMasked": self.secrets.mask(token),
                "tokenSha256": self.secrets.fingerprint(token),
                "assets": {
                    "icon": {
                        "file": app.icon,
                        "path": str(pathlib.Path(self.settings.icons_dir) / app.icon) if app.icon else None,
                        "sha256": self.local_sha256(pathlib.Path(self.settings.icons_dir) / app.icon)
                            if app.icon and (pathlib.Path(self.settings.icons_dir) / app.icon).is_file() else None,
                        "status": self.asset_actions.get(app.key, {}).get("icon"),
                        "serverImage": server_app.get("image") if server_app else None,
                    }
                },
                "serverCreatedAt": server_app.get("createdAt") if server_app else None,
                "serverLastUsed": server_app.get("lastUsed") if server_app else None,
            })
        return {
            "schemaVersion": 1,
            "generatedAt": now,
            "tool": {"name": TOOL_NAME},
            "gotify": {"url": self.settings.gotify_url, "version": self.server_version},
            "security": {
                "rawTokensIncluded": False,
                "note": "Raw tokens are stored only in dedicated 0600 files; this manifest contains masked values and SHA-256 fingerprints.",
            },
            "applications": entries,
        }

    def write_provisioning_manifest(self, server_apps: Sequence[Mapping[str, Any]]) -> Optional[pathlib.Path]:
        if self.settings.dry_run:
            self.console.info("DRY-RUN: provisioning manifest not written", component="provision")
            return None
        target = self.secrets.provisioning_path(self.settings.provisioning_output)
        self.secrets.write_json_atomic(target, self.provisioning_manifest(server_apps), mode=0o600)
        self.console.success(f"Gotify Application Provisioning written to {target}", component="provision")
        return target

    def provision_applications(
        self,
        *,
        create_missing: bool = True,
        rotate_missing_tokens: bool = False,
        require_token_files: bool = False,
        reconcile_metadata: bool = False,
        import_external_tokens: bool = True,
        export_token_bundle: Optional[str] = None,
        token_bundle_format: str = "env",
        show_secrets: bool = False,
        sync_icons: bool = True,
        force_icon_upload: bool = False,
        require_icons: bool = False,
    ) -> List[Dict[str, Any]]:
        """Converge configured categories to Gotify Applications and capture credentials."""
        self.server_preflight()
        server_apps = self.list_server_applications()

        # Validate/bind any existing applications first.
        for app in self.apps:
            existing = self._match_server_application(app, server_apps)
            if existing:
                app.app_id = int(existing["id"])
                self.state.set_app_id(app.key, app.app_id)
                self.server_app_meta[app.key] = existing
                self.provisioning_actions.setdefault(app.key, "existing")
                if reconcile_metadata:
                    self.reconcile_application_metadata(app, existing)
                continue
            if create_missing:
                self.create_application(app)
            else:
                self.provisioning_actions[app.key] = "missing"
        self.state.save()

        if not self.settings.dry_run:
            # Refresh after creation/reconciliation. Gotify 3 GET intentionally omits tokens.
            server_apps = self.list_server_applications()

        missing_tokens: List[AppSpec] = []
        for app in self.apps:
            if app.app_id is None:
                continue
            managed = self.secrets.read_token(app.key)
            if not managed and import_external_tokens:
                external = app.token()
                if external:
                    path = self._store_token_or_preserve_recovery(app, external)
                    managed = external
                    self.provisioning_actions.setdefault(app.key, "token-imported")
                    self.console.success(
                        f"Imported existing token for {app.name} into managed secret file {path}",
                        component="secrets", item=app.key,
                    )
            # Gotify <3 historically exposed token on GET. Import it only if actually present.
            if not managed:
                row = self._match_server_application(app, server_apps)
                gotify_get_token = row.get("token") if row else None
                if isinstance(gotify_get_token, str) and gotify_get_token.strip():
                    path = self._store_token_or_preserve_recovery(app, gotify_get_token)
                    managed = gotify_get_token
                    self.console.success(
                        f"Captured legacy server-exposed token for {app.name} into {path}",
                        component="secrets", item=app.key,
                    )
            if not self.app_token(app):
                self.provisioning_actions[app.key] = "token-missing-locally"
                missing_tokens.append(app)

        if missing_tokens and rotate_missing_tokens:
            self._rotation_confirmed(missing_tokens)
            for app in missing_tokens:
                self.rotate_application_token(app, reason="missing local token during provisioning")
            missing_tokens = [a for a in missing_tokens if not self.app_token(a)]

        if sync_icons:
            self.sync_application_icons(
                server_apps, force=force_icon_upload, require_icons=require_icons
            )
            if not self.settings.dry_run:
                server_apps = self.list_server_applications()

        # Manifest is deliberately generated only after every successfully returned
        # one-time token has been durably persisted.
        manifest = None
        if not self.settings.dry_run:
            server_apps = self.list_server_applications()
            manifest = self.write_provisioning_manifest(server_apps)

        if missing_tokens:
            names = ", ".join(a.name for a in missing_tokens)
            msg = (
                "Existing Gotify applications have no recoverable local token because Gotify 3.x "
                f"no longer returns tokens from GET endpoints: {names}. "
                "Use rotate-tokens or --rotate-missing-tokens to deliberately replace them."
            )
            if require_token_files:
                raise ToolError(msg, ExitCode.PROVISION)
            self.console.warning(msg, component="secrets")

        if export_token_bundle:
            if self.settings.dry_run:
                self.console.info(
                    f"DRY-RUN: would export aggregate token bundle to {export_token_bundle}",
                    component="secrets",
                )
            else:
                target = self.secrets.export_bundle(
                    export_token_bundle, self.apps, self.app_token, token_bundle_format
                )
                self.console.success(f"Exported aggregate token bundle to {target}", component="secrets")

        if show_secrets:
            if self.settings.non_interactive and not self.settings.assume_yes:
                raise ToolError("--show-secrets in non-interactive mode requires --yes.", ExitCode.USAGE)
            for app in self.apps:
                token = self.app_token(app)
                if token:
                    print(f"{app.key}\t{app.app_id or ''}\t{token}")
        return [dict(x) for x in server_apps]

    def rotate_tokens(
        self,
        *,
        reason: str = "",
        export_token_bundle: Optional[str] = None,
        token_bundle_format: str = "env",
        show_secrets: bool = False,
    ) -> None:
        self.server_preflight()
        version = self.semver_tuple(self.server_version)
        if version and version < (3, 0, 0):
            raise ToolError(
                f"Gotify {self.server_version} does not support the Gotify 3 application security rotation contract.",
                ExitCode.PROVISION,
            )
        server_apps = self.list_server_applications()
        targets: List[AppSpec] = []
        for app in self.apps:
            row = self._match_server_application(app, server_apps)
            if not row:
                raise ToolError(f"Gotify Application does not exist: {app.name}", ExitCode.PROVISION)
            app.app_id = int(row["id"])
            self.state.set_app_id(app.key, app.app_id)
            targets.append(app)
        self.state.save()
        self._rotation_confirmed(targets)
        for app in targets:
            self.rotate_application_token(app, reason=reason)

        if not self.settings.dry_run:
            server_apps = self.list_server_applications()
            self.write_provisioning_manifest(server_apps)
            if export_token_bundle:
                target = self.secrets.export_bundle(
                    export_token_bundle, self.apps, self.app_token, token_bundle_format
                )
                self.console.success(f"Exported aggregate token bundle to {target}", component="secrets")
        if show_secrets:
            if self.settings.non_interactive and not self.settings.assume_yes:
                raise ToolError("--show-secrets in non-interactive mode requires --yes.", ExitCode.USAGE)
            for app in self.apps:
                token = self.app_token(app)
                if token:
                    print(f"{app.key}\t{app.app_id or ''}\t{token}")

    def check_server(self) -> None:
        if not self.settings.gotify_url:
            raise ToolError("Gotify server URL is required for this command.", ExitCode.CONFIG)
        status, body = self.http.request("GET", "/version", accept=(200,))
        version = ""
        with contextlib.suppress(Exception):
            obj = json.loads(body)
            version = str(obj.get("version", ""))
        self.server_version = version
        self.report.server = {"url": self.settings.gotify_url, "version": version, "http_status": status}
        self.console.success(f"Gotify server reachable{f' (v{version})' if version else ''}", component="server")

    def resolve_app_ids(self, allow_seed: bool = True) -> None:
        # Config wins, then state cache.
        unresolved: List[AppSpec] = []
        for app in self.apps:
            if app.app_id is None:
                app.app_id = self.state.get_app_id(app.key)
            if app.app_id is None:
                unresolved.append(app)
            else:
                self.console.debug(f"{app.name}: app_id={app.app_id} (config/state)", component="resolve", item=app.key)

        # Management API resolution by exact name is non-destructive. Gotify 3
        # intentionally omits raw tokens from these GET responses.
        management_available = bool(self.client_token() or self.settings.gotify_username)
        if unresolved and management_available:
            try:
                payload = self.list_server_applications()
                by_name = {
                    str(x.get("name", "")): int(x["id"])
                    for x in payload if isinstance(x, dict) and "id" in x
                }
                for app in list(unresolved):
                    if app.name in by_name:
                        app.app_id = by_name[app.name]
                        self.state.set_app_id(app.key, app.app_id)
                        unresolved.remove(app)
                        self.console.success(
                            f"Resolved {app.name} -> application ID {app.app_id} via Gotify management API",
                            component="resolve", item=app.key,
                        )
            except Exception as exc:
                if self.settings.strict:
                    raise
                self.console.warning(f"Gotify management API application resolution failed: {exc}", component="resolve")

        # Last resort: seed a low-priority message. The API response contains appid.
        if unresolved and allow_seed:
            for app in list(unresolved):
                app_token = self.app_token(app)
                if not app_token:
                    self.console.warning(
                        f"Cannot resolve {app.name}: no app_id, cached ID, client token match, app token env/file.",
                        component="resolve", item=app.key,
                    )
                    continue
                try:
                    mid, appid = self.seed_one(app, self.settings.seed_priority)
                    if mid is not None:
                        self.seed_message_ids.append(mid)
                    if appid is not None:
                        app.app_id = appid
                        self.state.set_app_id(app.key, appid)
                        unresolved.remove(app)
                        self.console.success(f"Resolved {app.name} -> application ID {appid} from seed response", component="resolve", item=app.key)
                except Exception as exc:
                    if self.settings.continue_on_error:
                        self.console.error(f"Failed to seed/resolve {app.name}: {exc}", component="resolve", item=app.key)
                    else:
                        raise
                time.sleep(self.settings.seed_wait)
        self.state.save()

        still = [a for a in self.apps if a.app_id is None]
        if still:
            names = ", ".join(a.name for a in still)
            msg = f"Application IDs remain unresolved: {names}"
            if self.settings.strict and not self.settings.dry_run:
                raise ToolError(msg, ExitCode.PROVISION)
            self.console.warning(msg, component="resolve")

    def seed_one(self, app: AppSpec, priority: int) -> Tuple[Optional[int], Optional[int]]:
        token = self.app_token(app)
        payload: Dict[str, Any] = {
            "title": f"{self.settings.seed_title_prefix} {app.name} · P{priority}".strip(),
            "message": self.settings.seed_message,
            "priority": int(priority),
        }
        if token:
            _, body = self.http.request(
                "POST", "/message", token=token, json_body=payload, accept=(200, 201)
            )
        elif app.app_id is not None and (self.client_token() or self.settings.gotify_username):
            # Gotify 3 accepts appid on the client-authenticated create-message
            # endpoint, allowing channel seeding without exposing an app token.
            payload["appid"] = int(app.app_id)
            _, body = self.management_request(
                "POST", "/message", json_body=payload, accept=(200, 201)
            )
        else:
            raise ToolError(
                f"No application token or management appid path is available for {app.name}.",
                ExitCode.CONFIG,
            )
        try:
            obj = json.loads(body)
            mid = int(obj["id"]) if "id" in obj else None
            appid = int(obj["appid"]) if "appid" in obj else None
        except Exception:
            mid, appid = None, None
        self.console.success(f"Seeded {app.name} at priority {priority}", component="seed", item=app.key)
        return mid, appid

    def seed(self, priorities: Optional[List[int]] = None) -> None:
        self.resolve_app_ids(allow_seed=False)
        if priorities is None:
            priorities = [0, 2, 5, 8] if self.settings.seed_all_priorities else [self.settings.seed_priority]
        for app in self.apps:
            token = self.app_token(app)
            management_seed = app.app_id is not None and bool(self.client_token() or self.settings.gotify_username)
            if not token and not management_seed:
                self.console.warning(
                    f"Skipping {app.name}: neither app token nor management appid path is available",
                    component="seed", item=app.key,
                )
                continue
            for p in priorities:
                try:
                    mid, appid = self.seed_one(app, p)
                    if mid is not None:
                        self.seed_message_ids.append(mid)
                    if appid is not None and app.app_id is None:
                        app.app_id = appid
                        self.state.set_app_id(app.key, appid)
                    time.sleep(self.settings.seed_wait)
                except Exception as exc:
                    if self.settings.continue_on_error:
                        self.console.error(str(exc), component="seed", item=app.key)
                        continue
                    raise
        self.state.save()
        if self.settings.cleanup_seeds:
            self.cleanup_seed_messages()

    def cleanup_seed_messages(self) -> None:
        management_available = bool(self.client_token() or self.settings.gotify_username)
        if not management_available:
            self.console.warning(
                "--cleanup-seeds requested but no Gotify management auth is configured; seed messages were kept.",
                component="seed",
            )
            return
        for mid in list(dict.fromkeys(self.seed_message_ids)):
            try:
                self.management_request("DELETE", f"/message/{mid}", accept=(200, 204))
                self.console.success(f"Deleted seed message {mid}", component="seed")
            except Exception as exc:
                if self.settings.continue_on_error:
                    self.console.warning(f"Could not delete seed message {mid}: {exc}", component="seed")
                else:
                    raise

    def sound_files_expected(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for app in self.apps:
            for cls, policy in app.channels.items():
                sound = (policy.sound or "keep").strip()
                if self._special_sound(sound):
                    continue
                result.setdefault(sound, []).append(f"{app.key}:{cls}")
        return result

    @staticmethod
    def local_sha256(path: pathlib.Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _sound_source(self, target_name: str) -> Optional[pathlib.Path]:
        """Resolve a high-quality source for a canonical Android target filename."""
        sounds_dir = pathlib.Path(self.settings.sounds_dir)
        target = pathlib.Path(target_name)
        stem = target.stem
        candidates: List[pathlib.Path] = []
        # Honor explicit preference; WAV first is recommended because it is the lossless master.
        for ext in self.settings.audio_source_preference:
            cand = sounds_dir / f"{stem}.{ext.lstrip('.').lower()}"
            if cand not in candidates:
                candidates.append(cand)
        exact = sounds_dir / target_name
        if exact not in candidates:
            candidates.append(exact)
        return next((x for x in candidates if x.is_file()), None)

    def _transcode_sound(self, source: pathlib.Path, target_name: str) -> pathlib.Path:
        target_ext = pathlib.Path(target_name).suffix.lower().lstrip(".")
        source_ext = source.suffix.lower().lstrip(".")
        if source_ext == target_ext:
            return source
        if self.settings.dry_run:
            self.console.info(
                f"DRY-RUN: would convert {source.name} -> {target_name} ({target_ext})",
                component="audio",
            )
            return source
        ffmpeg = shutil.which(self.settings.ffmpeg) if os.path.sep not in self.settings.ffmpeg else self.settings.ffmpeg
        if not ffmpeg or not os.path.exists(ffmpeg):
            raise ToolError(
                f"ffmpeg is required to convert {source.name} -> {target_name}. "
                "On macOS install it with: brew install ffmpeg; or use --ffmpeg /path/to/ffmpeg.",
                ExitCode.PREFLIGHT,
            )
        src_hash = self.local_sha256(source)
        profile = f"{target_ext}|vorbis-q={self.settings.audio_vorbis_quality:.2f}|v1"
        cache_key = hashlib.sha256((src_hash + "|" + profile).encode("utf-8")).hexdigest()[:20]
        cache_dir = pathlib.Path(self.settings.audio_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        output = cache_dir / f"{pathlib.Path(target_name).stem}-{cache_key}.{target_ext}"
        if output.is_file() and output.stat().st_size > 0:
            self.console.success(
                f"Audio cache hit: {source.name} -> {target_name}", component="audio", item=target_name
            )
            return output
        tmp = output.with_name(output.stem + f".tmp-{os.getpid()}" + output.suffix)
        cmd = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map_metadata", "-1", "-vn",
        ]
        if target_ext == "ogg":
            encoder = self._ogg_encoder(str(ffmpeg))
            if encoder == "vorbis":
                # FFmpeg's native encoder is experimental and stereo-only.
                cmd += ["-ac", "2", "-strict", "-2"]
            cmd += ["-c:a", encoder, "-q:a", str(self.settings.audio_vorbis_quality)]
        elif target_ext == "mp3":
            cmd += ["-c:a", "libmp3lame", "-q:a", "4"]
        elif target_ext == "wav":
            cmd += ["-c:a", "pcm_s16le"]
        else:
            raise ToolError(f"Unsupported audio deployment format: {target_ext}", ExitCode.CONFIG)
        cmd.append(str(tmp))
        try:
            self.runner.run(cmd, timeout=120, check=True, mutating=True)
            if not tmp.is_file() or tmp.stat().st_size == 0:
                raise ToolError(f"ffmpeg produced an empty output for {source}", ExitCode.PROVISION)
            os.replace(tmp, output)
            with contextlib.suppress(OSError):
                os.chmod(output, 0o644)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
        self.console.success(
            f"Converted {source.name} -> {target_name} ({target_ext})", component="audio", item=target_name
        )
        return output

    def _ogg_encoder(self, ffmpeg: str) -> str:
        cached = self._ogg_encoders.get(ffmpeg)
        if cached:
            return cached
        cp = self.runner.run([ffmpeg, "-hide_banner", "-encoders"], timeout=15, check=True)
        encoders = f"{cp.stdout or ''}\n{cp.stderr or ''}"
        if re.search(r"\blibvorbis\b", encoders):
            encoder = "libvorbis"
        elif re.search(r"(?m)^\s*[A-Z.]+\s+vorbis\b", encoders):
            encoder = "vorbis"
            self.console.warning(
                "ffmpeg libvorbis encoder unavailable; using its native Vorbis encoder.",
                component="audio",
            )
        else:
            raise ToolError(
                "ffmpeg has no Vorbis encoder. Install an ffmpeg build with libvorbis or native vorbis support, "
                "or choose --audio-format mp3|wav.",
                ExitCode.PREFLIGHT,
            )
        self._ogg_encoders[ffmpeg] = encoder
        return encoder

    def install_sounds(self) -> None:
        sounds_dir = pathlib.Path(self.settings.sounds_dir)
        expected = self.sound_files_expected()
        if not expected:
            self.console.info("No custom sound files are required by the selected policy.", component="sounds")
            return
        if not sounds_dir.is_dir():
            raise ToolError(f"Sounds directory does not exist: {sounds_dir}", ExitCode.CONFIG)

        remote_dir = self.settings.remote_sounds_dir
        if self.settings.android_user != 0 and remote_dir == DEFAULT_REMOTE_SOUNDS_DIR:
            remote_dir = f"/storage/emulated/{self.settings.android_user}/Notifications/Gotify"
        self.adb.shell(["mkdir", "-p", remote_dir], check=True, mutating=True)

        wanted_remote: List[str] = []
        for filename, used_by in expected.items():
            source = self._sound_source(filename)
            remote = remote_dir.rstrip("/") + "/" + filename
            wanted_remote.append(remote)
            if source is None:
                stem = pathlib.Path(filename).stem
                searched = ", ".join(f"{stem}.{x}" for x in self.settings.audio_source_preference)
                msg = (
                    f"Missing sound source for {filename} in {sounds_dir}; searched {searched} "
                    f"(required by {', '.join(used_by)})"
                )
                if self.settings.strict:
                    raise ToolError(msg, ExitCode.CONFIG)
                self.console.warning(msg, component="sounds")
                continue
            local = self._transcode_sound(source, filename)
            conversion_needed = source.suffix.lower() != pathlib.Path(filename).suffix.lower()
            if self.settings.dry_run and conversion_needed:
                self.console.info(
                    f"DRY-RUN: would install converted {filename} from {source.name} -> {remote}",
                    component="dry-run", item=filename,
                )
                continue
            should_push = self.settings.force_sound_push
            local_hash = self.local_sha256(local) if self.settings.verify_hash else ""
            remote_hash = self.adb.remote_sha256(remote) if self.settings.verify_hash else None
            if self.settings.verify_hash and remote_hash == local_hash:
                should_push = False
                self.console.success(f"Up-to-date: {filename}", component="sounds", item=filename)
            elif not self.settings.verify_hash:
                should_push = True
            else:
                should_push = True
            if should_push:
                if self.settings.dry_run:
                    self.console.info(
                        f"DRY-RUN: would install sound {filename} from {source.name} -> {remote}",
                        component="dry-run", item=filename,
                    )
                else:
                    if not self.adb.push(local, remote):
                        raise ToolError(f"Failed to push {local} -> {remote}", ExitCode.PROVISION)
                    if self.settings.verify_hash:
                        new_hash = self.adb.remote_sha256(remote)
                        if new_hash and new_hash != local_hash:
                            raise ToolError(f"SHA-256 verification failed after pushing {filename}", ExitCode.PROVISION)
                    self.console.success(
                        f"Installed sound: {filename} (source {source.name})", component="sounds", item=filename
                    )
            if self.settings.media_scan == "broadcast":
                if not self.adb.media_scan(remote):
                    self.console.warning(
                        f"Media scanner broadcast failed for {filename}; Android may still index it later.",
                        component="sounds", item=filename,
                    )

        if self.settings.remove_orphan_sounds:
            self._remove_orphan_sounds(remote_dir, set(wanted_remote))

    def _remove_orphan_sounds(self, remote_dir: str, wanted: set[str]) -> None:
        existing = set(self.adb.list_remote_files(remote_dir))
        orphans = sorted(existing - wanted)
        if not orphans:
            return
        if not self.settings.assume_yes and not self.settings.non_interactive:
            print("Orphan sounds to remove:", file=sys.stderr)
            for x in orphans:
                print("  " + x, file=sys.stderr)
            answer = input("Remove these files? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                self.console.info("Orphan removal cancelled.", component="sounds")
                return
        elif self.settings.non_interactive and not self.settings.assume_yes:
            self.console.warning("--remove-orphan-sounds ignored in non-interactive mode without --yes.", component="sounds")
            return
        for remote in orphans:
            if self.adb.remove_remote(remote):
                self.console.success(f"Removed orphan sound: {remote}", component="sounds")

    def channel_id(self, app: AppSpec, cls: str) -> Optional[str]:
        if app.app_id is None:
            return None
        return f"{app.app_id}::{CHANNEL_SUFFIXES[cls]}"

    @staticmethod
    def parse_notification_channels(text: str) -> Dict[str, List[Dict[str, Any]]]:
        records: Dict[str, List[Dict[str, Any]]] = {}
        # NotificationChannel.toString() is normally one line. Use line-based parsing
        # to avoid swallowing unrelated notification contents.
        for line in text.splitlines():
            if "NotificationChannel{" not in line:
                continue
            # Android retains deleted channels in dumpsys output. They may have
            # the same ID as an active replacement and must not drive audit or
            # UI configuration decisions.
            if re.search(r"\bmDeleted=true\b", line):
                continue
            mid = re.search(r"\bmId=(?:'([^']*)'|([^,}\s]+))", line)
            if not mid:
                continue
            cid = mid.group(1) or mid.group(2) or ""
            name = re.search(r"\bmName=([^,}]*)", line)
            importance = re.search(r"\bmImportance=(\d+)", line)
            sound = re.search(r"\bmSound=([^,}]*)", line)
            vibration = re.search(r"\bmVibrationEnabled=(true|false)", line)
            userlocked = re.search(r"\bmUserLockedFields=([^,}]*)", line)
            group = re.search(r"\bmGroup=(?:'([^']*)'|([^,}]*))", line)
            rec = {
                "id": cid,
                "name": name.group(1).strip() if name else None,
                "importance": int(importance.group(1)) if importance else None,
                "sound": sound.group(1).strip() if sound else None,
                "vibration": (vibration.group(1) == "true") if vibration else None,
                "user_locked_fields": userlocked.group(1).strip() if userlocked else None,
                "group": (group.group(1) or group.group(2) or "").strip() if group else None,
                "raw": line.strip(),
            }
            records.setdefault(cid, []).append(rec)
        return records

    @staticmethod
    def sound_uri_to_name(uri: Optional[str], media: Mapping[str, str]) -> Optional[str]:
        if uri is None:
            return None
        value = uri.strip()
        if value.lower() in ("null", "none", ""):
            return "silent"
        if "settings/system/notification_sound" in value or "settings/system/notification" in value:
            return "default"
        m = re.search(r"/(\d+)(?:\?.*)?$", value)
        if m and m.group(1) in media:
            return media[m.group(1)]
        decoded = urllib.parse.unquote(value)
        base = os.path.basename(decoded)
        if "." in base:
            return base
        return value

    @staticmethod
    def is_effectively_silent(record: Mapping[str, Any], actual_sound: Optional[str], desired_importance: Optional[int]) -> bool:
        """Recognise Pixel's low/min channel semantics even when it retains the default URI."""
        if actual_sound == "silent":
            return True
        return bool(
            desired_importance is not None
            and desired_importance <= CHANNEL_EXPECTED_IMPORTANCE["low"]
            and record.get("importance") is not None
            and record.get("importance") <= CHANNEL_EXPECTED_IMPORTANCE["low"]
            and record.get("vibration") is False
        )

    def audit_channels(self, fail_on_drift: bool = False) -> List[AuditEntry]:
        self.resolve_app_ids(allow_seed=False)
        dump = self.adb.dumpsys_notification(self.settings.sensitive_dump)
        records = self.parse_notification_channels(dump)
        media = self.adb.media_map()
        entries: List[AuditEntry] = []
        for app in self.apps:
            for cls in ("min", "low", "normal", "high"):
                policy = app.channels.get(cls, ChannelPolicy(sound="keep", vibration=None, importance=CHANNEL_EXPECTED_IMPORTANCE[cls]))
                cid = self.channel_id(app, cls)
                matches = records.get(cid or "", []) if cid else []
                rec = matches[0] if matches else None
                actual_sound = self.sound_uri_to_name(rec.get("sound") if rec else None, media)
                desired_sound = policy.sound or "keep"
                desired_importance = policy.importance if policy.importance is not None else CHANNEL_EXPECTED_IMPORTANCE[cls]
                drift: List[str] = []
                if not rec:
                    drift.append("channel_missing")
                else:
                    ds = desired_sound.lower() if desired_sound else "keep"
                    if ds not in ("keep", "inherit"):
                        if ds in ("silent", "none"):
                            if not self.is_effectively_silent(rec, actual_sound, desired_importance):
                                drift.append(f"sound:{actual_sound}->silent")
                        elif ds == "default":
                            if actual_sound != "default":
                                drift.append(f"sound:{actual_sound}->default")
                        elif actual_sound != desired_sound:
                            drift.append(f"sound:{actual_sound}->{desired_sound}")
                    if policy.vibration is not None and rec.get("vibration") is not None and rec.get("vibration") != policy.vibration:
                        drift.append(f"vibration:{rec.get('vibration')}->{policy.vibration}")
                    if desired_importance is not None and rec.get("importance") is not None and rec.get("importance") != desired_importance:
                        drift.append(f"importance:{rec.get('importance')}->{desired_importance}")
                entry = AuditEntry(
                    app=app.name, app_key=app.key, app_id=app.app_id, channel=cls,
                    channel_id=cid, exists=bool(rec), desired_sound=desired_sound,
                    actual_sound=actual_sound, desired_vibration=policy.vibration,
                    actual_vibration=rec.get("vibration") if rec else None,
                    desired_importance=desired_importance,
                    actual_importance=rec.get("importance") if rec else None,
                    drift=drift,
                )
                entries.append(entry)
                status = "DRIFT" if drift else "OK"
                msg = f"{app.name}/{cls}: {status}"
                if drift:
                    msg += " [" + ", ".join(drift) + "]"
                    self.console.warning(msg, component="audit", item=f"{app.key}:{cls}")
                else:
                    self.console.success(msg, component="audit", item=f"{app.key}:{cls}")
        self.report.audit = entries
        drifted = [e for e in entries if e.drift]
        if drifted and fail_on_drift:
            raise ToolError(f"Audit detected drift in {len(drifted)} channel(s).", ExitCode.AUDIT_DRIFT)
        return entries

    def wait_for_channel(self, channel_id: str) -> bool:
        deadline = time.monotonic() + max(0.0, self.settings.channel_wait)
        while True:
            records = self.parse_notification_channels(self.adb.dumpsys_notification(False))
            if channel_id in records:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(1.0)

    def ensure_separate_app_channels(self) -> bool:
        mode = self.settings.ensure_separate_channels
        if mode == "skip" or self.device.sdk < 26:
            return True
        # If any resolved app already has an expected per-app channel, the setting is on.
        dump = self.adb.dumpsys_notification(False)
        records = self.parse_notification_channels(dump)
        for app in self.apps:
            if app.app_id is not None:
                cid = self.channel_id(app, "low")
                if cid and cid in records:
                    self.console.success("Per-application Gotify notification channels are active.", component="gotify-settings")
                    return True

        if self.settings.dry_run:
            self.console.info("DRY-RUN: would ensure Gotify 'Separate app notification channels' is enabled.", component="dry-run")
            return True
        if self.settings.ui_mode == "off":
            self.console.warning("Cannot ensure Gotify 'Separate app notification channels' because UI mode is off.", component="gotify-settings")
            return False
        if not self.adb.launch_package(self.settings.package):
            self.console.warning("Could not launch Gotify to enable separate app channels.", component="gotify-settings")
            return False
        time.sleep(self.settings.ui_wait)

        # Navigate semantically: drawer -> Settings -> preference -> Restart.
        drawer_rx = r"^(Open navigation drawer|Apri menu di navigazione|Navigation drawer|Menu)$"
        settings_rx = r"^(Settings|Impostazioni)$"
        separate_rx = r"Separate.*notification.*channels|Separate app notification channels|Canali.*notific.*app|notific.*separat"
        restart_rx = r"^(Restart|Riavvia|Restart app|Riavvia app)$"

        # Try visible Settings first (some layouts expose it directly), then drawer.
        if not self.ui.tap(settings_rx):
            self.ui.tap(drawer_rx)
            if not self.ui.tap(settings_rx, required=True):
                return self._guided_separate_channels("Could not navigate to Gotify Settings.")
        node = self.ui.find_with_scroll(separate_rx)
        if not node:
            return self._guided_separate_channels("Could not find 'Separate app notification channels'.")
        if node.get("checked") is True:
            self.console.success("Gotify separate app notification channels already enabled.", component="gotify-settings")
            return True
        self.ui.tap_node(node)
        # Preference change shows a restart dialog. Restart is preferred because
        # Gotify recreates the channels based on the new setting at startup.
        if not self.ui.tap(restart_rx):
            # 'Later' is not sufficient for immediate provisioning; relaunch package.
            time.sleep(self.settings.ui_wait)
            self.adb.launch_package(self.settings.package)
        time.sleep(max(2.0, self.settings.ui_wait))
        self.console.success("Enabled Gotify separate app notification channels (best-effort UI automation).", component="gotify-settings")
        return True

    def _guided_separate_channels(self, reason: str) -> bool:
        self.ui.failure_artifacts("separate-channels")
        if self.settings.non_interactive or self.settings.ui_mode == "auto" and self.settings.strict:
            self.console.error(reason, component="gotify-settings")
            return False
        self.console.warning(reason, component="gotify-settings")
        self.console.info("On the phone: Gotify → Settings → Separate app notification channels → enable → Restart.", component="gotify-settings")
        return self.guided_wait("Enable the setting and restart Gotify, then press Enter")

    def guided_wait(self, prompt: str) -> bool:
        if self.settings.non_interactive:
            return False
        if self.settings.guided_timeout <= 0:
            input(prompt + ": ")
            return True
        # Portable timeout without relying on GNU read. Use select only on POSIX.
        import select
        print(prompt + f" (timeout {self.settings.guided_timeout:.0f}s): ", end="", file=sys.stderr, flush=True)
        readable, _, _ = select.select([sys.stdin], [], [], self.settings.guided_timeout)
        if not readable:
            print(file=sys.stderr)
            return False
        sys.stdin.readline()
        return True

    def ui_labels(self) -> Dict[str, str]:
        # Regexes deliberately use semantic text and never screen coordinates.
        return {
            "sound": r"^(Sound|Suono|Notification sound|Suono di notifica|Custom sound|Suono personalizzato)$",
            "silent": r"^(Silent|Silenzioso|Silenziosa|None|Nessuno|Nessun suono|Mute|Disattivato)$",
            "alert": r"^(Alert|Avviso|Avvisi|Sound and vibration|Suono e vibrazione)$",
            "my_sounds": r"^(My Sounds|I miei suoni|Sounds|Suoni|Custom|Personalizzato|Local ringtone|Suoneria locale)$",
            "confirm": r"^(OK|Ok|Done|Fine|Save|Salva|Apply|Applica)$",
            "vibration": r"^(Vibration|Vibrate|Vibrazione|Vibra|Allow vibration|Consenti vibrazione)$",
            "back": r"^(Navigate up|Back|Indietro)$",
        }

    @staticmethod
    def _channel_title_regex(cls: str) -> str:
        """Semantic Settings titles for the four Gotify priority channels.

        The English expressions cover AOSP/Pixel.  The Italian alternatives
        keep guided/auto protection usable on the operator's configured locale.
        Known manufacturer families are detected for diagnostics; unknown OEM wording deliberately fails closed and falls back to guided
        configuration rather than guessing a screen coordinate.
        """
        patterns = {
            "min": r"^(Minimum|Minim[ao]|Priorit.{0,16}minim).*(0|priority)",
            "low": r"^(Low|Bass[ao]|Priorit.{0,16}bass).*(1.?3|priority)",
            "normal": r"^(Normal|Priorit.{0,16}normal).*(4.?7|priority)",
            "high": r"^(High|Alt[ao]|Priorit.{0,16}alt).*(> ?7|priority)",
        }
        return patterns.get(cls, r"$^")

    def preflight_channel_page(self, cls: str) -> bool:
        return self.ui.has_visible_text(self._channel_title_regex(cls))

    def _sound_regex(self, filename: str) -> str:
        stem = pathlib.Path(filename).stem
        options = [re.escape(filename), re.escape(stem)]
        return r"^(?:" + "|".join(options) + r")$"

    def configure_channel_ui(self, app: AppSpec, cls: str, policy: ChannelPolicy) -> bool:
        lock_probe = getattr(self.adb, "keyguard_showing", lambda: None)
        locked = lock_probe()
        if locked is True:
            self.console.warning(
                f"Device is locked; refusing {app.name}/{cls} UI automation. Unlock it, then rerun or use guided/manual Settings.",
                component="configure",
            )
            return False
        cid = self.channel_id(app, cls)
        if not cid:
            self.console.warning(f"Cannot configure {app.name}/{cls}: application ID unknown.", component="configure")
            return False
        if not self.adb.open_channel_settings(self.settings.package, cid):
            self.console.warning(f"Could not open Android channel settings for {app.name}/{cls}.", component="configure")
            return False
        time.sleep(self.settings.ui_wait)
        if not self.preflight_channel_page(cls):
            self.console.warning(
                f"Settings did not prove the requested {app.name}/{cls} channel before interaction; refusing UI taps.",
                component="configure",
            )
            self.ui.failure_artifacts(f"{app.key}-{cls}-preflight")
            return False
        labels = self.ui_labels()
        ok = True
        silent_mode = False

        desired_sound = (policy.sound or "keep").strip()
        if desired_sound.lower() not in ("keep", "inherit", ""):
            if desired_sound.lower() in ("silent", "none"):
                if not self._ui_set_silent(labels):
                    ok = False
                else:
                    silent_mode = True
            elif desired_sound.lower() == "default":
                # Default is OEM-specific. Open sound picker and select Default if visible.
                if not self.ui.tap(labels["sound"]):
                    ok = False
                else:
                    node = self.ui.find_with_scroll(r"^(Default|Predefinito|Default notification sound|Suono di notifica predefinito)$")
                    if node:
                        self.ui.tap_node(node)
                        self.ui.tap(labels["confirm"])
                    else:
                        ok = False
            else:
                if not self._ui_set_custom_sound(desired_sound, labels):
                    ok = False

        # Pixel hides the vibration control for a Silent channel. Selecting
        # Silent already guarantees vibration is off, so do not treat the
        # absent control as an automation failure.
        if policy.vibration is not None and not (silent_mode and policy.vibration is False):
            # Return to a known screen because the sound picker may have changed activity.
            self.adb.open_channel_settings(self.settings.package, cid)
            time.sleep(self.settings.ui_wait)
            node = self.ui.find(labels["vibration"])
            if node:
                current = node.get("checked")
                if current is None or current != policy.vibration:
                    if not self.ui.tap_node(node):
                        ok = False
            else:
                # Some OEMs only expose vibration after selecting Alert.
                if policy.vibration:
                    self.ui.tap(labels["alert"])
                    node = self.ui.find(labels["vibration"])
                    if node and node.get("checked") is not True:
                        self.ui.tap_node(node)
                    elif not node:
                        ok = False
                else:
                    ok = False

        if not ok:
            self.ui.failure_artifacts(f"{app.key}-{cls}")
        return ok

    def verify_channel_postcondition(self, app: AppSpec, cls: str) -> bool:
        """Validate the exact requested channel from dumpsys after UI changes."""
        cid = self.channel_id(app, cls)
        if not cid:
            return False
        matching = [e for e in self.audit_channels(fail_on_drift=False) if e.app_key == app.key and e.channel == cls]
        entry = matching[0] if matching else None
        if entry and not entry.drift:
            return True
        detail = ", ".join(entry.drift) if entry else "audit entry missing"
        self.console.warning(
            f"Post-condition failed for {app.name}/{cls}: {detail}. Manual/guided handling required.",
            component="configure",
        )
        self.ui.failure_artifacts(f"{app.key}-{cls}-postcondition")
        return False

    def _ui_set_silent(self, labels: Mapping[str, str]) -> bool:
        # Prefer a top-level Silent radio option.
        node = self.ui.find(labels["silent"])
        if node and node.get("enabled") is not False:
            # Pixel's Alert/Silent selector exposes the active choice with
            # `selected=true`, not a checked radio button.
            if node.get("checked") is True or node.get("selected") is True:
                return True
            return self.ui.tap_node(node)
        # Otherwise use the Sound picker and select None/Silent.
        if self.ui.tap(labels["sound"]):
            time.sleep(self.settings.ui_wait)
            node = self.ui.find_with_scroll(labels["silent"])
            if node:
                self.ui.tap_node(node)
                self.ui.tap(labels["confirm"])
                return True
        return False

    def _ui_set_custom_sound(self, filename: str, labels: Mapping[str, str]) -> bool:
        # Ensure the channel is in alerting mode when such a radio exists.
        alert = self.ui.find(labels["alert"])
        if alert and alert.get("checked") is False:
            self.ui.tap_node(alert)
            time.sleep(self.settings.ui_wait)
        if not self.ui.tap(labels["sound"], required=True):
            return False
        time.sleep(self.settings.ui_wait)
        # On AOSP/Pixel, custom files often live under "My Sounds". On Samsung
        # they may be directly visible, so this is optional.
        self.ui.tap(labels["my_sounds"])
        node = self.ui.find_with_scroll(self._sound_regex(filename))
        if not node:
            return False
        if not self.ui.tap_node(node):
            return False
        self.ui.tap(labels["confirm"])
        return True

    def configure_channels(self, classes: Optional[List[str]] = None, only_drifted: bool = False) -> None:
        classes = classes or ["min", "low", "normal", "high"]
        if self.settings.dry_run:
            for app in self.apps:
                for cls in classes:
                    if cls not in app.channels:
                        continue
                    p = app.channels[cls]
                    cid = self.channel_id(app, cls) or "<application-id-unresolved>"
                    self.console.info(
                        f"DRY-RUN: would configure {app.name}/{cls} ({cid}): sound={p.sound}, vibration={p.vibration}, importance={p.importance}",
                        component="dry-run", item=f"{app.key}:{cls}"
                    )
            return
        self.resolve_app_ids(allow_seed=True)
        drift_entries: Dict[Tuple[str, str], AuditEntry] = {}
        if only_drifted:
            for e in self.audit_channels(fail_on_drift=False):
                if e.drift:
                    drift_entries[(e.app_key, e.channel)] = e
        if self.settings.ui_mode == "off":
            raise ToolError("configure requires --ui auto or --ui guided; Android does not expose a supported API to rewrite channel behavior directly.", ExitCode.UI)
        if self.settings.oem_profile == "auto":
            self.console.warning(
                "OEM/UI profile is auto-detected. Unrecognised channel titles or controls will receive no taps and require guided/manual completion.",
                component="configure",
            )

        for app in self.apps:
            for cls in classes:
                if cls not in app.channels:
                    continue
                entry = drift_entries.get((app.key, cls))
                if only_drifted and not entry:
                    continue
                policy = app.channels[cls]
                # Do not reopen a picker that already matches: Pixel/OEM UI can
                # change page hierarchy after a picker round-trip.  Repair only
                # the dimensions proven to be drifted, then audit the complete
                # desired policy as the post-condition.
                if entry:
                    sound_drift = any(item.startswith("sound:") for item in entry.drift)
                    vibration_drift = any(item.startswith("vibration:") for item in entry.drift)
                    unsupported = [item for item in entry.drift if not item.startswith(("sound:", "vibration:"))]
                    if unsupported:
                        self.console.warning(
                            f"{app.name}/{cls} has unsupported automatic repair drift: {', '.join(unsupported)}; use guided/manual Settings.",
                            component="configure",
                        )
                        if self.settings.strict:
                            raise ToolError(f"Unsupported automatic channel repair for {app.name}/{cls}.", ExitCode.UI)
                        continue
                    policy = ChannelPolicy(
                        sound=policy.sound if sound_drift else "keep",
                        vibration=policy.vibration if vibration_drift else None,
                        importance=policy.importance,
                    )
                cid = self.channel_id(app, cls)
                if cid and not self.wait_for_channel(cid):
                    self.console.warning(f"Channel not present after wait: {app.name}/{cls} ({cid})", component="configure")
                    if self.settings.strict:
                        raise ToolError(f"Missing expected Gotify channel {cid}; verify separate app channels and device connectivity.", ExitCode.UI)
                    continue
                if self.settings.ui_mode == "guided":
                    self.adb.open_channel_settings(self.settings.package, cid or "")
                    sound = policy.sound or "keep"
                    vib = "keep" if policy.vibration is None else ("on" if policy.vibration else "off")
                    if not self.guided_wait(f"Configure {app.name}/{cls}: sound={sound}, vibration={vib}; then press Enter"):
                        raise ToolError("Guided configuration timed out or is unavailable.", ExitCode.UI)
                    continue
                success = False
                for attempt in range(1, max(1, self.settings.ui_retries) + 1):
                    if self.configure_channel_ui(app, cls, policy):
                        success = True
                        break
                    self.console.warning(f"UI configure attempt {attempt}/{self.settings.ui_retries} failed for {app.name}/{cls}", component="configure")
                    time.sleep(self.settings.ui_wait)
                if success and self.verify_channel_postcondition(app, cls):
                    self.console.success(f"Configured {app.name}/{cls}", component="configure", item=f"{app.key}:{cls}")
                elif self.settings.non_interactive:
                    msg = f"Could not configure {app.name}/{cls} automatically."
                    if self.settings.strict:
                        raise ToolError(msg, ExitCode.UI)
                    self.console.error(msg, component="configure", item=f"{app.key}:{cls}")
                else:
                    self.adb.open_channel_settings(self.settings.package, cid or "")
                    sound = policy.sound or "keep"
                    vib = "keep" if policy.vibration is None else ("on" if policy.vibration else "off")
                    if not self.guided_wait(f"AUTO failed. Configure {app.name}/{cls}: sound={sound}, vibration={vib}; then press Enter"):
                        if self.settings.strict:
                            raise ToolError(f"Guided fallback failed for {app.name}/{cls}", ExitCode.UI)

    def notification_permission_status(self) -> Optional[bool]:
        cp = self.adb.shell(["dumpsys", "package", self.settings.package], check=False)
        text = cp.stdout or ""
        m = re.search(r"android\.permission\.POST_NOTIFICATIONS:\s*granted=(true|false)", text)
        return (m.group(1) == "true") if m else None

    def doctor(self) -> Dict[str, Any]:
        self.preflight(require_server=bool(self.settings.gotify_url), require_channels=False)
        checks: Dict[str, Any] = {}
        checks["notification_permission"] = self.notification_permission_status()
        dump = self.adb.dumpsys_notification(False)
        records = self.parse_notification_channels(dump)
        checks["notification_channel_count"] = len(records)
        checks["general_gotify_channels"] = [cid for cid in CHANNEL_SUFFIXES.values() if cid in records]
        checks["per_app_channels_detected"] = any("::gotify_messages_" in cid for cid in records)
        checks["media_sound_count"] = len(self.adb.media_map())
        icons_dir = pathlib.Path(self.settings.icons_dir)
        sounds_dir = pathlib.Path(self.settings.sounds_dir)
        missing_icons = [a.icon for a in self.apps if a.icon and not (icons_dir / a.icon).is_file()]
        missing_sound_sources = []
        for target in self.sound_files_expected():
            if self._sound_source(target) is None:
                missing_sound_sources.append(target)
        checks["assets"] = {
            "root": self.settings.assets_root,
            "icons_dir": str(icons_dir),
            "icons_dir_exists": icons_dir.is_dir(),
            "missing_icons": missing_icons,
            "sounds_dir": str(sounds_dir),
            "sounds_dir_exists": sounds_dir.is_dir(),
            "missing_sound_sources": missing_sound_sources,
        }
        ffmpeg_path = shutil.which(self.settings.ffmpeg) if os.path.sep not in self.settings.ffmpeg else self.settings.ffmpeg
        checks["audio"] = {
            "format": self.settings.audio_format,
            "source_preference": self.settings.audio_source_preference,
            "cache_dir": self.settings.audio_cache_dir,
            "ffmpeg": ffmpeg_path if ffmpeg_path and os.path.exists(ffmpeg_path) else None,
            "vorbis_quality": self.settings.audio_vorbis_quality,
        }
        checks["oem_profile"] = self.device.oem_profile
        checks["gotify_version"] = self.device.gotify_version
        self.console.info(json.dumps(checks, indent=2, ensure_ascii=False), component="doctor")
        return checks

    def snapshot(self, output: str) -> pathlib.Path:
        self.preflight(require_server=False)
        out_path = pathlib.Path(output).expanduser().resolve()
        snap_dir = self.temp_dir / "snapshot"
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / "metadata.json").write_text(json.dumps({
            "tool": {"name": TOOL_NAME},
            "captured_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
            "device": dataclasses.asdict(self.device),
            "settings": {
                "package": self.settings.package,
                "android_user": self.settings.android_user,
                "gotify_url": self.settings.gotify_url,
                "oem_profile": self.device.oem_profile,
            },
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (snap_dir / "notification.txt").write_text(self.adb.dumpsys_notification(self.settings.sensitive_dump), encoding="utf-8", errors="replace")
        cp = self.adb.shell(["dumpsys", "package", self.settings.package], check=False, timeout=30)
        (snap_dir / "package.txt").write_text(cp.stdout or "", encoding="utf-8", errors="replace")
        cp = self.adb.shell(["getprop"], check=False, timeout=30)
        (snap_dir / "getprop.txt").write_text(cp.stdout or "", encoding="utf-8", errors="replace")
        ui = self.ui.dump()
        if ui and ui.exists():
            shutil.copy2(ui, snap_dir / "ui.xml")
        png = snap_dir / "screen.png"
        self.adb.screenshot(png)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w:gz" if str(out_path).endswith((".tar.gz", ".tgz")) else "w"
        with tarfile.open(out_path, mode) as tf:
            for p in sorted(snap_dir.iterdir()):
                tf.add(p, arcname=p.name)
        self.console.success(f"Diagnostic snapshot written to {out_path}", component="snapshot")
        return out_path

    def write_report(self, path: str) -> None:
        self.report.finish()
        target = pathlib.Path(os.path.expanduser(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.console.info(f"Report written to {target}", component="report")

    def bootstrap(self) -> None:
        self.preflight(require_server=True, require_channels=True)
        if not getattr(self.args, "skip_app_provision", False):
            self.provision_applications(
                create_missing=True,
                rotate_missing_tokens=getattr(self.args, "rotate_missing_tokens", False),
                require_token_files=getattr(self.args, "require_token_files", False),
                reconcile_metadata=getattr(self.args, "reconcile_app_metadata", False),
                export_token_bundle=getattr(self.args, "export_token_bundle", None),
                token_bundle_format=getattr(self.args, "token_bundle_format", "env"),
                sync_icons=not getattr(self.args, "skip_icons", False),
                force_icon_upload=getattr(self.args, "force_icon_upload", False),
                require_icons=getattr(self.args, "require_icons", False),
            )
        elif not getattr(self.args, "skip_icons", False):
            server_apps = self.list_server_applications()
            self.sync_application_icons(
                server_apps,
                force=getattr(self.args, "force_icon_upload", False),
                require_icons=getattr(self.args, "require_icons", False),
            )
        # Resolve non-destructively first when possible; this helps detect existing channels.
        self.resolve_app_ids(allow_seed=False)
        if not getattr(self.args, "skip_separate", False):
            enabled = self.ensure_separate_app_channels()
            if not enabled and self.settings.strict:
                raise ToolError("Could not ensure Gotify separate app notification channels.", ExitCode.UI)
        if not getattr(self.args, "skip_sounds", False):
            self.install_sounds()
        if not getattr(self.args, "skip_seed", False):
            self.resolve_app_ids(allow_seed=True)
            # If app IDs were already known but channels are missing, one P2 seed per app
            # can cause the Android client to materialize its channel group.
            records = self.parse_notification_channels(self.adb.dumpsys_notification(False))
            for app in self.apps:
                cid = self.channel_id(app, "low")
                if cid and cid not in records and (
                    self.app_token(app) or (app.app_id is not None and (self.client_token() or self.settings.gotify_username))
                ):
                    mid, appid = self.seed_one(app, self.settings.seed_priority)
                    if mid is not None:
                        self.seed_message_ids.append(mid)
                    if appid is not None:
                        app.app_id = appid
                        self.state.set_app_id(app.key, appid)
                    time.sleep(self.settings.seed_wait)
            self.state.save()
        if not getattr(self.args, "skip_configure", False):
            classes = parse_csv_list(getattr(self.args, "channels", None)) or ["min", "low", "normal", "high"]
            self.configure_channels(classes=classes, only_drifted=getattr(self.args, "only_drifted", False))
        if self.settings.cleanup_seeds and self.seed_message_ids:
            self.cleanup_seed_messages()
        if not getattr(self.args, "skip_audit", False):
            self.audit_channels(fail_on_drift=getattr(self.args, "fail_on_drift", False))


def default_channel_policy(sound: str) -> Dict[str, ChannelPolicy]:
    if sound.lower() in ("silent", "none", "-"):
        return {
            "min": ChannelPolicy("silent", False, 1),
            "low": ChannelPolicy("silent", False, 2),
            "normal": ChannelPolicy("silent", False, 3),
            "high": ChannelPolicy("silent", False, 4),
        }
    return {
        "min": ChannelPolicy("silent", False, 1),
        "low": ChannelPolicy("silent", False, 2),
        "normal": ChannelPolicy(sound, False, 3),
        "high": ChannelPolicy(sound, True, 4),
    }


def built_in_apps() -> List[AppSpec]:
    result: List[AppSpec] = []
    for row in DEFAULT_APPS:
        result.append(AppSpec(
            key=row["id"],
            name=row["name"],
            token_env=row.get("token_env"),
            description=str(row.get("description", "")),
            icon=str(row.get("icon")) if row.get("icon") else None,
            default_priority=int(row.get("default_priority", 0)),
            channels=default_channel_policy(row["sound"]),
        ))
    return result


def parse_bool_or_none(value: Any) -> Optional[bool]:
    if value is None or value == "keep":
        return None
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("1", "true", "yes", "on"):
        return True
    if str(value).lower() in ("0", "false", "no", "off"):
        return False
    raise ToolError(f"Invalid boolean value in config: {value!r}", ExitCode.CONFIG)


def load_config_file(path: pathlib.Path) -> Tuple[Dict[str, Any], List[AppSpec]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ToolError(f"Could not parse config {path}: {exc}", ExitCode.CONFIG) from exc
    if not isinstance(raw, dict):
        raise ToolError("Config root must be a JSON object.", ExitCode.CONFIG)
    if int(raw.get("version", 1)) != CONFIG_VERSION:
        raise ToolError(f"Unsupported config version {raw.get('version')}; expected {CONFIG_VERSION}.", ExitCode.CONFIG)
    apps_raw = raw.get("apps", [])
    if not isinstance(apps_raw, list):
        raise ToolError("config.apps must be an array.", ExitCode.CONFIG)
    apps: List[AppSpec] = []
    seen: set[str] = set()
    for item in apps_raw:
        if not isinstance(item, dict):
            raise ToolError("Each app entry must be an object.", ExitCode.CONFIG)
        key = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not key or not re.match(r"^[A-Za-z0-9_.-]+$", key):
            raise ToolError(f"Invalid app id/key: {key!r}", ExitCode.CONFIG)
        if key in seen:
            raise ToolError(f"Duplicate app id/key: {key}", ExitCode.CONFIG)
        seen.add(key)
        if not name:
            raise ToolError(f"App {key} is missing name.", ExitCode.CONFIG)
        if "token" in item:
            raise ToolError(f"App {key}: direct token values in config are intentionally unsupported; use token_env or token_file.", ExitCode.CONFIG)
        base_sound = str(item.get("sound", "silent"))
        channels = default_channel_policy(base_sound)
        channel_raw = item.get("channels", {})
        if channel_raw:
            if not isinstance(channel_raw, dict):
                raise ToolError(f"App {key}: channels must be an object.", ExitCode.CONFIG)
            for cls, cfg in channel_raw.items():
                if cls not in CHANNEL_SUFFIXES:
                    raise ToolError(f"App {key}: unknown channel class {cls!r}.", ExitCode.CONFIG)
                if not isinstance(cfg, dict):
                    raise ToolError(f"App {key}/{cls}: policy must be an object.", ExitCode.CONFIG)
                sound = cfg.get("sound", channels[cls].sound)
                vibration = parse_bool_or_none(cfg.get("vibration", channels[cls].vibration))
                importance = cfg.get("importance", channels[cls].importance)
                if importance == "keep":
                    importance = None
                elif importance is not None:
                    importance = int(importance)
                channels[cls] = ChannelPolicy(str(sound) if sound is not None else None, vibration, importance)
        app_id = item.get("app_id")
        apps.append(AppSpec(
            key=key,
            name=name,
            enabled=bool(item.get("enabled", True)),
            app_id=int(app_id) if app_id is not None else None,
            token_env=str(item.get("token_env")) if item.get("token_env") else None,
            token_file=str(item.get("token_file")) if item.get("token_file") else None,
            description=str(item.get("description", "")),
            icon=str(item.get("icon")) if item.get("icon") else None,
            default_priority=int(item.get("default_priority", item.get("defaultPriority", 0))),
            channels=channels,
        ))
    return raw, apps


def deep_get(data: Mapping[str, Any], path: Sequence[str], default: Any = None) -> Any:
    cur: Any = data
    for part in path:
        if not isinstance(cur, Mapping) or part not in cur:
            return default
        cur = cur[part]
    return cur


def env_or_none(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value if value not in (None, "") else None


def first_not_none(*values: Any) -> Any:
    for x in values:
        if x is not None:
            return x
    return None


def parse_csv_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def normalize_patterns(values: Optional[List[str]]) -> List[str]:
    result: List[str] = []
    for value in values or []:
        result.extend(parse_csv_list(value))
    return result


def config_path_from_argv(argv: Sequence[str]) -> Tuple[Optional[str], bool]:
    path: Optional[str] = None
    no_config = False
    for i, arg in enumerate(argv):
        if arg == "--no-config":
            no_config = True
        elif arg in ("--config", "-c") and i + 1 < len(argv):
            path = argv[i + 1]
        elif arg.startswith("--config="):
            path = arg.split("=", 1)[1]
    if no_config:
        return None, True
    if path:
        return path, False
    default = pathlib.Path("./gotify-android.json")
    return (str(default) if default.exists() else None), False




def _resolve_path(value: str, base: pathlib.Path) -> str:
    p = pathlib.Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not p.is_absolute():
        p = base / p
    return str(p.resolve())


def _discover_assets_root(config_base: pathlib.Path) -> pathlib.Path:
    """Find the repository asset root without depending on the caller's CWD."""
    candidates: List[pathlib.Path] = []
    # Preferred layout: utils/gotify-androidctl/<config> with sibling ../icons ../sounds.
    candidates.extend([config_base.parent, config_base])
    with contextlib.suppress(Exception):
        candidates.append(pathlib.Path(__file__).resolve().parent.parent)
    with contextlib.suppress(Exception):
        candidates.append(pathlib.Path(sys.argv[0]).resolve().parent.parent)
    candidates.append(pathlib.Path.cwd())
    seen: set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if (cand / DEFAULT_ICONS_DIR).is_dir() or (cand / DEFAULT_SOUNDS_DIR).is_dir():
            return cand.resolve()
    return config_base.resolve()

def runtime_settings(args: argparse.Namespace, cfg: Mapping[str, Any], config_path: Optional[str], no_config: bool) -> RuntimeSettings:
    gotify_cfg = cfg.get("gotify", {}) if isinstance(cfg.get("gotify", {}), Mapping) else {}
    android_cfg = cfg.get("android", {}) if isinstance(cfg.get("android", {}), Mapping) else {}
    http_cfg = cfg.get("http", {}) if isinstance(cfg.get("http", {}), Mapping) else {}
    ui_cfg = cfg.get("ui", {}) if isinstance(cfg.get("ui", {}), Mapping) else {}
    policy_cfg = cfg.get("policy", {}) if isinstance(cfg.get("policy", {}), Mapping) else {}
    assets_cfg = cfg.get("assets", {}) if isinstance(cfg.get("assets", {}), Mapping) else {}
    audio_cfg = assets_cfg.get("audio", {}) if isinstance(assets_cfg.get("audio", {}), Mapping) else {}

    config_base = pathlib.Path(config_path).expanduser().resolve().parent if config_path else pathlib.Path.cwd()
    # CLI/env paths are CWD-relative; JSON asset paths are config-relative. This makes
    # repository configs relocatable and independent of the launch directory.
    if args.assets_root:
        assets_root = pathlib.Path(_resolve_path(args.assets_root, pathlib.Path.cwd()))
    elif env_or_none("GOTIFY_ASSETS_ROOT"):
        assets_root = pathlib.Path(_resolve_path(env_or_none("GOTIFY_ASSETS_ROOT") or ".", pathlib.Path.cwd()))
    elif assets_cfg.get("root") is not None:
        assets_root = pathlib.Path(_resolve_path(str(assets_cfg.get("root")), config_base))
    elif cfg.get("assets_root") is not None:
        assets_root = pathlib.Path(_resolve_path(str(cfg.get("assets_root")), config_base))
    else:
        assets_root = _discover_assets_root(config_base)

    def asset_dir(cli_value: Optional[str], env_name: str, asset_key: str, legacy_key: str, default_name: str) -> str:
        if cli_value:
            return _resolve_path(cli_value, pathlib.Path.cwd())
        ev = env_or_none(env_name)
        if ev:
            return _resolve_path(ev, pathlib.Path.cwd())
        if assets_cfg.get(asset_key) is not None:
            return _resolve_path(str(assets_cfg.get(asset_key)), assets_root)
        if cfg.get(legacy_key) is not None:
            # Backward compatibility: old top-level paths were working-directory/config-local paths.
            return _resolve_path(str(cfg.get(legacy_key)), config_base)
        return _resolve_path(default_name, assets_root)

    icons_dir = asset_dir(args.icons_dir, "GOTIFY_ICONS_DIR", "icons_dir", "icons_dir", DEFAULT_ICONS_DIR)
    sounds_dir = asset_dir(args.sounds_dir, "SOUNDS_DIR", "sounds_dir", "sounds_dir", DEFAULT_SOUNDS_DIR)
    audio_format = str(first_not_none(args.audio_format, env_or_none("GOTIFY_AUDIO_FORMAT"), audio_cfg.get("format"), "ogg")).lower()
    pref_raw = first_not_none(args.audio_source_preference, env_or_none("GOTIFY_AUDIO_SOURCE_PREFERENCE"), audio_cfg.get("source_preference"), list(DEFAULT_AUDIO_SOURCE_PREFERENCE))
    if isinstance(pref_raw, str):
        audio_source_preference = [x.lower().lstrip(".") for x in parse_csv_list(pref_raw)]
    elif isinstance(pref_raw, Sequence):
        audio_source_preference = [str(x).lower().lstrip(".") for x in pref_raw if str(x).strip()]
    else:
        audio_source_preference = list(DEFAULT_AUDIO_SOURCE_PREFERENCE)
    cache_raw = first_not_none(args.audio_cache_dir, audio_cfg.get("cache_dir"), DEFAULT_AUDIO_CACHE_DIR)
    audio_cache_dir = _resolve_path(str(cache_raw), config_base if audio_cfg.get("cache_dir") is not None and not args.audio_cache_dir else pathlib.Path.cwd())

    url = first_not_none(args.gotify_url, env_or_none("GOTIFY_URL"), gotify_cfg.get("url"))
    package = first_not_none(args.package, env_or_none("GOTIFY_PACKAGE"), android_cfg.get("package"), DEFAULT_PACKAGE)
    remote = first_not_none(args.remote_sounds_dir, env_or_none("GOTIFY_REMOTE_SOUNDS_DIR"), android_cfg.get("remote_sounds_dir"), DEFAULT_REMOTE_SOUNDS_DIR)
    serial = first_not_none(args.serial, env_or_none("ANDROID_SERIAL"), android_cfg.get("serial"))
    state_file = first_not_none(args.state_file, cfg.get("state_file"), DEFAULT_STATE_FILE)

    return RuntimeSettings(
        config_path=config_path,
        no_config=no_config,
        state_file=str(state_file),
        gotify_url=str(url).rstrip("/") if url else None,
        package=str(package),
        assets_root=str(assets_root),
        icons_dir=str(icons_dir),
        sounds_dir=str(sounds_dir),
        remote_sounds_dir=str(remote),
        audio_format=audio_format,
        audio_source_preference=audio_source_preference,
        audio_cache_dir=str(audio_cache_dir),
        ffmpeg=str(first_not_none(args.ffmpeg, audio_cfg.get("ffmpeg"), "ffmpeg")),
        audio_vorbis_quality=float(first_not_none(args.audio_vorbis_quality, audio_cfg.get("vorbis_quality"), 5.0)),
        serial=str(serial) if serial else None,
        transport_id=args.transport_id,
        android_user=int(first_not_none(args.android_user, android_cfg.get("user"), 0)),
        adb=str(first_not_none(args.adb, android_cfg.get("adb"), "adb")),
        curl=str(first_not_none(args.curl, http_cfg.get("curl"), "curl")),
        adb_host=first_not_none(args.adb_host, android_cfg.get("adb_host")),
        adb_port=int(first_not_none(args.adb_port, android_cfg.get("adb_port"), 5037)) if first_not_none(args.adb_port, android_cfg.get("adb_port")) is not None else None,
        allow_emulator=bool(first_not_none(args.allow_emulator, android_cfg.get("allow_emulator"), False)),
        allow_legacy=bool(first_not_none(args.allow_legacy, android_cfg.get("allow_legacy"), False)),
        wait_device=float(first_not_none(args.wait_device, android_cfg.get("wait_device"), 5.0)),
        dry_run=bool(args.dry_run),
        non_interactive=bool(args.non_interactive),
        assume_yes=bool(args.assume_yes),
        strict=bool(args.strict),
        continue_on_error=bool(args.continue_on_error),
        log_level=str(first_not_none(args.log_level, cfg.get("log_level"), "info")),
        log_file=first_not_none(args.log_file, cfg.get("log_file")),
        color=str(first_not_none(args.color, cfg.get("color"), "auto")),
        report_file=first_not_none(args.report, cfg.get("report_file")),
        json_console=bool(args.json_console),
        include_apps=normalize_patterns(args.app),
        exclude_apps=normalize_patterns(args.exclude_app),
        insecure=bool(first_not_none(args.insecure, http_cfg.get("insecure"), False)),
        cacert=first_not_none(args.cacert, http_cfg.get("cacert")),
        client_cert=first_not_none(args.client_cert, http_cfg.get("client_cert")),
        client_key=first_not_none(args.client_key, http_cfg.get("client_key")),
        client_p12=first_not_none(args.client_p12, http_cfg.get("client_p12")),
        client_p12_password_env=first_not_none(args.client_p12_password_env, http_cfg.get("client_p12_password_env")),
        proxy=first_not_none(args.proxy, http_cfg.get("proxy")),
        no_proxy=first_not_none(args.no_proxy, http_cfg.get("no_proxy")),
        http_user=first_not_none(args.http_user, http_cfg.get("user")),
        http_password_env=first_not_none(args.http_password_env, http_cfg.get("password_env")),
        http_bearer_env=first_not_none(args.http_bearer_env, http_cfg.get("bearer_env")),
        headers=list(http_cfg.get("headers", [])) + (args.header or []),
        header_envs=list(http_cfg.get("header_envs", [])) + (args.header_env or []),
        connect_timeout=float(first_not_none(args.connect_timeout, http_cfg.get("connect_timeout"), 5.0)),
        request_timeout=float(first_not_none(args.request_timeout, http_cfg.get("request_timeout"), 20.0)),
        retries=int(first_not_none(args.retries, http_cfg.get("retries"), 2)),
        retry_delay=float(first_not_none(args.retry_delay, http_cfg.get("retry_delay"), 1.0)),
        client_token_env=first_not_none(args.client_token_env, gotify_cfg.get("client_token_env")),
        client_token_file=first_not_none(args.client_token_file, gotify_cfg.get("client_token_file")),
        gotify_username=first_not_none(args.gotify_username, gotify_cfg.get("username")),
        gotify_password_env=first_not_none(args.gotify_password_env, gotify_cfg.get("password_env")),
        gotify_password_file=first_not_none(args.gotify_password_file, gotify_cfg.get("password_file")),
        secret_dir=str(first_not_none(args.secret_dir, gotify_cfg.get("secret_dir"), DEFAULT_SECRET_DIR)),
        provisioning_output=first_not_none(args.provisioning_output, gotify_cfg.get("provisioning_output")),
        ui_mode=str(first_not_none(args.ui, ui_cfg.get("mode"), "auto")),
        ui_wait=float(first_not_none(args.ui_wait, ui_cfg.get("wait"), 1.0)),
        ui_retries=int(first_not_none(args.ui_retries, ui_cfg.get("retries"), 2)),
        ui_scrolls=int(first_not_none(args.ui_scrolls, ui_cfg.get("scrolls"), 8)),
        ui_locale=str(first_not_none(args.ui_locale, ui_cfg.get("locale"), "auto")),
        oem_profile=str(first_not_none(args.oem_profile, ui_cfg.get("oem_profile"), "auto")),
        screenshot_on_failure=bool(first_not_none(args.screenshot_on_failure, ui_cfg.get("screenshot_on_failure"), True)),
        dump_ui_on_failure=bool(first_not_none(args.dump_ui_on_failure, ui_cfg.get("dump_ui_on_failure"), True)),
        guided_timeout=float(first_not_none(args.guided_timeout, ui_cfg.get("guided_timeout"), 0.0)),
        ensure_separate_channels=str(first_not_none(args.ensure_separate_channels, ui_cfg.get("ensure_separate_channels"), "auto")),
        wake_device=bool(first_not_none(args.wake_device, android_cfg.get("wake_device"), True)),
        keep_awake=bool(first_not_none(args.keep_awake, android_cfg.get("keep_awake"), True)),
        grant_notifications=bool(first_not_none(args.grant_notifications, android_cfg.get("grant_notifications"), True)),
        battery_whitelist=bool(first_not_none(args.battery_whitelist, android_cfg.get("battery_whitelist"), False)),
        seed_priority=int(first_not_none(args.seed_priority, policy_cfg.get("seed_priority"), 2)),
        seed_all_priorities=bool(first_not_none(args.seed_all_priorities, policy_cfg.get("seed_all_priorities"), False)),
        seed_wait=float(first_not_none(args.seed_wait, policy_cfg.get("seed_wait"), 1.0)),
        channel_wait=float(first_not_none(args.channel_wait, policy_cfg.get("channel_wait"), 12.0)),
        seed_title_prefix=str(first_not_none(args.seed_title_prefix, policy_cfg.get("seed_title_prefix"), "[BOOTSTRAP]")),
        seed_message=str(first_not_none(args.seed_message, policy_cfg.get("seed_message"), "Temporary provisioning message used to materialize/verify Gotify Android notification channels.")),
        cleanup_seeds=bool(first_not_none(args.cleanup_seeds, policy_cfg.get("cleanup_seeds"), False)),
        media_scan=str(first_not_none(args.media_scan, android_cfg.get("media_scan"), "broadcast")),
        verify_hash=bool(first_not_none(args.verify_hash, android_cfg.get("verify_hash"), True)),
        force_sound_push=bool(args.force_sound_push),
        remove_orphan_sounds=bool(args.remove_orphan_sounds),
        preserve_temp=bool(args.preserve_temp),
        sensitive_dump=bool(args.sensitive_dump),
    )


def add_common_flags(p: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    opt_default = argparse.SUPPRESS if suppress_defaults else None
    g = p.add_argument_group("configuration")
    g.add_argument("-c", "--config", help="JSON config file (default: ./gotify-android.json if present)")
    g.add_argument("--no-config", action="store_true", help="Ignore config files and use built-ins/CLI/env only")
    g.add_argument("--state-file", help=f"App-ID cache/state path (default: {DEFAULT_STATE_FILE})")
    g.add_argument("--gotify-url", help="Gotify server base URL (or GOTIFY_URL)")
    g.add_argument("--package", help=f"Gotify Android package (default: {DEFAULT_PACKAGE})")
    g.add_argument("--assets-root", help="Asset root; config-relative when set in JSON, CWD-relative on CLI")
    g.add_argument("--icons-dir", help=f"Gotify Application icon directory (default under assets root: {DEFAULT_ICONS_DIR})")
    g.add_argument("--sounds-dir", help=f"Notification sound source directory (default under assets root: {DEFAULT_SOUNDS_DIR})")
    g.add_argument("--remote-sounds-dir", help=f"Android destination (default: {DEFAULT_REMOTE_SOUNDS_DIR})")
    g.add_argument("--app", action="append", help="Include app key/name glob; repeat or comma-separate (e.g. security,money_*)")
    g.add_argument("--exclude-app", action="append", help="Exclude app key/name glob; repeat or comma-separate")

    d = p.add_argument_group("ADB/device")
    d.add_argument("--adb", help="adb binary/path")
    d.add_argument("--serial", help="ADB device serial (or ANDROID_SERIAL)")
    d.add_argument("--transport-id", type=int, help="ADB transport ID instead of serial")
    d.add_argument("--adb-host", help="ADB server host (-H)")
    d.add_argument("--adb-port", type=int, help="ADB server port (-P)")
    d.add_argument("--android-user", type=int, help="Android user/work-profile ID (default 0)")
    d.add_argument("--wait-device", type=float, help="Seconds to wait for a usable device")
    d.add_argument("--allow-emulator", action="store_true", default=opt_default, help="Allow automatic emulator selection")
    d.add_argument("--allow-legacy", action="store_true", default=opt_default, help="Allow Android < API 26 for non-channel operations")
    d.add_argument("--wake-device", dest="wake_device", action="store_true", default=opt_default, help="Wake/dismiss non-secure keyguard before UI work")
    d.add_argument("--no-wake-device", dest="wake_device", action="store_false", default=opt_default, help="Do not wake device")
    d.add_argument("--keep-awake", dest="keep_awake", action="store_true", default=opt_default, help="Keep device awake over USB during the run")
    d.add_argument("--no-keep-awake", dest="keep_awake", action="store_false", default=opt_default, help="Do not change stay-awake behavior")
    d.add_argument("--grant-notifications", dest="grant_notifications", action="store_true", default=opt_default, help="Attempt to grant POST_NOTIFICATIONS on API 33+")
    d.add_argument("--no-grant-notifications", dest="grant_notifications", action="store_false", default=opt_default, help="Do not grant notification permission")
    d.add_argument("--battery-whitelist", action="store_true", default=opt_default, help="Best-effort add Gotify to device-idle whitelist")

    h = p.add_argument_group("HTTP/TLS/reverse proxy")
    h.add_argument("--curl", help="curl binary/path")
    h.add_argument("-k", "--insecure", action="store_true", default=opt_default, help="Disable TLS certificate verification")
    h.add_argument("--cacert", help="Custom CA certificate PEM")
    h.add_argument("--client-cert", help="mTLS client certificate PEM")
    h.add_argument("--client-key", help="mTLS client private key PEM")
    h.add_argument("--client-p12", help="mTLS PKCS#12 client certificate")
    h.add_argument("--client-p12-password-env", help="Environment variable containing PKCS#12 password")
    h.add_argument("--proxy", help="HTTP(S) proxy URL for curl")
    h.add_argument("--no-proxy", help="curl no-proxy hosts")
    h.add_argument("--http-user", help="HTTP Basic username for a reverse proxy")
    h.add_argument("--http-password-env", help="Env var containing HTTP Basic password")
    h.add_argument("--http-bearer-env", help="Env var containing reverse-proxy Bearer token")
    h.add_argument("--header", action="append", help="Additional HTTP header; repeatable")
    h.add_argument("--header-env", action="append", help="Secret header from env: 'Header-Name=ENV_VAR'; repeatable")
    h.add_argument("--connect-timeout", type=float, help="HTTP connect timeout seconds")
    h.add_argument("--request-timeout", type=float, help="HTTP total timeout seconds")
    h.add_argument("--retries", type=int, help="HTTP retries after the first attempt")
    h.add_argument("--retry-delay", type=float, help="Initial exponential-backoff delay seconds")
    h.add_argument("--client-token-env", help="Env var containing a Gotify client token for management/app resolution")
    h.add_argument("--client-token-file", help="File containing a Gotify client token")
    h.add_argument("--gotify-username", help="Gotify username for management HTTP Basic auth (recommended for token rotation)")
    h.add_argument("--gotify-password-env", help="Environment variable containing Gotify management password")
    h.add_argument("--gotify-password-file", help="File containing Gotify management password")
    h.add_argument("--secret-dir", help=f"Managed per-category application-token directory (default: {DEFAULT_SECRET_DIR})")
    h.add_argument("--provisioning-output", help="Gotify Application Provisioning JSON path (default: under managed secret directory)")

    u = p.add_argument_group("UI automation")
    u.add_argument("--ui", choices=["auto", "guided", "off"], help="Channel configuration mode")
    u.add_argument("--ui-wait", type=float, help="Delay after each UI action")
    u.add_argument("--ui-retries", type=int, help="Automatic UI attempts per channel")
    u.add_argument("--ui-scrolls", type=int, help="Maximum semantic-list swipes while finding a sound")
    u.add_argument("--ui-locale", choices=["auto", "en", "it"], help="Preferred UI label locale")
    u.add_argument("--oem-profile", choices=["auto", "aosp", "pixel", "samsung", "xiaomi", "oneplus", "oppo", "motorola", "generic"], help="OEM-specific UI profile")
    u.add_argument("--screenshot-on-failure", dest="screenshot_on_failure", action="store_true", default=opt_default, help="Capture screenshot when UI automation fails")
    u.add_argument("--no-screenshot-on-failure", dest="screenshot_on_failure", action="store_false", default=opt_default)
    u.add_argument("--dump-ui-on-failure", dest="dump_ui_on_failure", action="store_true", default=opt_default, help="Preserve UI XML on automation failure")
    u.add_argument("--no-dump-ui-on-failure", dest="dump_ui_on_failure", action="store_false", default=opt_default)
    u.add_argument("--guided-timeout", type=float, help="Seconds to wait for guided Enter; 0 means indefinitely")
    u.add_argument("--ensure-separate-channels", choices=["auto", "on", "skip"], help="Ensure Gotify 'Separate app notification channels'")

    s = p.add_argument_group("seed/channel materialization")
    s.add_argument("--seed-priority", type=int, help="Priority for one-per-app materialization seed (default 2)")
    s.add_argument("--seed-all-priorities", action="store_true", default=opt_default, help="Seed P0/P2/P5/P8 instead of one priority")
    s.add_argument("--seed-wait", type=float, help="Delay between seed pushes")
    s.add_argument("--channel-wait", type=float, help="Seconds to poll for expected Android channel")
    s.add_argument("--seed-title-prefix", help="Seed message title prefix")
    s.add_argument("--seed-message", help="Seed message body")
    s.add_argument("--cleanup-seeds", action="store_true", default=opt_default, help="Delete seed messages afterward (requires client token)")

    so = p.add_argument_group("sound deployment")
    so.add_argument("--audio-format", choices=list(SUPPORTED_AUDIO_FORMATS), help="Android deployment format (default: ogg/Vorbis)")
    so.add_argument("--audio-source-preference", help="Comma-separated source preference (default: wav,ogg,mp3)")
    so.add_argument("--audio-cache-dir", help=f"Converted audio cache (default: {DEFAULT_AUDIO_CACHE_DIR})")
    so.add_argument("--ffmpeg", help="ffmpeg executable/path used when source conversion is required")
    so.add_argument("--audio-vorbis-quality", type=float, help="ffmpeg libvorbis quality for OGG output (default 5.0)")
    so.add_argument("--media-scan", choices=["broadcast", "none"], help="How to request MediaStore indexing")
    so.add_argument("--verify-hash", dest="verify_hash", action="store_true", default=opt_default, help="SHA-256 compare before/after push")
    so.add_argument("--no-verify-hash", dest="verify_hash", action="store_false", default=opt_default)
    so.add_argument("--force-sound-push", action="store_true", help="Push sounds even when SHA-256 matches")
    so.add_argument("--remove-orphan-sounds", action="store_true", help="Remove unreferenced files from the managed remote sound directory")

    b = p.add_argument_group("execution/logging")
    b.add_argument("-n", "--dry-run", action="store_true", help="Print/validate actions without changing device/server")
    b.add_argument("--non-interactive", action="store_true", help="Never prompt for user input")
    b.add_argument("-y", "--yes", dest="assume_yes", action="store_true", help="Assume yes for destructive optional actions")
    b.add_argument("--strict", action="store_true", help="Treat unsupported/ambiguous conditions as failures")
    b.add_argument("--continue-on-error", action="store_true", help="Continue across per-app failures where safe")
    b.add_argument("--log-level", choices=["debug", "info", "warning", "error"], help="Console/log verbosity")
    b.add_argument("--log-file", help="Append JSONL operational log to path")
    b.add_argument("--color", choices=["auto", "always", "never"], help="Console color policy")
    b.add_argument("--json-console", action="store_true", help="Emit console logs as JSON lines")
    b.add_argument("--report", help="Write final JSON report")
    b.add_argument("--preserve-temp", action="store_true", help="Preserve temporary work directory")
    b.add_argument("--sensitive-dump", action="store_true", help="Use dumpsys notification --noredact (may expose notification content)")


def build_parser() -> argparse.ArgumentParser:
    common_root = argparse.ArgumentParser(add_help=False)
    add_common_flags(common_root, suppress_defaults=False)
    common_sub = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    add_common_flags(common_sub, suppress_defaults=True)
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Enterprise provisioning/audit utility for Gotify Android notification channels.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Precedence: CLI > environment > JSON config > built-in defaults.

        Common examples:
          gotify-androidctl setup --output ./gotify-android.json
          gotify-androidctl --gotify-url https://push.example.net provision-apps
          gotify-androidctl --app security rotate-tokens --confirm-token-rotation
          gotify-androidctl --serial R58... sounds
          gotify-androidctl --app security --app 'money_*' configure --channels normal,high
          gotify-androidctl --non-interactive --strict bootstrap --only-drifted
          gotify-androidctl audit --fail-on-drift --report ./audit.json
        """),
        parents=[common_root],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", parents=[common_sub], help="Full Gotify app provisioning → Android settings → sounds → channels → audit")
    p.add_argument("--skip-app-provision", action="store_true", help="Skip Gotify Application discovery/creation/token capture")
    p.add_argument("--rotate-missing-tokens", action="store_true", help="Rotate existing app tokens only when no local token is recoverable")
    p.add_argument("--confirm-token-rotation", action="store_true", help="Explicitly authorize requested token rotation")
    p.add_argument("--require-token-files", action="store_true", help="Fail if every existing app does not have a locally managed token")
    p.add_argument("--reconcile-app-metadata", action="store_true", help="Reconcile Gotify name/description/defaultPriority")
    p.add_argument("--skip-icons", action="store_true", help="Skip Gotify Application icon synchronization")
    p.add_argument("--force-icon-upload", action="store_true", help="Re-upload configured icons even when local SHA-256 state matches")
    p.add_argument("--require-icons", action="store_true", help="Fail when a configured Application icon is missing")
    p.add_argument("--export-token-bundle", help="Optional aggregate raw-token export path (0600; dedicated per-app files remain canonical)")
    p.add_argument("--token-bundle-format", choices=["env", "json"], default="env", help="Aggregate token export format")
    p.add_argument("--skip-separate", action="store_true", help="Do not ensure Gotify per-app channel setting")
    p.add_argument("--skip-sounds", action="store_true", help="Skip sound deployment")
    p.add_argument("--skip-seed", action="store_true", help="Do not seed/materialize missing app channels")
    p.add_argument("--skip-configure", action="store_true", help="Skip Android settings UI configuration")
    p.add_argument("--skip-audit", action="store_true", help="Skip final audit")
    p.add_argument("--channels", help="Channel classes: min,low,normal,high (comma-separated)")
    p.add_argument("--only-drifted", action="store_true", help="Configure only channels detected as drifted")
    p.add_argument("--fail-on-drift", action="store_true", help="Return exit 30 if final audit still has drift")

    sub.add_parser("preflight", parents=[common_sub], help="Validate tools, device, Gotify package, permissions, server if URL is configured")
    sub.add_parser("doctor", parents=[common_sub], help="Run diagnostic checks and print detected capabilities")
    sub.add_parser("devices", parents=[common_sub], help="List ADB devices with metadata")

    p = sub.add_parser(
        "provision-apps", parents=[common_sub],
        help="Discover/create Gotify Applications, capture tokens to dedicated 0600 files, write provisioning manifest"
    )
    p.add_argument("--no-create-missing", action="store_true", help="Discover only; do not create missing Gotify Applications")
    p.add_argument("--rotate-missing-tokens", action="store_true", help="Rotate existing tokens only when no local token is recoverable")
    p.add_argument("--confirm-token-rotation", action="store_true", help="Explicitly authorize requested token rotation")
    p.add_argument("--require-token-files", action="store_true", help="Fail if an existing app has no local managed token")
    p.add_argument("--reconcile-metadata", action="store_true", help="Reconcile name/description/defaultPriority on existing apps")
    p.add_argument("--skip-icons", action="store_true", help="Skip Gotify Application icon synchronization")
    p.add_argument("--force-icon-upload", action="store_true", help="Re-upload icons even when local SHA-256 state matches")
    p.add_argument("--require-icons", action="store_true", help="Fail when a configured Application icon is missing")
    p.add_argument("--no-import-external-tokens", action="store_true", help="Do not import token_env/token_file values into the managed per-category store")
    p.add_argument("--export-token-bundle", help="Optional aggregate raw-token export path (0600)")
    p.add_argument("--token-bundle-format", choices=["env", "json"], default="env")
    p.add_argument("--show-secrets", action="store_true", help="Explicitly print raw application tokens to stdout")

    p = sub.add_parser(
        "rotate-tokens", parents=[common_sub],
        help="Rotate selected Gotify Application tokens via PUT /application/{id}/security"
    )
    p.add_argument("--confirm-token-rotation", action="store_true", help="Explicitly authorize token invalidation/rotation")
    p.add_argument("--reason", default="", help="Audit/log reason for rotation")
    p.add_argument("--export-token-bundle", help="Optional aggregate raw-token export path (0600)")
    p.add_argument("--token-bundle-format", choices=["env", "json"], default="env")
    p.add_argument("--show-secrets", action="store_true", help="Explicitly print raw application tokens to stdout")

    p = sub.add_parser("pair", parents=[common_sub], help="Pair wireless ADB device")
    p.add_argument("target", help="Pairing host:port")
    p.add_argument("--code", help="Pairing code (prefer --code-env for shell-history hygiene)")
    p.add_argument("--code-env", help="Environment variable containing pairing code")

    p = sub.add_parser("connect", parents=[common_sub], help="Connect wireless ADB device")
    p.add_argument("target", help="Wireless ADB host:port")

    p = sub.add_parser("disconnect", parents=[common_sub], help="Disconnect wireless ADB device or all TCP devices")
    p.add_argument("target", nargs="?", help="Optional host:port")

    p = sub.add_parser("sounds", parents=[common_sub], help="Resolve/convert, deploy and verify custom notification sounds")

    p = sub.add_parser("icons", parents=[common_sub], help="Synchronize configured PNG/JPEG icons to Gotify Applications")
    p.add_argument("--force-icon-upload", action="store_true", help="Re-upload icons even when local SHA-256 state matches")
    p.add_argument("--require-icons", action="store_true", help="Fail when a configured Application icon is missing")

    p = sub.add_parser("resolve", parents=[common_sub], help="Resolve/cache Gotify application IDs")
    p.add_argument("--no-seed", action="store_true", help="Do not use a seed push as last-resort resolution")

    p = sub.add_parser("seed", parents=[common_sub], help="Send provisioning messages")
    p.add_argument("--priorities", help="Explicit comma-separated priorities, overriding seed defaults")

    p = sub.add_parser("channels", parents=[common_sub], help="Show expected channel IDs and matching Android channel state")
    p.add_argument("--raw", action="store_true", help="Also print raw matching NotificationChannel lines")

    p = sub.add_parser("configure", parents=[common_sub], help="Configure per-app Android notification channels via safe UI automation/guided mode")
    p.add_argument("--channels", help="Channel classes: min,low,normal,high (comma-separated)")
    p.add_argument("--only-drifted", action="store_true", help="Configure only channels detected as drifted")

    p = sub.add_parser("audit", parents=[common_sub], help="Audit channel existence, sound, vibration and importance")
    p.add_argument("--fail-on-drift", action="store_true", help="Return exit 30 when drift exists")
    p.add_argument("--output", help="Write audit JSON to a separate file")

    p = sub.add_parser("settings", parents=[common_sub], help="Open Android notification settings")
    p.add_argument("--app-key", help="Open a specific configured Gotify application channel")
    p.add_argument("--channel", choices=["min", "low", "normal", "high"], help="Channel class with --app-key")

    p = sub.add_parser("snapshot", parents=[common_sub], help="Create diagnostic tar/tar.gz snapshot (redacted by default)")
    p.add_argument("--output", required=True, help="Output .tar or .tar.gz path")

    p = sub.add_parser("init-config", parents=[common_sub], help="Write a fully documented starter JSON config")
    p.add_argument("--output", default="./gotify-android.json", help="Destination config path")
    p.add_argument("--force", action="store_true", help="Overwrite existing config")

    p = sub.add_parser("setup", parents=[common_sub], help="Create a safe config with an interactive setup wizard")
    p.add_argument("--output", default="./gotify-android.json", help="Destination config path")
    p.add_argument("--force", action="store_true", help="Overwrite existing config")

    sub.add_parser("show-config", parents=[common_sub], help="Print effective non-secret configuration and policy")
    sub.add_parser("policy", parents=[common_sub], help="Print conceptual Gotify/Android channel policy")
    return parser


def sample_config() -> Dict[str, Any]:
    apps: List[Dict[str, Any]] = []
    for row in DEFAULT_APPS:
        sound = row["sound"]
        ch = default_channel_policy(sound)
        apps.append({
            "id": row["id"],
            "name": row["name"],
            "enabled": True,
            "description": row.get("description", ""),
            "default_priority": row.get("default_priority", 0),
            "token_env": row["token_env"],
            "icon": row.get("icon"),
            "sound": sound,
            "channels": {
                cls: {
                    "sound": pol.sound,
                    "vibration": pol.vibration,
                    "importance": pol.importance,
                }
                for cls, pol in ch.items()
            },
        })
    return {
        "version": CONFIG_VERSION,
        "gotify": {
            "url": "https://gotify.example.com",
            "client_token_env": "GOTIFY_CLIENT_TOKEN",
            "username": None,
            "password_env": "GOTIFY_PASSWORD",
            "password_file": None,
            "secret_dir": "~/.config/gotify-androidctl/secrets",
            "provisioning_output": None
        },
        "android": {
            "package": DEFAULT_PACKAGE,
            "user": 0,
            "remote_sounds_dir": DEFAULT_REMOTE_SOUNDS_DIR,
            "wake_device": True,
            "keep_awake": True,
            "grant_notifications": True,
            "battery_whitelist": False,
            "media_scan": "broadcast",
            "verify_hash": True
        },
        "assets": {
            "root": "..",
            "icons_dir": "icons",
            "sounds_dir": "sounds",
            "audio": {
                "format": "ogg",
                "source_preference": ["wav", "ogg", "mp3"],
                "cache_dir": "~/.cache/gotify-androidctl/audio",
                "ffmpeg": "ffmpeg",
                "vorbis_quality": 5.0
            }
        },
        "state_file": "~/.config/gotify-androidctl/state.json",
        "http": {
            "curl": "curl",
            "insecure": False,
            "connect_timeout": 5,
            "request_timeout": 20,
            "retries": 2,
            "retry_delay": 1,
            "headers": [],
            "header_envs": []
        },
        "ui": {
            "mode": "auto",
            "wait": 1.0,
            "retries": 2,
            "scrolls": 8,
            "locale": "auto",
            "oem_profile": "auto",
            "screenshot_on_failure": True,
            "dump_ui_on_failure": True,
            "guided_timeout": 0,
            "ensure_separate_channels": "auto"
        },
        "policy": {
            "seed_priority": 2,
            "seed_all_priorities": False,
            "seed_wait": 1.0,
            "channel_wait": 12.0,
            "seed_title_prefix": "[BOOTSTRAP]",
            "seed_message": "Temporary provisioning message used to materialize/verify Gotify Android notification channels.",
            "cleanup_seeds": False
        },
        "apps": apps,
    }


def validate_setup_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError("Gotify URL must be an absolute http(s) URL, for example https://gotify.example.com.", ExitCode.CONFIG)
    return value


def prompt_setup_value(label: str, default: Optional[str] = None, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("A value is required.", file=sys.stderr)


def write_config(target: pathlib.Path, config: Mapping[str, Any], force: bool) -> None:
    if target.exists() and not force:
        raise ToolError(f"Refusing to overwrite {target}; use --force.", ExitCode.CONFIG)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def setup_config(target: pathlib.Path, args: argparse.Namespace, interactive: bool) -> None:
    cfg = sample_config()
    gotify = cfg["gotify"]
    url = getattr(args, "gotify_url", None)
    username = getattr(args, "gotify_username", None)
    password_env = getattr(args, "gotify_password_env", None)
    client_token_env = getattr(args, "client_token_env", None)

    if interactive:
        print("Gotify Android setup — no secrets are written to the JSON file.")
        url = url or prompt_setup_value("Gotify server URL", required=True)
        username = username or prompt_setup_value("Gotify management username", default="admin")
        password_env = password_env or prompt_setup_value("Management password environment variable", default="GOTIFY_PASSWORD")
        client_token_env = client_token_env or prompt_setup_value("Client-token environment variable", default="GOTIFY_CLIENT_TOKEN")
    elif not url:
        raise ToolError("setup --non-interactive requires --gotify-url; secrets must be supplied through environment-variable names.", ExitCode.CONFIG)

    gotify["url"] = validate_setup_url(str(url))
    gotify["username"] = username or gotify["username"]
    gotify["password_env"] = password_env or gotify["password_env"]
    gotify["client_token_env"] = client_token_env or gotify["client_token_env"]
    write_config(target, cfg, bool(getattr(args, "force", False)))


def missing_config_guidance(target: pathlib.Path) -> str:
    return textwrap.dedent(f"""\
        Config file not found: {target}

        Create it safely (no secrets are stored in JSON):
          {TOOL_NAME} setup --output {target}

        For automation:
          {TOOL_NAME} setup --non-interactive --gotify-url https://gotify.example.com --output {target}
        """).rstrip()


def print_policy() -> None:
    print(textwrap.dedent("""
    Gotify / Android channel contract
    ================================
    Gotify priority    Android channel class    Default desired behavior
    <= 0               min                      silent, vibration off
    1-3                low                      silent, vibration off
    4-7                normal                   category sound, vibration off
    >= 8               high                     category sound, vibration on

    DOMAIN        NORMAL SOUND        HIGH SOUND + VIBRATION
    PAGER         pager.ogg           pager.ogg
    SECURITY      security.ogg        security.ogg
    INFRA         infra.ogg           infra.ogg
    PLATFORM      platform.ogg        platform.ogg
    AUTOMATION    automation.ogg      automation.ogg
    DEV           dev.ogg             dev.ogg
    DIGEST        silent              silent
    MONEY · IN    cash-in.ogg         cash-in.ogg
    MONEY · OUT   cash-out.ogg        cash-out.ogg
    TRADING       trading.ogg         trading.ogg

    Principle: sound identifies domain; Gotify priority/channel class identifies urgency.
    """).strip())


def effective_config_view(settings: RuntimeSettings, apps: Sequence[AppSpec]) -> Dict[str, Any]:
    return {
        "config_path": settings.config_path,
        "gotify_url": settings.gotify_url,
        "package": settings.package,
        "assets_root": settings.assets_root,
        "icons_dir": settings.icons_dir,
        "sounds_dir": settings.sounds_dir,
        "remote_sounds_dir": settings.remote_sounds_dir,
        "audio": {
            "format": settings.audio_format,
            "source_preference": settings.audio_source_preference,
            "cache_dir": settings.audio_cache_dir,
            "ffmpeg": settings.ffmpeg,
            "vorbis_quality": settings.audio_vorbis_quality,
        },
        "serial": settings.serial,
        "transport_id": settings.transport_id,
        "android_user": settings.android_user,
        "state_file": settings.state_file,
        "secret_dir": settings.secret_dir,
        "provisioning_output": settings.provisioning_output,
        "adb": settings.adb,
        "curl": settings.curl,
        "ui_mode": settings.ui_mode,
        "oem_profile": settings.oem_profile,
        "strict": settings.strict,
        "non_interactive": settings.non_interactive,
        "dry_run": settings.dry_run,
        "http": {
            "insecure": settings.insecure,
            "cacert": settings.cacert,
            "client_cert": settings.client_cert,
            "client_key": settings.client_key,
            "client_p12": settings.client_p12,
            "proxy": settings.proxy,
            "no_proxy": settings.no_proxy,
            "http_user": settings.http_user,
            "http_password_env": settings.http_password_env,
            "http_bearer_env": settings.http_bearer_env,
            "gotify_username": settings.gotify_username,
            "gotify_password_env": settings.gotify_password_env,
            "gotify_password_file": settings.gotify_password_file,
            "headers": settings.headers,
            "header_envs": settings.header_envs,
        },
        "apps": [
            {
                "id": a.key,
                "name": a.name,
                "enabled": a.enabled,
                "app_id": a.app_id,
                "token_env": a.token_env,
                "token_file": a.token_file,
                "description": a.description,
                "icon": a.icon,
                "default_priority": a.default_priority,
                "external_token_available": bool(a.token()),
                "channels": {k: dataclasses.asdict(v) for k, v in a.channels.items()},
            }
            for a in apps
        ],
    }


def load_everything(args: argparse.Namespace, argv: Sequence[str]) -> Tuple[RuntimeSettings, List[AppSpec], Dict[str, Any]]:
    path_str, no_config = config_path_from_argv(argv)
    cfg: Dict[str, Any] = {}
    apps = built_in_apps()
    if path_str and not no_config:
        path = pathlib.Path(os.path.expanduser(path_str))
        if not path.is_file():
            raise ToolError(f"Config file not found: {path}", ExitCode.CONFIG)
        cfg, apps = load_config_file(path)
    settings = runtime_settings(args, cfg, path_str, no_config)
    return settings, apps, cfg


def validate_args(args: argparse.Namespace, settings: RuntimeSettings, apps: Sequence[AppSpec]) -> None:
    if settings.transport_id is not None and settings.serial:
        raise ToolError("Use either --transport-id or --serial, not both.", ExitCode.USAGE)
    if settings.client_cert and settings.client_p12:
        raise ToolError("Use either PEM --client-cert/--client-key or --client-p12, not both.", ExitCode.USAGE)
    if settings.client_key and not settings.client_cert:
        raise ToolError("--client-key requires --client-cert.", ExitCode.USAGE)
    if settings.ui_retries < 1:
        raise ToolError("--ui-retries must be >= 1.", ExitCode.USAGE)
    if settings.retries < 0:
        raise ToolError("--retries must be >= 0.", ExitCode.USAGE)
    if settings.audio_format not in SUPPORTED_AUDIO_FORMATS:
        raise ToolError(f"Unsupported --audio-format {settings.audio_format!r}; choose ogg, wav or mp3.", ExitCode.USAGE)
    invalid_audio = [x for x in settings.audio_source_preference if x not in SUPPORTED_AUDIO_FORMATS]
    if invalid_audio:
        raise ToolError(
            f"Unsupported audio source extension(s): {', '.join(invalid_audio)}; supported: ogg,wav,mp3.",
            ExitCode.USAGE,
        )
    if not settings.audio_source_preference:
        raise ToolError("Audio source preference cannot be empty.", ExitCode.USAGE)
    if not (0.0 <= settings.audio_vorbis_quality <= 10.0):
        raise ToolError("--audio-vorbis-quality must be between 0 and 10.", ExitCode.USAGE)
    if settings.seed_priority < -100 or settings.seed_priority > 100:
        raise ToolError("--seed-priority is outside a reasonable range (-100..100).", ExitCode.USAGE)
    if not apps and args.command not in ("devices", "pair", "connect", "disconnect", "init-config", "setup", "policy"):
        raise ToolError("No applications selected after --app/--exclude-app filtering.", ExitCode.CONFIG)


def command_devices(controller: Controller) -> None:
    controller.require_tools()
    controller.adb.start_server()
    rows = controller.adb.devices()
    print(json.dumps(rows, indent=2, ensure_ascii=False))


def command_pair(controller: Controller) -> None:
    controller.require_tools()
    target = controller.args.target
    code = controller.args.code
    if controller.args.code_env:
        code = os.environ.get(controller.args.code_env, "")
    cmd = ["pair", target]
    if code:
        cmd.append(code)
    elif controller.settings.non_interactive:
        raise ToolError("pair requires --code/--code-env in non-interactive mode.", ExitCode.USAGE)
    cp = controller.adb.run(cmd, select_device=False, check=False, capture=False, redact=[code] if code else [], mutating=True)
    if cp.returncode != 0:
        raise ToolError(f"adb pair failed for {target}", ExitCode.DEVICE)


def command_connect(controller: Controller) -> None:
    controller.require_tools()
    cp = controller.adb.run(["connect", controller.args.target], select_device=False, check=False, mutating=True)
    out = (cp.stdout or "") + (cp.stderr or "")
    print(out.strip())
    if cp.returncode != 0 or "failed" in out.lower():
        raise ToolError(f"adb connect failed for {controller.args.target}", ExitCode.DEVICE)


def command_disconnect(controller: Controller) -> None:
    controller.require_tools()
    args = ["disconnect"] + ([controller.args.target] if controller.args.target else [])
    cp = controller.adb.run(args, select_device=False, check=False, mutating=True)
    print(((cp.stdout or "") + (cp.stderr or "")).strip())
    if cp.returncode != 0:
        raise ToolError("adb disconnect failed", ExitCode.DEVICE)


def command_channels(controller: Controller) -> None:
    controller.preflight(require_server=False, require_channels=True)
    controller.resolve_app_ids(allow_seed=False)
    dump = controller.adb.dumpsys_notification(controller.settings.sensitive_dump)
    records = controller.parse_notification_channels(dump)
    for app in controller.apps:
        print(f"\n{app.name}  app_id={app.app_id if app.app_id is not None else '?'}")
        for cls in ("min", "low", "normal", "high"):
            cid = controller.channel_id(app, cls)
            recs = records.get(cid or "", []) if cid else []
            state = "present" if recs else "MISSING"
            print(f"  {cls:6}  {cid or '<unresolved>':55}  {state}")
            if controller.args.raw and recs:
                for rec in recs:
                    print("           " + rec["raw"])


def command_settings(controller: Controller) -> None:
    controller.preflight(require_server=False, require_channels=False)
    if controller.args.app_key:
        matches = [a for a in controller.apps if a.key == controller.args.app_key or a.name == controller.args.app_key]
        if not matches:
            raise ToolError(f"Unknown configured app: {controller.args.app_key}", ExitCode.USAGE)
        controller.resolve_app_ids(allow_seed=False)
        app = matches[0]
        if not controller.args.channel:
            raise ToolError("--app-key requires --channel min|low|normal|high.", ExitCode.USAGE)
        cid = controller.channel_id(app, controller.args.channel)
        if not cid:
            raise ToolError(f"Application ID unresolved for {app.name}; run resolve first.", ExitCode.PROVISION)
        if not controller.adb.open_channel_settings(controller.settings.package, cid):
            raise ToolError("Could not open channel settings.", ExitCode.UI)
    else:
        if not controller.adb.open_app_notification_settings(controller.settings.package):
            raise ToolError("Could not open app notification settings.", ExitCode.UI)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-config":
        target = pathlib.Path(os.path.expanduser(args.output))
        write_config(target, sample_config(), args.force)
        print(str(target))
        return ExitCode.OK
    if args.command == "setup":
        target = pathlib.Path(os.path.expanduser(args.output))
        setup_config(target, args, interactive=not args.non_interactive and sys.stdin.isatty())
        print(f"Configuration written to {target}")
        print(f"Review it, then run: {TOOL_NAME} -c {target} --dry-run bootstrap")
        return ExitCode.OK
    if args.command == "policy":
        print_policy()
        return ExitCode.OK

    path_str, no_config = config_path_from_argv(argv)
    if path_str and not no_config:
        target = pathlib.Path(os.path.expanduser(path_str))
        if not target.is_file():
            if not args.non_interactive and sys.stdin.isatty():
                print(f"Configuration {target} does not exist; starting guided setup.")
                setup_config(target, args, interactive=True)
                print(f"Configuration written to {target}")
                print("Review it, then rerun the requested command. No provisioning was performed.")
                return ExitCode.OK
            print(missing_config_guidance(target), file=sys.stderr)
            return ExitCode.CONFIG

    controller: Optional[Controller] = None
    exit_code = ExitCode.OK
    try:
        settings, apps, _cfg = load_everything(args, argv)
        validate_args(args, settings, apps)
        controller = Controller(args, settings, apps)

        if args.command == "show-config":
            print(json.dumps(effective_config_view(settings, controller.apps), indent=2, ensure_ascii=False))
        elif args.command == "devices":
            command_devices(controller)
        elif args.command == "provision-apps":
            controller.provision_applications(
                create_missing=not args.no_create_missing,
                rotate_missing_tokens=args.rotate_missing_tokens,
                require_token_files=args.require_token_files,
                reconcile_metadata=args.reconcile_metadata,
                import_external_tokens=not args.no_import_external_tokens,
                export_token_bundle=args.export_token_bundle,
                token_bundle_format=args.token_bundle_format,
                show_secrets=args.show_secrets,
                sync_icons=not args.skip_icons,
                force_icon_upload=args.force_icon_upload,
                require_icons=args.require_icons,
            )
        elif args.command == "rotate-tokens":
            controller.rotate_tokens(
                reason=args.reason,
                export_token_bundle=args.export_token_bundle,
                token_bundle_format=args.token_bundle_format,
                show_secrets=args.show_secrets,
            )
        elif args.command == "pair":
            command_pair(controller)
        elif args.command == "connect":
            command_connect(controller)
        elif args.command == "disconnect":
            command_disconnect(controller)
        elif args.command == "preflight":
            controller.preflight(require_server=bool(settings.gotify_url), require_channels=False)
        elif args.command == "doctor":
            controller.doctor()
        elif args.command == "sounds":
            controller.preflight(require_server=False, require_channels=False)
            controller.install_sounds()
        elif args.command == "icons":
            controller.server_preflight()
            server_apps = controller.list_server_applications()
            controller.sync_application_icons(
                server_apps, force=args.force_icon_upload, require_icons=args.require_icons
            )
        elif args.command == "resolve":
            controller.preflight(require_server=True, require_channels=False)
            controller.resolve_app_ids(allow_seed=not args.no_seed)
            print(json.dumps({a.key: a.app_id for a in controller.apps}, indent=2, ensure_ascii=False))
        elif args.command == "seed":
            controller.preflight(require_server=True, require_channels=False)
            priorities = [int(x) for x in parse_csv_list(args.priorities)] if args.priorities else None
            controller.seed(priorities)
        elif args.command == "channels":
            command_channels(controller)
        elif args.command == "configure":
            controller.preflight(require_server=bool(settings.gotify_url), require_channels=True)
            # Resolve IDs before inspecting Gotify's per-application Android
            # channels. Without this, an otherwise active setup appears absent
            # and the tool can unnecessarily enter/toggle the Gotify UI.
            controller.resolve_app_ids(allow_seed=False)
            if not controller.ensure_separate_app_channels():
                raise ToolError(
                    "Gotify per-application notification channels could not be verified/enabled; refusing channel configuration.",
                    ExitCode.UI,
                )
            classes = parse_csv_list(args.channels) or ["min", "low", "normal", "high"]
            unknown = [x for x in classes if x not in CHANNEL_SUFFIXES]
            if unknown:
                raise ToolError(f"Unknown channel class(es): {', '.join(unknown)}", ExitCode.USAGE)
            controller.configure_channels(classes=classes, only_drifted=args.only_drifted)
        elif args.command == "audit":
            controller.preflight(require_server=False, require_channels=True)
            entries = controller.audit_channels(fail_on_drift=args.fail_on_drift)
            if args.output:
                target = pathlib.Path(os.path.expanduser(args.output))
                target.write_text(json.dumps([dataclasses.asdict(x) for x in entries], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                controller.console.info(f"Audit JSON written to {target}", component="audit")
        elif args.command == "settings":
            command_settings(controller)
        elif args.command == "snapshot":
            controller.snapshot(args.output)
        elif args.command == "bootstrap":
            controller.bootstrap()
        else:
            parser.error(f"Unsupported command: {args.command}")

    except ToolError as exc:
        exit_code = exc.code
        if controller:
            controller.console.error(str(exc), component="fatal")
            controller.report.add("error", "fatal", "", str(exc))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        exit_code = 130
        if controller:
            controller.console.error("Interrupted by user.", component="fatal")
        else:
            print("Interrupted.", file=sys.stderr)
    except Exception as exc:
        exit_code = ExitCode.PARTIAL
        if controller:
            controller.console.error(f"Unexpected error: {type(exc).__name__}: {exc}", component="fatal")
            if controller.settings.log_level == "debug":
                import traceback
                traceback.print_exc()
        else:
            print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if controller:
            controller.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
