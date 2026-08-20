#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="${GOTIFY_ANDROIDCTL:-$ROOT/gotify-androidctl}"
MOCK="$ROOT/tests/mock_gotify_server.py"
command -v python3 >/dev/null || { echo 'python3 required' >&2; exit 10; }
command -v curl >/dev/null || { echo 'curl required' >&2; exit 10; }
cmp -s "$ROOT/gotify-androidctl" "$ROOT/gotify-androidctl.py" || { echo "entrypoints drift: synchronize gotify-androidctl from gotify-androidctl.py" >&2; exit 10; }
python3 -m py_compile "$ROOT/gotify-androidctl.py"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/gotify-androidctl-selftest.XXXXXX")"
cleanup(){ [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT INT TERM
mkdir -p "$TMP/icons" "$TMP/sounds" "$TMP/utils/gotify-androidctl" "$TMP/utils/icons" "$TMP/utils/sounds"
for f in pager security infra platform automation dev digest money_in money_out trading; do printf '\x89PNG\r\n\x1a\n%s' "$f" > "$TMP/icons/$f.png"; done
PORT="$(python3 - <<'PY'
import socket
s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()
PY
)"
SERVER_STATE="$TMP/server-state.json"
python3 "$MOCK" "$PORT" "$SERVER_STATE" >"$TMP/server.log" 2>&1 & SERVER_PID=$!; sleep .25
export GOTIFY_PASSWORD='secret'
BASE=("$CLI" --no-config --color never --state-file "$TMP/client-state.json" --icons-dir "$TMP/icons" --gotify-url "http://127.0.0.1:$PORT" --gotify-username admin --gotify-password-env GOTIFY_PASSWORD)
SECRETS_A="$TMP/secrets-a"; PROV_A="$TMP/provisioning-a.json"; BUNDLE="$TMP/tokens.env"
"${BASE[@]}" --secret-dir "$SECRETS_A" --provisioning-output "$PROV_A" provision-apps --require-icons --require-token-files --export-token-bundle "$BUNDLE" >/dev/null
python3 - "$SERVER_STATE" "$SECRETS_A" "$PROV_A" <<'PY'
import json,pathlib,stat,sys
s=json.load(open(sys.argv[1])); assert s['create_counter']==10; assert s['image_upload_counter']==10
files=list(pathlib.Path(sys.argv[2]).glob('*/apps/*.token')); assert len(files)==10; assert all(stat.S_IMODE(x.stat().st_mode)==0o600 for x in files)
m=json.load(open(sys.argv[3])); assert len(m['applications'])==10; assert all(x['assets']['icon']['sha256'] for x in m['applications']); assert all(x['assets']['icon']['serverImage'] for x in m['applications'])
raw=[x['token'] for x in s['apps']]; txt=pathlib.Path(sys.argv[3]).read_text(); assert not any(x in txt for x in raw)
print('PASS create + token capture + icon upload + manifest redaction')
PY
"${BASE[@]}" --secret-dir "$SECRETS_A" --provisioning-output "$PROV_A" provision-apps --require-icons >/dev/null
python3 - "$SERVER_STATE" <<'PY'
import json,sys
s=json.load(open(sys.argv[1])); assert s['create_counter']==10; assert s['image_upload_counter']==10
print('PASS idempotent Application + icon provisioning')
PY
SECURITY_FILE="$(echo "$SECRETS_A"/*/apps/security.token)"; BEFORE="$(cat "$SECURITY_FILE")"
"${BASE[@]}" --secret-dir "$SECRETS_A" --provisioning-output "$PROV_A" --app security rotate-tokens --confirm-token-rotation --reason selftest >/dev/null
[[ "$BEFORE" != "$(cat "$SECURITY_FILE")" ]]
python3 - "$SERVER_STATE" "$PROV_A" <<'PY'
import json,sys
s=json.load(open(sys.argv[1])); assert s['rotate_counter']==1
m=json.load(open(sys.argv[2])); assert len(m['applications'])==10
print('PASS explicit token rotation + full manifest')
PY
# Config-relative repository layout must not depend on CWD.
"$CLI" init-config --output "$TMP/utils/gotify-androidctl/gotify-android.json" --force >/dev/null
"$CLI" -c "$TMP/utils/gotify-androidctl/gotify-android.json" show-config > "$TMP/view.json"
python3 - "$TMP/view.json" "$TMP/utils" <<'PY'
import json,pathlib,sys
d=json.load(open(sys.argv[1])); root=pathlib.Path(sys.argv[2]).resolve(); assert pathlib.Path(d['assets_root'])==root; assert pathlib.Path(d['icons_dir'])==root/'icons'; assert pathlib.Path(d['sounds_dir'])==root/'sounds'; assert d['audio']['format']=='ogg'
print('PASS config-relative asset-root resolution')
PY
# WAV master -> cached OGG/Vorbis conversion, if ffmpeg exists.
if command -v ffmpeg >/dev/null; then
  ffmpeg -hide_banner -loglevel error -f lavfi -i 'sine=frequency=900:duration=0.20' -c:a pcm_s16le "$TMP/sounds/security.wav" -y
  python3 - "$CLI" "$TMP/sounds" "$TMP/audio-cache" <<'PY'
import importlib.machinery,importlib.util,pathlib,sys
cli,sounds,cache=sys.argv[1:]
loader=importlib.machinery.SourceFileLoader('gctl',cli); spec=importlib.util.spec_from_loader(loader.name,loader); m=importlib.util.module_from_spec(spec); sys.modules['gctl']=m; loader.exec_module(m)
argv=['--no-config','--sounds-dir',sounds,'--audio-cache-dir',cache,'show-config']; args=m.build_parser().parse_args(argv); settings,apps,_=m.load_everything(args,argv); m.validate_args(args,settings,apps); c=m.Controller(args,settings,apps)
try:
    src=c._sound_source('security.ogg'); assert src and src.suffix=='.wav'; out=c._transcode_sound(src,'security.ogg'); assert out.is_file() and out.suffix=='.ogg' and out.stat().st_size>0
    out2=c._transcode_sound(src,'security.ogg'); assert out2==out
finally: c.close()
print('PASS WAV -> content-addressed OGG/Vorbis conversion/cache')
PY
else
  echo 'SKIP audio conversion test (ffmpeg not installed)'
fi
# Non-elevated client rotation must fail.
export GOTIFY_CLIENT_TOKEN='C-non'; set +e
"$CLI" --no-config --color never --state-file "$TMP/client-state.json" --gotify-url "http://127.0.0.1:$PORT" --client-token-env GOTIFY_CLIENT_TOKEN --secret-dir "$SECRETS_A" --app security rotate-tokens --confirm-token-rotation >/dev/null 2>"$TMP/non-elev.err"; RC=$?; set -e
[[ "$RC" -ne 0 ]]; grep -Eiq 'elevat|403' "$TMP/non-elev.err"; echo 'PASS non-elevated rotation refusal'
echo 'ALL gotify-androidctl self-tests PASS'
