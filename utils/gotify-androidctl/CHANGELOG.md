# Changelog

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
