# Changelog

## 4.1.3-local — 2026-08-20

### Cross-OEM safety and drift repair

- Disabled Settings controls are now rejected before tap; Silent selection falls back to the active Sound picker rather than treating a disabled top-level choice as success.

- Fixed Pixel switch discovery: a label can be a sibling of the actual Switch, so the automation now searches the verified preference-row subtree rather than only the label subtree.

- Settings discovery now prefers the semantic checkable Switch child over a clickable parent row when the platform exposes state only on that child; this fixes the current Pixel vibration-control hierarchy without fixed coordinates.

- Automatic channel edits now refuse to start when Android positively reports a visible lock screen; the operator must unlock the device or use guided/manual Settings.

- The Android UI path is now explicitly fail-closed across OEMs: Pixel/AOSP, Samsung, Xiaomi/Redmi/POCO, OnePlus, Oppo/Realme and Motorola are detected for diagnostics, while unrecognised channel titles or controls receive no tap and require guided/manual completion.
- Added drift-only repair: when an audit proves only vibration drift, the tool preserves the already-verified custom sound and changes only vibration.
- Added an entrypoint consistency invariant to the self-test so the executable and Python source cannot silently diverge again.
- Android Settings is force-stopped before each channel deep link to avoid stale Settings task/page reuse seen on Pixel.
- The final authority remains the post-change `dumpsys notification` audit; ADB/UI success alone is insufficient.


## 4.1.1-local — 2026-08-20

### Android UI safety

- Added a fail-closed channel-page preflight: after Android Settings opens, the
  UI dump must contain the expected priority-channel title before the tool can
  tap any control.
- Added an immediate `dumpsys notification` post-condition audit for every
  automatically configured channel. An ADB exit code alone can no longer mark
  a channel configuration successful.
- A failed preflight or post-condition captures diagnostics best-effort and
  falls back to guided/manual handling; it does not retry blind coordinates.
- Added regression coverage for title preflight refusal and post-condition
  drift rejection.

## 4.1.0 — 2026-08-20

### Application asset management

- Added first-class `icon` mapping to every built-in Gotify category.
- Added `icons` command.
- `provision-apps` and `bootstrap` now synchronize Gotify Application images by default.
- Uses official `POST /application/{id}/image` multipart API.
- Added SHA-256 image state for idempotent uploads and server-image repair detection.
- Added `--icons-dir`, `--skip-icons`, `--require-icons`, and `--force-icon-upload`.
- Provisioning manifest now includes redacted image asset metadata and digest.

### Relocatable repository assets

- Added `assets.root` configuration, resolved relative to the JSON config file.
- Added automatic asset-root discovery for the sibling `gotify-androidctl/`, `icons/`, `sounds/` repository layout.
- Added `--assets-root` / `GOTIFY_ASSETS_ROOT` and `GOTIFY_ICONS_DIR` overrides.
- Kept backward compatibility with legacy top-level `sounds_dir`.

### Professional audio pipeline

- WAV is now the recommended master; OGG/Vorbis is the default Android deployment format.
- Added source resolution across WAV/OGG/MP3 with configurable preference.
- Added content-addressed ffmpeg transcode cache; sources are never overwritten.
- Added `--audio-format {ogg,wav,mp3}`.
- Added `--audio-source-preference`, `--audio-cache-dir`, `--ffmpeg`, and `--audio-vorbis-quality`.
- Canonical channel sound filenames automatically follow the selected deployment format.
- ffmpeg is only required when a real conversion is necessary.

### Diagnostics / quality

- `doctor` now reports resolved asset paths, missing icons/sounds, audio profile and ffmpeg availability.
- Fixed duplicate `--no-wake-device` parser registration.
- Added filename/path-traversal protection for per-category sound and icon asset references.
- Added multipart-upload support to the hardened curl transport.
- Added integration coverage for config-relative paths, Application image upload and WAV→OGG conversion.

## 4.0.0

- Added Gotify Application create/discover lifecycle.
- Added Gotify 3 one-time token capture and dedicated `0600` token files.
- Added redacted Application Provisioning manifest.
- Added explicit `/application/{id}/security` token rotation with elevation handling.
