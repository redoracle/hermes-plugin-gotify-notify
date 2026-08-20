# Security model — gotify-androidctl

## Credentials

- Raw Gotify Application tokens are stored in dedicated `0600` files.
- Managed secret directories are `0700`.
- Gotify 3 one-time credentials are persisted immediately after create/rotate responses.
- Raw tokens are excluded from normal reports and the provisioning manifest.
- Token values are sent in headers/config files rather than command URLs.
- Rotation is never implicit and requires explicit authorization.
- If the canonical token write fails after Gotify has generated a new token, the CLI retains a `0600` emergency recovery copy and preserves its temporary directory.

## Asset boundaries

`assets.root`, `icons_dir` and `sounds_dir` define trusted operator-controlled asset directories. Per-category `icon` and `sound` entries are filenames only; path traversal from an Application entry is rejected.

Config-relative asset paths are anchored to the configuration file, making executions independent of the shell working directory and reducing accidental substitution by same-named CWD files.

## Image upload

Application images are sent only through Gotify's documented `POST /application/{id}/image` endpoint. A SHA-256 hash is stored in the local state file to make synchronization idempotent. The provisioning manifest contains the digest and path but no secret credentials.

## Audio conversion

Source audio is never overwritten. When conversion is required, ffmpeg writes into a content-addressed cache under `~/.cache/gotify-androidctl/audio` by default. Cache identity includes source SHA-256 and the encoding profile.

OGG/Vorbis is the default Android deployment format. WAV and MP3 are supported alternatives. The tool does not execute shell-interpolated asset names; subprocesses are invoked with argument arrays.

## Android

The tool does not edit Android notification databases, root-only settings, or private framework files. It uses ADB, public Settings intents and semantic UI automation. UI automation does not use fixed tap coordinates unless it has first identified the target UI node semantically.

## Logging

Use `--sensitive-dump` only when necessary. Android notification dumps can contain notification content. Standard logs should be treated as operational metadata; secret values are redacted by the command runner.
