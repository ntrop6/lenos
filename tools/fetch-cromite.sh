#!/usr/bin/env bash
# Fetch the pinned Cromite browser APK and verify its sha256 against
# config/VERSIONS.sh. Idempotent; exits 0 when the pinned APK is present.
set -Eeuo pipefail

LENOS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=/dev/null
source "$LENOS_ROOT/config/VERSIONS.sh"

DEST="$LENOS_ROOT/vendor/lenos/prebuilt/Cromite.apk"

if [[ -s "$DEST" ]]; then
    actual=$(sha256sum "$DEST" | awk '{print $1}')
    if [[ "$actual" == "$CROMITE_SHA256" ]]; then
        echo "Cromite already pinned and verified: $DEST"
        exit 0
    fi
    echo "ERROR: $DEST exists but does not match the pin ($actual != $CROMITE_SHA256)." >&2
    echo "Remove it or update config/VERSIONS.sh after verifying the new artifact." >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "Downloading $CROMITE_URL"
curl -fL --retry 3 --connect-timeout 20 -o "$tmp/Cromite.apk" "$CROMITE_URL"
actual=$(sha256sum "$tmp/Cromite.apk" | awk '{print $1}')
[[ "$actual" == "$CROMITE_SHA256" ]] || {
    echo "ERROR: downloaded Cromite does not match the pin ($actual != $CROMITE_SHA256)." >&2
    exit 1
}
install -m 644 "$tmp/Cromite.apk" "$DEST"
echo "Verified and installed: $DEST (sha256 $actual)"
