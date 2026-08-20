# gotify-androidctl

MacOS/Linux → Gotify Server → Android provisioning, credential lifecycle, Application-image synchronization, notification-sound deployment, channel configuration and drift audit.

## Repository layout supported out of the box

This utility is designed for the following layout:

```text
utils/
├── gotify-androidctl/
│   ├── gotify-androidctl
│   ├── gotify-androidctl.py
│   ├── gotify-android.json
│   ├── README.md
│   ├── SECURITY.md
│   └── tests/
├── icons/
│   ├── 00_index.png
│   ├── automation.png
│   ├── dev.png
│   ├── digest.png
│   ├── infra.png
│   ├── money_in.png
│   ├── money_out.png
│   ├── pager.png
│   ├── platform.png
│   ├── security.png
│   └── trading.png
└── sounds/
    ├── automation.mp3 / automation.wav
    ├── cash-in.mp3 / cash-in.wav
    ├── cash-out.mp3 / cash-out.wav
    ├── dev.mp3 / dev.wav
    ├── digest.mp3 / digest.wav
    ├── digest2.mp3 / digest2.wav
    ├── infra.mp3 / infra.wav
    ├── pager.mp3 / pager.wav
    ├── pager2.mp3 / pager2.wav
    ├── platform.mp3 / platform.wav
    ├── security.mp3 / security.wav
    └── trading.mp3 / trading.wav
```

The recommended config lives in `utils/gotify-androidctl/` and uses:

```json
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
}
```

`assets.root` is resolved relative to the JSON configuration file, **not** the process working directory. The same config therefore works when the CLI is launched from the repository root, `utils/`, a cron job, CI runner, or another directory.

CLI path overrides are CWD-relative (or absolute) and take precedence:

```bash
./utils/gotify-androidctl/gotify-androidctl \
  --assets-root ./utils \
  --icons-dir ./utils/icons \
  --sounds-dir ./utils/sounds \
  show-config
```

Environment overrides are also supported:

```bash
export GOTIFY_ASSETS_ROOT="./utils"
export GOTIFY_ICONS_DIR="$GOTIFY_ASSETS_ROOT/icons"
export SOUNDS_DIR="$GOTIFY_ASSETS_ROOT/sounds"
```

## Canonical category asset mapping

| Category    | Gotify Application image | Sound master                 | Android deployment |
| ----------- | ------------------------ | ---------------------------- | ------------------ |
| PAGER       | `pager.png`              | `pager.wav`                  | `pager.ogg`        |
| SECURITY    | `security.png`           | `security.wav`               | `security.ogg`     |
| INFRA       | `infra.png`              | `infra.wav`                  | `infra.ogg`        |
| PLATFORM    | `platform.png`           | `platform.wav`               | `platform.ogg`     |
| AUTOMATION  | `automation.png`         | `automation.wav`             | `automation.ogg`   |
| DEV         | `dev.png`                | `dev.wav`                    | `dev.ogg`          |
| DIGEST      | `digest.png`             | not used by default (silent) | silent             |
| MONEY · IN  | `money_in.png`           | `cash-in.wav`                | `cash-in.ogg`      |
| MONEY · OUT | `money_out.png`          | `cash-out.wav`               | `cash-out.ogg`     |
| TRADING     | `trading.png`            | `trading.wav`                | `trading.ogg`      |

`00_index.png` is intentionally ignored. `pager2.*` and `digest2.*` are alternatives and are ignored until selected in config, e.g. `"sound": "pager2.ogg"`.

## Why WAV source → OGG/Vorbis deployment

The default asset pipeline treats WAV as the lossless master and deploys OGG/Vorbis to Android:

```text
sounds/security.wav
        │
        ├─ SHA-256 source identity
        │
        ├─ ffmpeg Vorbis encoder q=5
        ▼
~/.cache/gotify-androidctl/audio/security-<content-hash>.ogg
        │
        └─ adb push
           ▼
/sdcard/Notifications/Gotify/security.ogg
```

Benefits:

- the original WAV master is never modified;
- OGG/Vorbis is natively supported by Android and is substantially smaller than uncompressed WAV;
- cache keys include source SHA-256 + encoding profile, avoiding unnecessary re-encoding;
- Android receives stable canonical filenames, which keeps channel audit/UI automation deterministic;
- if a native OGG source is preferred, reorder `source_preference`;
- MP3 and WAV deployment remain available through `--audio-format mp3|wav`.

Install ffmpeg on macOS:

```bash
brew install ffmpeg
```

Verify that the selected `ffmpeg` has a Vorbis encoder before running the full self-test or deploying OGG:

```bash
ffmpeg -hide_banner -encoders | rg 'libvorbis| vorbis'
```

`gotify-androidctl` prefers `libvorbis` and falls back to FFmpeg's native `vorbis` encoder when that is the available implementation. The fallback is enabled with FFmpeg's experimental flag and safely converts to stereo, as required by that encoder. If neither encoder appears, install or rebuild FFmpeg with Vorbis support, or use `--audio-format mp3` or `--audio-format wav`.

The full local self-test includes WAV-to-OGG conversion. A local FFmpeg build that lacks `libvorbis` no longer stops that test when its native `vorbis` encoder is present; the utility selects the compatible fallback automatically.

The utility has no runtime Python dependencies beyond the standard library. For development tests, use the repository virtual environment and extras; a separate `requirements.txt` or `pip-compile` workflow is not required:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If the chosen source already has the deployment extension, ffmpeg is not required for that asset.

Examples:

```bash
# Recommended default: WAV master -> OGG/Vorbis
./gotify-androidctl --audio-format ogg sounds

# Keep WAV as the Android notification asset
./gotify-androidctl --audio-format wav sounds

# Generate/deploy MP3
./gotify-androidctl --audio-format mp3 sounds

# Prefer pre-existing OGG before WAV
./gotify-androidctl --audio-source-preference ogg,wav,mp3 sounds

# Change Vorbis quality
./gotify-androidctl --audio-vorbis-quality 6 sounds
```

## Gotify Application images

Every configured Application can contain an `icon` field:

```json
{
  "id": "security",
  "name": "🛡 SECURITY",
  "icon": "security.png"
}
```

During `provision-apps` and `bootstrap`, the tool synchronizes it through Gotify's official multipart endpoint:

```text
POST /application/{id}/image
form field: file
```

Uploads are idempotent using a local SHA-256 asset record. The Gotify Application model exposes the server-side `image` field, so an externally removed image causes a repair upload on the next run.

Commands:

```bash
# Sync only images
./gotify-androidctl -c gotify-android.json icons

# Require all configured images to exist
./gotify-androidctl -c gotify-android.json icons --require-icons

# Explicitly re-upload all selected icons
./gotify-androidctl -c gotify-android.json icons --force-icon-upload

# Only one category
./gotify-androidctl -c gotify-android.json --app security icons
```

Important: this is the **Gotify Application image**. It does not rewrite Android's protected status-bar small icon for the Gotify APK.

## Gotify Application + token lifecycle

`provision-apps`:

1. checks Gotify `/version`;
2. reads existing Applications;
3. creates missing category Applications with `POST /application`;
4. immediately captures the one-time Application token returned by Gotify 3;
5. atomically stores one `0600` token file per category;
6. optionally imports known legacy token sources;
7. synchronizes the configured Application image;
8. writes a redacted `gotify-application-provisioning.json` manifest.

Default secret layout:

```text
~/.config/gotify-androidctl/secrets/
└── <server>-<hash>/
    ├── apps/
    │   ├── pager.token
    │   ├── security.token
    │   ├── infra.token
    │   ├── platform.token
    │   ├── automation.token
    │   ├── dev.token
    │   ├── digest.token
    │   ├── money_in.token
    │   ├── money_out.token
    │   └── trading.token
    └── gotify-application-provisioning.json
```

Raw tokens are never included in normal reports or the provisioning manifest. The manifest contains token presence, masked token, SHA-256 fingerprint, Application ID and asset metadata.

## Gotify 3 token rotation

A token is never rotated implicitly. Explicit rotation uses:

```text
PUT /application/{id}/security
{"regenerateToken": true}
```

Example:

```bash
./gotify-androidctl \
  -c gotify-android.json \
  --app security \
  rotate-tokens \
  --confirm-token-rotation \
  --reason 'scheduled credential rotation'
```

If an existing Gotify 3 Application has no locally recoverable token:

```bash
./gotify-androidctl provision-apps \
  --rotate-missing-tokens \
  --confirm-token-rotation
```

Rotation requires elevated Gotify authentication. HTTP Basic management credentials are the deterministic unattended option:

```bash
export GOTIFY_PASSWORD='...'
./gotify-androidctl \
  --gotify-username admin \
  --gotify-password-env GOTIFY_PASSWORD \
  rotate-tokens --confirm-token-rotation
```

## First deployment

Requirements:

```bash
brew install android-platform-tools ffmpeg
```

Enable Developer Options / USB debugging (or Wireless debugging) on Android, then:

```bash
adb devices
```

Create the configuration:

```bash
# The setup wizard writes references to environment variables, never raw secrets.
./utils/gotify-androidctl/gotify-androidctl setup \
  --output ./utils/gotify-androidctl/gotify-android.json
```

Edit `gotify.url` and management credentials. Then inspect resolved paths before mutation:

```bash
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json show-config
```

If a command references a missing `-c` file in an interactive terminal, the same setup wizard starts automatically and exits after creating the file. In automation, create the file explicitly:

```bash
./utils/gotify-androidctl/gotify-androidctl setup \
  --non-interactive \
  --gotify-url https://gotify.example.com \
  --output ./utils/gotify-androidctl/gotify-android.json
```

Expected paths include:

```text
assets_root = .../utils
icons_dir   = .../utils/icons
sounds_dir  = .../utils/sounds
audio.format = ogg
```

Run diagnostics:

```bash
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json doctor
```

Dry-run:

```bash
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json --dry-run bootstrap \
  --report ./gotify-dry-run.json
```

Provision:

```bash
./utils/gotify-androidctl/gotify-androidctl \
  -c ./utils/gotify-androidctl/gotify-android.json bootstrap \
  --require-icons \
  --report ./gotify-provision.json
```

## Full bootstrap flow

```text
Gotify management preflight
  ↓
Discover/create Applications
  ↓
Capture/persist one-time Application tokens
  ↓
Sync PNG Application images
  ↓
Generate redacted Application Provisioning manifest
  ↓
ADB/device preflight
  ↓
Resolve WAV/OGG/MP3 source assets
  ↓
WAV → cached OGG/Vorbis when required
  ↓
Push canonical sounds + MediaStore scan
  ↓
Ensure Gotify separate Application channels
  ↓
Materialize deterministic Android channels
  ↓
Configure sound/vibration through Android Settings UI
  ↓
Audit drift
```

## Priority contract

```text
<= 0   Min      silent, vibration off
1–3    Low      silent, vibration off
4–7    Normal   category sound, vibration off
>= 8   High     category sound, vibration on
```

The sound identifies the domain; the priority/channel class identifies urgency.

## Useful commands

```bash
./gotify-androidctl --help
./gotify-androidctl bootstrap --help
./gotify-androidctl provision-apps --help
./gotify-androidctl icons --help
./gotify-androidctl sounds --help
./gotify-androidctl rotate-tokens --help
./gotify-androidctl audit --help

./gotify-androidctl -c gotify-android.json preflight
./gotify-androidctl -c gotify-android.json doctor
./gotify-androidctl -c gotify-android.json provision-apps --require-icons
./gotify-androidctl -c gotify-android.json icons
./gotify-androidctl -c gotify-android.json sounds
./gotify-androidctl -c gotify-android.json channels
./gotify-androidctl -c gotify-android.json configure --only-drifted
./gotify-androidctl -c gotify-android.json audit --fail-on-drift
```

## CI / unattended audit

```bash
./gotify-androidctl \
  -c gotify-android.json \
  --non-interactive \
  --strict \
  audit --fail-on-drift \
  --report ./gotify-audit.json
```

## Asset behavior and safety

- Per-app icon/sound values are restricted to filenames; category entries cannot escape their configured asset directories with `../` paths.
- Relative config asset paths are anchored to the config file.
- CLI/env asset paths are explicit operator overrides.
- Image uploads use the official Gotify management endpoint and multipart form upload.
- Audio conversion never overwrites source files.
- Converted assets are content-addressed by source hash + encoder profile.
- ADB uploads are SHA-256 verified by default.
- `--remove-orphan-sounds` is opt-in and confirmation protected.
- Token rotation is explicit and confirmation protected.
- One-time Gotify tokens have an emergency `0600` recovery path if durable secret persistence fails.
- Normal logs/reports never include raw Application tokens.

## Android limitation

On Android 8+ a notification channel's sound/importance behavior becomes user-controlled after creation. A normal third-party process cannot reliably rewrite those settings with a supported stock API. `gotify-androidctl` therefore uses official Settings intents plus semantic UI automation, with a guided fallback instead of private database edits or blind fixed-coordinate taps.

## Upstream references

- Gotify REST API: https://gotify.net/api-docs
- Gotify API spec: https://github.com/gotify/server/blob/master/docs/spec.json
- Android supported media formats: https://developer.android.com/media/platform/supported-formats
