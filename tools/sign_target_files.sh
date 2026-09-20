#!/usr/bin/env bash
# Native (no container) release signer, adapted from the audited lenOS 2.8.1
# container signer (MIT). Re-signs every APK/APEX in the target-files with
# the generated release keys, audits the result, and builds the base OTA.
#
# Inputs via environment:
#   LENOS_TREE      path to the synced LineageOS tree
#   TARGET_FILES    absolute path to the built target-files zip
#   LENOS_KEYS      key directory (avb/, ota/, packages/, apex/ subdirs)
#   SIGNING_PLAN    path to signing-plan.json (produced by signing_metadata.py)
#   OUT_DIR         output directory
#   BUILD_VARIANT   userdebug (default)
set -Eeo pipefail

: "${LENOS_TREE:?}" "${TARGET_FILES:?}" "${LENOS_KEYS:?}" "${SIGNING_PLAN:?}" "${OUT_DIR:?}"
BUILD_VARIANT="${BUILD_VARIANT:-userdebug}"

META_TOOL="$(cd "$(dirname "$0")" && pwd)/signing_metadata.py"
VERIFY_TOOL="$(cd "$(dirname "$0")" && pwd)/verify_signed_target.py"
SIGNED_TMP="$OUT_DIR/.signed-target-files.zip.tmp"
BASE_OTA_TMP="$OUT_DIR/.base-signed-ota.zip.tmp"
SIGNED_OUT="$OUT_DIR/signed-target-files.zip"
BASE_OTA_OUT="$OUT_DIR/base-signed-ota.zip"

rm -f "$SIGNED_TMP" "$BASE_OTA_TMP"

# AOSP envsetup scripts probe unset variables deliberately; no -u here.
# shellcheck source=/dev/null
cd "$LENOS_TREE"
. build/envsetup.sh
breakfast lenos_asteroids "$BUILD_VARIANT" >/dev/null

args=(
    -o
    -d "$LENOS_KEYS/packages"
)

apk_mappings=$(python3 "$META_TOOL" emit "$SIGNING_PLAN" apk-mappings) || {
    echo "Failed to emit APK signing mappings" >&2
    exit 1
}
while IFS=$'\t' read -r source key_id; do
    [[ -n "$source" && -n "$key_id" ]] || continue
    args+=(--key_mapping "${source}=${LENOS_KEYS}/packages/${key_id}")
done <<<"$apk_mappings"

apex_mappings=$(python3 "$META_TOOL" emit "$SIGNING_PLAN" apex-mappings) || {
    echo "Failed to emit APEX signing mappings" >&2
    exit 1
}
while IFS=$'\t' read -r apex_name key_id; do
    [[ -n "$apex_name" && -n "$key_id" ]] || continue
    args+=(--extra_apks "${apex_name}=${LENOS_KEYS}/apex/${key_id}")
    args+=(--extra_apex_payload_key "${apex_name}=${LENOS_KEYS}/apex/${key_id}.pem")
done <<<"$apex_mappings"

printf '[sign] Re-signing APK and APEX containers/payloads...\n'
sign_target_files_apks "${args[@]}" "$TARGET_FILES" "$SIGNED_TMP"

# sign_target_files_apks preserves original key-path metadata in META/*.txt.
# Audit the actual nested signatures instead of trusting completion alone.
apksigner_bin=$(command -v apksigner || true)
[[ -n "$apksigner_bin" ]] || apksigner_bin="$LENOS_TREE/out/host/linux-x86/bin/apksigner"
[[ -x "$apksigner_bin" ]] || apksigner_bin="$LENOS_TREE/prebuilts/sdk/tools/linux/bin/apksigner"
[[ -x "$apksigner_bin" ]] || { echo "apksigner executable not found" >&2; exit 1; }
avbtool_bin=$(command -v avbtool || true)
[[ -n "$avbtool_bin" ]] || avbtool_bin="$LENOS_TREE/out/host/linux-x86/bin/avbtool"
[[ -x "$avbtool_bin" ]] || avbtool_bin="$LENOS_TREE/external/avb/avbtool.py"
[[ -x "$avbtool_bin" ]] || { echo "avbtool executable not found" >&2; exit 1; }

python3 "$VERIFY_TOOL" \
    --input "$TARGET_FILES" \
    --signed "$SIGNED_TMP" \
    --plan "$SIGNING_PLAN" \
    --package-keys "$LENOS_KEYS/packages" \
    --apex-keys "$LENOS_KEYS/apex" \
    --apksigner "$apksigner_bin" \
    --avbtool "$avbtool_bin"

mv -f "$SIGNED_TMP" "$SIGNED_OUT"

printf '[sign] Creating the full A/B OTA...\n'
ota_from_target_files \
    -k "$LENOS_KEYS/packages/releasekey" \
    "$SIGNED_OUT" \
    "$BASE_OTA_TMP"
mv -f "$BASE_OTA_TMP" "$BASE_OTA_OUT"

printf '[sign] Base signed OTA: %s\n' "$BASE_OTA_OUT"
