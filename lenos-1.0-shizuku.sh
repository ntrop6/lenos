#!/usr/bin/env bash
# lenOS 1.0.0-shizuku — product driver for Nothing Phone (3a) `asteroids`.
#
# This is the 1.0 entry point. It does not reimplement Soong/repo/signing.
# The external build/signing wizard remains the compiler. This script:
#   - never repo syncs
#   - applies patches only through vendor/lenos/tools/lenos-patch.py (strict
#     `git apply`, no fuzz; refuses to patch a project that is not pristine)
#   - never flashes the phone
#   - never locks
#   - never re-signs firmware (abl/xbl/bluetooth VBMeta magic)
#   - builds and packages rootless by default
#
# Root is opt-in and post-build: LENOS_ROOT=bakasu|kernelsu. The normal
# LineageOS build stays rootless. root-prepare patches init_boot from the
# signed base OTA, package re-signs the whole OTA with the user's AVB/OTA keys,
# and the root manager remains a separate userspace APK. See docs/root.md.
#
# Subcommands: doctor | apply | build | package | extract | flash-plan |
#              lock-gates | root-prepare | root-status
# (`hardwire` is kept as an alias of `apply` for the older scripts/manuals)
#
# Experimental mode: set LENOS_EXPERIMENTAL=1. The driver then applies
# patches-experimental/ after the stable series, installs experimental/app/,
# and exports the same flag to the build so config/lenos.mk inherits the
# experimental product fragment. Default is 0; no experimental source is
# patched into the tree and LenosOpsec is not built.
set -euo pipefail
umask 077

readonly LENOS_VERSION="1.0.0-shizuku"

err()  { printf '[lenOS %s] ERROR: %s\n' "$LENOS_VERSION" "$*" >&2; }
die()  { err "$*"; exit 1; }
info() { printf '[lenOS %s] %s\n' "$LENOS_VERSION" "$*" >&2; }

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
WS="${LENOS_WORKSPACE:-$HOME/lenos-workspace}"
SRC="${LENOS_SOURCE:-$WS/lineage}"
KEYS="${LENOS_KEYDIR:-$HOME/secure-keys/asteroids}"
AVBROOT="${AVBROOT:-$WS/tools/avbroot}"
WIZARD="${LENOS_WIZARD:-$HOME/lenOS-2.8.1-ReSukiSU-single.sh}"
if [[ ! -x "$WIZARD" && -x "$HOME/Downloads/lenOS-2.8.1-ReSukiSU-single.sh" ]]; then
  WIZARD="$HOME/Downloads/lenOS-2.8.1-ReSukiSU-single.sh"
fi
readonly WIZARD_SHA256_DEFAULT="7efc6fee0fb8f6582774bb6efeeb8e7fc721c2d1ca04adcb8116d9f071b7530b"
WIZARD_SHA256="${LENOS_WIZARD_SHA256:-$WIZARD_SHA256_DEFAULT}"
VENDOR="${LENOS_VENDOR:-}"
if [[ -z "$VENDOR" ]]; then
  if [[ -d "$SELF_DIR/vendor-lenos" ]]; then VENDOR="$SELF_DIR/vendor-lenos"
  elif [[ -f "$SELF_DIR/tools/lenos-patch.py" ]]; then VENDOR="$SELF_DIR"
  elif [[ -d "$HOME/vendor-lenos" ]]; then VENDOR="$HOME/vendor-lenos"
  else VENDOR="$SELF_DIR/vendor-lenos"
  fi
fi
ROOT_MODE="none"
ROOT_STATE_BASE="$WS/lenos-root"
ROOT_STATE_DIR=""
ROOT_CACHE="${LENOS_ROOT_CACHE:-$WS/.root-cache}"
ROOT_LKM="${LENOS_ROOT_LKM:-}"
ROOT_ALLOW_UNVALIDATED_LKM="${LENOS_ALLOW_UNVALIDATED_LKM:-0}"
OUT="$WS/lenos-asteroids-rootless.zip"
EXTRACT_DIR="$WS/extracted-rootless"

# Qualcomm firmware / bootloader images. avbroot --re-sign of these aborts
# with "Invalid VBMeta header magic" (bluetooth/abl/xbl). OS AVB only. The
# list lives in tools/firmware-deny.txt so the re-sign filter and the
# fastboot-info sanitizer cannot drift.
readonly FIRMWARE_DENY_FILE="$VENDOR/tools/firmware-deny.txt"

usage() {
  cat <<EOF
lenOS $LENOS_VERSION  (asteroids / Nothing Phone 3a)

  $0 doctor         build host / keys / wizard / avbroot / patchkit
  $0 apply          reset-hardening, install vendor/lenos, apply the patch series
  $0 build          apply + 8–17h  mka  --rootless --hardening full
  $0 root-prepare   opt-in: patch init_boot from base-signed-ota.zip
  $0 root-status    print/check the prepared root state
  $0 package        avbroot OTA. rootless unless LENOS_ROOT is set.
  $0 extract        avbroot ota extract --fastboot --all + sanitize flash plan
  $0 flash-plan     print host-side commands. does not touch the phone
  $0 lock-gates     print lock warnings/gates. always exits 1 (this script will not lock)

Default build: stable 1.0 series, rootless.
Root (opt-in): LENOS_ROOT=bakasu|kernelsu. Build first, then root-prepare,
  then package. BakaSU is preferred; KernelSU is the fallback.
  Example: LENOS_ROOT=bakasu LENOS_ROOT_LKM=/path/to/kernelsu.ko $0 root-prepare
  The LKM must be built against this tree's kernel. The pinned GKI module is
  rejected unless LENOS_ALLOW_UNVALIDATED_LKM=1 is explicitly set.
  Root mode never changes the product or includes a manager APK in the system
  image. It re-signs init_boot and every OS AVB partition with your keys.
Experimental build: LENOS_EXPERIMENTAL=1 $0 apply|build
  (patches-experimental + experimental/app/LenosOpsec + HTS-1 bionic
   hardened thread stacks; never device-validated)

Never: repo sync, git apply, flash, lock, firmware --re-sign.
EOF
}

need_file() { [[ -s "$1" ]] || die "missing $1"; }
need_exec() { [[ -x "$1" ]] || die "missing executable $1"; }

verify_wizard() {
  need_exec "$WIZARD"
  local actual
  actual="$(sha256sum "$WIZARD" | awk '{print $1}')"
  [[ "$actual" == "$WIZARD_SHA256" ]] || die \
    "external wizard hash mismatch: $WIZARD
    expected $WIZARD_SHA256
    actual   $actual
    The wizard is not part of this repository. Pin the exact file you audited
    with LENOS_WIZARD_SHA256=<sha256> or restore the pinned 2.8.1 release."
  info "wizard:  $WIZARD (sha256 $actual)"
}

require_boot_verification_tools() {
  "$AVBROOT" boot unpack --help >/dev/null 2>&1 \
    && "$AVBROOT" cpio unpack --help >/dev/null 2>&1 \
    || die "avbroot 3.33.0+ with boot unpack and cpio unpack is required to verify boot images"
}

experimental_enabled() {
  case "${LENOS_EXPERIMENTAL:-0}" in
    1|true|TRUE|yes|YES) return 0;;
    *) return 1;;
  esac
}

root_enabled() {
  [[ "$ROOT_MODE" != "none" ]]
}

resolve_root_mode() {
  local requested="${LENOS_ROOT-none}"
  requested="${requested,,}"
  case "$requested" in
    none|rootless) requested="none";;
    bakasu|kernelsu) ;;
    *) die "invalid LENOS_ROOT='$requested' (use none, bakasu, or kernelsu)";;
  esac
  ROOT_MODE="$requested"
  if root_enabled; then
    ROOT_STATE_DIR="$ROOT_STATE_BASE/$ROOT_MODE"
    OUT="$WS/lenos-asteroids-$ROOT_MODE.zip"
    EXTRACT_DIR="$WS/extracted-$ROOT_MODE"
  else
    ROOT_STATE_DIR=""
    OUT="$WS/lenos-asteroids-rootless.zip"
    EXTRACT_DIR="$WS/extracted-rootless"
  fi
}

select_base_ota() {
  local candidate chosen=""
  if [[ -n "${LENOS_BASE_OTA:-}" ]]; then
    [[ -s "$LENOS_BASE_OTA" ]] \
      || die "LENOS_BASE_OTA is set but not a file: $LENOS_BASE_OTA"
    printf '%s\n' "$LENOS_BASE_OTA"
    return 0
  fi
  if [[ -s "$WS/base-signed-ota.zip" ]]; then
    printf '%s\n' "$WS/base-signed-ota.zip"
    return 0
  fi
  for candidate in "$WS/out/target/product/asteroids"/*.zip; do
    [[ -s "$candidate" ]] && chosen="$candidate"
  done
  [[ -n "$chosen" ]] || die "no input OTA. expected $WS/base-signed-ota.zip after build"
  printf '%s\n' "$chosen"
}

# Read BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE from the pinned device tree. This
# is the upper bound avbroot pads the final partition to; do not guess it from
# the input image size.
partition_limit() {
  python3 - "$SRC/device/nothing/asteroids/BoardConfig.mk" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
pattern = re.compile(
    r"^\s*BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE\s*:?=\s*"
    r"(0x[0-9a-fA-F]+|[0-9]+)\s*$"
)
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    match = pattern.match(line)
    if match:
        print(int(match.group(1), 0))
        raise SystemExit
raise SystemExit(f"BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE not found in {path}")
PY
}

assert_image_fits_partition() {
  local image="$1" partition="$2" limit size
  [[ "$partition" == init_boot ]] || return 0
  limit="$(partition_limit)" || die "cannot determine init_boot partition size"
  size="$(stat -c %s "$image")"
  ((size <= limit)) \
    || die "$partition image exceeds its partition: $size > $limit bytes"
  info "$partition image size: $size / $limit bytes"
}

verify_ota_boot_images() {
  local ota="$1" temp p
  require_boot_verification_tools
  temp="$(mktemp -d "$WS/.boot-check.XXXXXX")"
  "$AVBROOT" ota extract \
    --input "$ota" \
    --directory "$temp" \
    --partition boot \
    --partition init_boot \
    --partition vendor_boot >/dev/null \
    || { rm -rf "$temp"; die "could not extract boot partitions from final OTA"; }
  for p in boot init_boot vendor_boot; do
    [[ -s "$temp/$p.img" ]] \
      || { rm -rf "$temp"; die "final OTA is missing $p.img"; }
    assert_image_fits_partition "$temp/$p.img" "$p"
  done
  if root_enabled; then
    python3 "$VENDOR/tools/lenos_root.py" verify-image \
      --mode "$ROOT_MODE" \
      --image "$temp/init_boot.img" \
      --state-dir "$ROOT_STATE_DIR" \
      --avbroot "$AVBROOT" >/dev/null \
      || { rm -rf "$temp"; die "final OTA init_boot ramdisk verification failed"; }
  else
    # avbroot --rootless means "do not add root", not "remove an existing root".
    # Verify the final image really has a stock ramdisk so a wrongly selected
    # base OTA cannot be re-signed and shipped as the rootless default.
    python3 "$VENDOR/tools/lenos_root.py" verify-image \
      --mode stock \
      --image "$temp/init_boot.img" \
      --avbroot "$AVBROOT" >/dev/null \
      || { rm -rf "$temp"; die "final OTA init_boot is not stock/rootless"; }
  fi
  rm -rf "$temp"
  info "boot/init_boot/vendor_boot images verified"
}

verify_input_ota() {
  local ota="$1"
  "$AVBROOT" ota verify \
    --input "$ota" \
    --cert-ota "$KEYS/ota.crt" \
    --public-key-avb "$KEYS/avb_pkmd.bin" \
    || die "input OTA is not signed by the configured OTA/AVB keys: $ota"
}

cmd_doctor() {
  info "doctor"
  [[ "$(uname -s)" == Linux ]] || die "Linux host only"
  verify_wizard
  need_exec "$AVBROOT"
  info "avbroot: $($AVBROOT --version 2>/dev/null || echo unknown)"
  [[ -f "$SRC/device/nothing/asteroids/lineage_asteroids.mk" ]] \
    || die "not an asteroids tree: $SRC"
  [[ -d "$VENDOR" && -f "$VENDOR/tools/lenos-patch.py" \
     && -f "$VENDOR/tools/lenos_projects.py" ]] \
    || die "vendor/lenos patchkit not next to this script and not at $VENDOR"
  if experimental_enabled; then
    [[ -d "$VENDOR/patches-experimental" ]] \
      || die "experimental patch series missing: $VENDOR/patches-experimental"
    [[ -d "$VENDOR/experimental/app/LenosOpsec" ]] \
      || die "experimental app source missing: $VENDOR/experimental/app/LenosOpsec"
    info "mode:    experimental (LENOS_EXPERIMENTAL=1)"
    info "stacks:  hardened thread stacks (HTS-1, experimental)"
  else
    info "mode:    stable 1.0"
  fi
  if root_enabled; then
    need_file "$VENDOR/tools/lenos_root.py"
    need_file "$VENDOR/tools/root-managers.json"
    need_file "$VENDOR/tools/apk_signing_cert.py"
    require_boot_verification_tools
    if [[ -n "$ROOT_LKM" ]]; then
      need_file "$ROOT_LKM"
      info "root:    $ROOT_MODE (local LKM: $ROOT_LKM)"
    else
      case "${ROOT_ALLOW_UNVALIDATED_LKM,,}" in
        1|true|yes)
          info "root:    $ROOT_MODE (pinned GKI LKM, explicitly UNVALIDATED)"
          ;;
        *)
          info "root:    $ROOT_MODE (no local LKM; root-prepare will refuse without one)"
          ;;
      esac
    fi
  else
    info "root:    none (rootless)"
  fi
  need_file "$KEYS/avb.key"
  need_file "$KEYS/ota.key"
  need_file "$KEYS/ota.crt"
  need_file "$KEYS/avb_pkmd.bin"
  command -v python3 >/dev/null || die "python3 required"
  command -v git >/dev/null || die "git required"
  command -v sha256sum >/dev/null || die "sha256sum required"
  info "tree:    $SRC"
  info "keys:    $KEYS"
  info "vendor:  $VENDOR"
  info "OK. do not repo sync. do not lock."
}

# Projects touched by the selected patch series (unique), read from the patchkit.
series_projects() {
  {
    python3 "$VENDOR/tools/lenos-patch.py" --list
    if experimental_enabled; then
      python3 "$VENDOR/tools/lenos-patch.py" --list --experimental
    fi
  } | cut -f1 | sort -u
}

# Refuse to patch a project that still has tracked modifications: the
# patchkit assumes pinned sources, and a stale change from an older pipeline
# could otherwise survive next to a patch that applies cleanly.
require_pristine() {
  local projects proj changes dirty=0
  projects="$(series_projects)" || die "cannot list the patch series projects"
  [[ -n "$projects" ]] || die "patch series is empty - refusing to patch"
  while IFS= read -r proj; do
    [[ -n "$proj" ]] || continue
    if [[ -d "$SRC/$proj/.git" || -f "$SRC/$proj/.git" ]]; then
      changes="$(git -C "$SRC/$proj" status --porcelain --untracked-files=no)"
      if [[ -n "$changes" ]]; then
        err "project not pristine: $proj"
        printf '%s\n' "$changes" | sed 's/^/    /' >&2
        dirty=1
      fi
    else
      die "no git checkout at $SRC/$proj (fix with repo sync only, then re-pin)"
    fi
  done <<< "$projects"
  if [[ "$dirty" -ne 0 ]]; then
    die "tree is not pinned. reset first: '$WIZARD reset hardening', then
    'git -C \$SRC/<project> checkout -- .' for anything still listed"
  fi
}

# Build inputs only (config/, app/, rro/). The patchkit, tests and
# docs stay in $VENDOR outside the tree; nothing else is compiled.
install_vendor_lenos() {
  local part
  if [[ "$VENDOR" -ef "$SRC/vendor/lenos" ]]; then
    die "the helper must run from a patchkit checkout outside \$SRC/vendor/lenos; use the manual build path in docs/build.md"
  fi
  info "install vendor/lenos build inputs -> $SRC/vendor/lenos"
  rm -rf "$SRC/vendor/lenos"
  mkdir -p "$SRC/vendor/lenos"
  for part in config app rro; do
    cp -a "$VENDOR/$part" "$SRC/vendor/lenos/"
  done
  if experimental_enabled; then
    [[ -d "$VENDOR/experimental/app" ]] \
      || die "experimental app tree missing: $VENDOR/experimental/app"
    info "install experimental app inputs -> $SRC/vendor/lenos/app"
    cp -a "$VENDOR/experimental/app/." "$SRC/vendor/lenos/app/"
    need_file "$SRC/vendor/lenos/app/LenosOpsec/Android.bp"
  fi
  need_file "$SRC/vendor/lenos/config/lenos.mk"
  need_file "$SRC/vendor/lenos/config/privapp-permissions-org.lenos.security.xml"
}

cmd_apply() {
  cmd_doctor
  export LENOS_ALLOW_LOW_MEMORY="${LENOS_ALLOW_LOW_MEMORY:-1}"
  export LENOS_BUILD_JOBS="${LENOS_BUILD_JOBS:-4}"

  local experimental=0 exp_was_applied=0 exp_status
  if experimental_enabled; then experimental=1; fi
  export LENOS_EXPERIMENTAL="$experimental"
  if [[ "$experimental" -eq 1 ]]; then
    info "build mode: EXPERIMENTAL (patches-experimental + LenosOpsec; not device-validated)"
  else
    info "build mode: stable 1.0 (experimental series disabled)"
  fi

  # Detect an applied experimental series before either reset reverts its
  # tracked hunks. Its created files must still be removed when switching back
  # to a stable build.
  exp_status="$(python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" \
      --experimental --status 2>/dev/null || true)"
  if grep -q '^  applied' <<< "$exp_status"; then exp_was_applied=1; fi

  info "wizard reset hardening (git reset of patched projects)"
  "$WIZARD" reset hardening

  if [[ "$experimental" -eq 1 || "$exp_was_applied" -eq 1 ]]; then
    info "patchkit --experimental --reset (remove experimental files)"
    python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --experimental --reset \
      || die "experimental patchkit --reset failed"
  fi

  info "patchkit --reset (pinned state; also removes files the series created)"
  python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --reset \
    || die "patchkit --reset failed"
  require_pristine
  install_vendor_lenos

  info "patchkit --check (strict, must pass before anything is written)"
  python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --check \
    || die "patchkit --check failed: tree does not match the pinned revisions"

  info "patchkit --apply"
  python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --apply \
    || die "patchkit --apply failed"

  # Validate the stable series before the experimental patches change any of
  # its context. --require-applied reverse-replays the whole series in a
  # throwaway copy, so overlapping patches cannot produce a false "missing".
  info "patchkit --require-applied"
  python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --require-applied \
    || die "stable series is not fully applied. do not build a half-patched tree."

  if [[ "$experimental" -eq 1 ]]; then
    info "experimental patchkit --check (strict, after the stable series)"
    python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --experimental --check \
      || die "experimental patchkit --check failed: stable tree does not match"

    info "experimental patchkit --apply"
    python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --experimental --apply \
      || die "experimental patchkit --apply failed"

    info "experimental patchkit --require-applied"
    python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" \
      --experimental --require-applied \
      || die "experimental series is not fully applied. refusing a half-patched build."
  fi

  # Markers of this series, independent of the patchkit's own reporting.
  grep -q '>dns.quad9.net<' \
    "$SRC/vendor/lenos/rro/LenosSettingsProviderOverlay/res/values/defaults.xml" \
    || die "Quad9 DoT default missing from the settings RRO"
  grep -q 'def_lenos_private_dns_specifier' \
    "$SRC/frameworks/base/packages/SettingsProvider/res/values/defaults.xml" \
    || die "first-boot default resources missing from SettingsProvider"
  grep -q 'ro.lenos.version' "$SRC/vendor/lenos/config/lenos.mk" \
    || die "lenOS version prop missing from config/lenos.mk"
  grep -q 'PRODUCT_COMPRESSED_APEX := false' "$SRC/vendor/lenos/config/lenos.mk" \
    || die "compressed APEX not disabled in the lenOS product config"
  grep -q 'SendDhcpHostname2' \
    "$SRC/packages/modules/Wifi/service/java/com/android/server/wifi/util/XmlUtil.java" \
    || die "Wi-Fi DHCP-hostname privacy default missing from the Wi-Fi module"
  grep -q 'RANDOMIZATION_ALWAYS' \
    "$SRC/packages/modules/Wifi/framework/java/android/net/wifi/WifiConfiguration.java" \
    || die "Wi-Fi MAC randomization default missing from the Wi-Fi module"
  grep -q 'setupPinScrambling' \
    "$SRC/frameworks/base/packages/SystemUI/src/com/android/keyguard/KeyguardPinBasedInputView.java" \
    || die "keyguard PIN scrambling missing from SystemUI"
  grep -q 'scramble_pin_layout' \
    "$SRC/packages/apps/Settings/src/com/android/settings/security/screenlock/PinScramblingPrefController.java" \
    || die "keyguard PIN scrambling UI missing from Settings"
  grep -q 'MAX_PASSWORD_LENGTH = 128' \
    "$SRC/frameworks/base/core/java/android/app/admin/DevicePolicyManager.java" \
    || die "password-length hardening missing"
  grep -q 'SYSTEM_CLOCK_PARANOIA_THRESHOLD_MILLIS = 250' \
    "$SRC/frameworks/base/services/core/java/com/android/server/timedetector/TimeDetectorStrategyImpl.java" \
    || die "clock-drift warning hardening missing"
  grep -q 'checkPendingIntent2' \
    "$SRC/frameworks/base/core/java/android/app/PendingIntent.java" \
    || die "PendingIntent immutability warp missing"
  grep -q 'def_lock_screen_allow_private_notifications">false<' \
    "$SRC/frameworks/base/packages/SettingsProvider/res/values/defaults.xml" \
    || die "lockscreen notification-content privacy default missing"
  grep -q 'config_multiuserMaximumUsers">32<' \
    "$SRC/device/nothing/asteroids/rro_overlays/FrameworksResCommon_Vendor/res/values/config.xml" \
    || die "multiuser limit hardening missing"
  grep -q 'ExtSettings.SCREENSHOT_TIMESTAMP_EXIF.get(resolver.getContext())' \
    "$SRC/frameworks/base/packages/SystemUI/src/com/android/systemui/screenshot/ImageExporter.java" \
    || die "screenshot EXIF privacy gate missing from SystemUI"
  grep -q 'privacy_screenshot_timestamp_exif' \
    "$SRC/packages/apps/Settings/res/xml/more_security_privacy_settings.xml" \
    || die "screenshot EXIF setting row missing from Settings"
  for ca in 53a1b57a.0 60afe812.0 9d6523ce.0; do
    [[ ! -e "$SRC/system/ca-certificates/files/$ca" ]] \
      || die "distrusted CA $ca is still shipped"
  done
  grep -q 'options->flags |= FSCRYPT_POLICY_FLAGS_PAD_32;' \
    "$SRC/system/extras/libfscrypt/fscrypt.cpp" \
    || die "FBE filename padding not hardened"
  grep -q 'KEY_ENABLE_CMAS_PRESIDENTIAL_ALERTS, true' \
    "$SRC/packages/apps/CellBroadcastReceiver/src/com/android/cellbroadcastreceiver/CellBroadcastAlertService.java" \
    || die "wireless alerts not made optional"
  grep -q 'show_presidential_alerts_settings">true<' \
    "$SRC/packages/apps/CellBroadcastReceiver/res/values/config.xml" \
    || die "presidential alert settings row not enabled"
  grep -q 'public static boolean isAllowButton' \
    "$SRC/packages/modules/Permission/PermissionController/src/com/android/permissioncontroller/permission/ui/GrantPermissionsActivity.java" \
    || die "permission dialog Allow buttons not delayed"
  grep -q 'accidental Allow button tap' \
    "$SRC/frameworks/base/packages/SystemUI/src/com/android/systemui/usb/UsbDebuggingActivity.java" \
    || die "USB debugging Allow button not delayed"
  grep -q 'clipboardReadAllowedForPackage' \
    "$SRC/frameworks/base/services/core/java/com/android/server/clipboard/ClipboardService.java" \
    || die "Secure Paste clipboard read gate missing"
  grep -q 'privacy_secure_paste' \
    "$SRC/packages/apps/Settings/res/xml/more_security_privacy_settings.xml" \
    || die "Secure Paste setting row missing from Settings"
  grep -q 'isExportAccessAllowed' \
    "$SRC/frameworks/base/services/core/java/com/android/server/clipboard/ClipboardService.java" \
    || die "cross-profile clipboard export gate missing"
  grep -q 'CROSS_PROFILE_CLIPBOARD_ACCESS_SETTINGS' \
    "$SRC/frameworks/base/core/java/android/ext/settings/CrossProfileClipboardAccessSettings.java" \
    || die "cross-profile clipboard policy class missing"
  grep -q 'cross_profile_clipboard_access' \
    "$SRC/frameworks/base/core/java/android/provider/Settings.java" \
    || die "cross-profile clipboard setting key missing"
  grep -q 'privacy_cross_profile_clipboard' \
    "$SRC/packages/apps/Settings/res/xml/more_security_privacy_settings.xml" \
    || die "cross-profile clipboard setting row missing from Settings"
  grep -q 'canProtectLocked(uid, \*netId)' \
    "$SRC/system/netd/server/NetworkController.cpp" \
    || die "VPN lockdown DNS leak fix missing from netd"
  grep -q 'MulticastFirewallController' \
    "$SRC/system/netd/server/Controllers.cpp" \
    || die "netd multicast firewall not wired"
  grep -q 'mfw_OUTPUT' \
    "$SRC/system/netd/server/MulticastFirewallController.cpp" \
    || die "netd multicast firewall rules missing"
  grep -q 'isRegularAppWithLockdownVpnEnabled' \
    "$SRC/packages/modules/Connectivity/service-t/src/com/android/server/NsdService.java" \
    || die "NSD lockdown check missing"
  grep -q 'isRegularAppWithLockdownVpnEnabled' \
    "$SRC/frameworks/base/core/java/android/ext/ConnectivityUtil.java" \
    || die "ConnectivityUtil helper missing"
  grep -q 'isAlwaysOnPackageSupported returned false' \
    "$SRC/frameworks/base/services/core/java/com/android/server/connectivity/Vpn.java" \
    || die "always-on VPN survival change missing"
  grep -q 'no implicit foreground-location grant' \
    "$SRC/frameworks/base/services/core/java/com/android/server/pm/permission/DefaultPermissionGrantPolicy.java" \
    || die "browser location auto-grant not removed"
  grep -q 'SystemServerExt.init(mSystemContext, mPackageManagerService);' \
    "$SRC/frameworks/base/services/java/com/android/server/SystemServer.java" \
    || die "SystemServerExt hook missing"
  grep -q 'class WifiAutoOff' \
    "$SRC/frameworks/base/services/core/java/com/android/server/ext/WifiAutoOff.java" \
    || die "WifiAutoOff missing"
  grep -q 'class BluetoothAutoOff' \
    "$SRC/frameworks/base/services/core/java/com/android/server/ext/BluetoothAutoOff.java" \
    || die "BluetoothAutoOff missing"
  grep -q 'android:key="wifi_auto_off"' \
    "$SRC/packages/apps/Settings/res/xml/more_security_privacy_settings.xml" \
    || die "Wi-Fi auto-off setting row missing"
  grep -q 'android:key="bluetooth_auto_off"' \
    "$SRC/packages/apps/Settings/res/xml/more_security_privacy_settings.xml" \
    || die "Bluetooth auto-off setting row missing"
  grep -q 'private void addLteOnlyEntry()' \
    "$SRC/packages/apps/Settings/src/com/android/settings/network/telephony/EnabledNetworkModePreferenceController.java" \
    || die "LTE-only network mode entry missing"
  grep -q 'private void addNrOnlyEntry()' \
    "$SRC/packages/apps/Settings/src/com/android/settings/network/telephony/EnabledNetworkModePreferenceController.java" \
    || die "5G-only network mode entry missing"
  grep -q 'name="preferred_network_mode_lte_only_summary"' \
    "$SRC/packages/apps/Settings/res/values/strings_ext.xml" \
    || die "LTE-only summary string missing"
  grep -q 'private static void applyConfigOverrides' \
    "$SRC/frameworks/base/services/core/java/com/android/server/location/gnss/GnssConfiguration.java" \
    || die "GNSS SUPL/PSDS privacy overrides missing"
  grep -q 'SUPL_DISABLED, // lenOS: disabled by default' \
    "$SRC/frameworks/base/core/java/android/ext/settings/GnssSettings.java" \
    || die "GNSS settings defaults missing"
  grep -q 'private boolean isPsdsEnabled()' \
    "$SRC/frameworks/base/services/core/java/com/android/server/location/gnss/GnssLocationProvider.java" \
    || die "PSDS download gate missing"
  grep -q 'android:key="gnss_supl"' \
    "$SRC/packages/apps/Settings/res/xml/location_settings.xml" \
    || die "GNSS network-assistance settings rows missing"
  grep -q 'StorageScopesHooks.obtainDirContents' \
    "$SRC/packages/providers/MediaProvider/src/com/android/providers/media/MediaProvider.java" \
    || die "MediaProvider directory-listing restriction missing"
  grep -q 'grapheneos.package_update_preserves_package_enabled_setting' \
    "$SRC/frameworks/base/services/core/java/com/android/server/pm/SystemConfig.java" \
    || die "package enabled-state preservation missing"
  grep -q 'showPrototypeNotificationIfPrototype' \
    "$SRC/frameworks/base/services/core/java/com/android/server/am/ActivityManagerService.java" \
    || die "prototype device warning missing"
  grep -q 'NOTE_PROTOTYPE_DETECTED = 400;' \
    "$SRC/frameworks/base/proto/src/system_messages.proto" \
    || die "prototype device system message id missing"
  grep -q 'android:key="bootloader_version"' \
    "$SRC/packages/apps/Settings/res/xml/firmware_version.xml" \
    || die "bootloader version field missing"
  grep -q 'System.gc();' \
    "$SRC/frameworks/base/packages/SystemUI/src/com/android/systemui/keyguard/KeyguardViewMediator.java" \
    || die "lock-time SystemUI GC missing"
  grep -q 'keyguardShowingChanged && keyguardShowing' \
    "$SRC/frameworks/base/services/core/java/com/android/server/wm/ActivityTaskManagerService.java" \
    || die "lock-time system_server GC missing"
  grep -q 'if (!app.installed) return null' \
    "$SRC/packages/apps/Settings/src/com/android/settings/spa/app/appinfo/AppDisableButton.kt" \
    || die "user-installed app disabling missing"
  grep -q 'FLAG_INTERNET_COMPAT_ENABLED' \
    "$SRC/frameworks/base/core/java/android/content/pm/SrtPermissions.java" \
    || die "network permission (special runtime permissions) framework missing"
  grep -q 'SpecialRuntimePermAppUtils.isInternetCompatEnabled()' \
    "$SRC/packages/modules/Connectivity/framework/src/android/net/ConnectivityManager.java" \
    || die "network-permission connectivity gates missing"
  grep -q 'isSpecialRuntimePermissionGroup' \
    "$SRC/packages/modules/Permission/PermissionController/src/com/android/permissioncontroller/permission/utils/PermissionMapping.kt" \
    || die "network-permission permission-UI integration missing"
  grep -q 'setNewlyInstalledInUserId' \
    "$SRC/frameworks/base/services/core/java/com/android/server/pm/InstallPackageHelper.java" \
    || die "new-install gate for special runtime permissions missing"
  grep -q 'android.permission.OTHER_SENSORS' \
    "$SRC/frameworks/native/libs/sensor/Sensor.cpp" \
    || die "sensors permission native tag missing"
  grep -q 'protectedByOtherSensorsPerm' \
    "$SRC/frameworks/native/services/sensorservice/SensorService.cpp" \
    || die "sensors permission enforcement missing"
  grep -q 'onDeniedSpecialRuntimePermissionOp' \
    "$SRC/frameworks/base/services/core/java/com/android/server/pm/PackageManagerNative.java" \
    || die "sensors permission denial notification hook missing"
  grep -q 'NOTE_MISSING_PERMISSION_OTHER_SENSORS = 500;' \
    "$SRC/frameworks/base/proto/src/system_messages.proto" \
    || die "sensors permission system message id missing"
  grep -q 'OP_COARSE_LOCATION' \
    "$SRC/frameworks/base/packages/SystemUI/src/com/android/systemui/privacy/AppOpsPrivacyItemMonitor.kt" \
    || die "location indicator coarse-op coverage missing"
  grep -q 'shouldAvoidStateReuse' \
    "$SRC/packages/modules/NetworkStack/src/android/net/dhcp/DhcpClient.java" \
    || die "DHCP lease-reuse fix for per-connection MAC randomization missing"
  grep -q 'if (false && mUserLogoutInteractor.isPolicyManagerLogoutEnabled' \
    "$SRC/frameworks/base/packages/SystemUI/src/com/android/systemui/statusbar/KeyguardIndicationController.java" \
    || die "lock screen end session button not disabled"
  grep -q 'DISALLOW_INSTALL_UNKNOWN_SOURCES' \
    "$SRC/packages/apps/Settings/src/com/android/settings/users/UserAppsInstallSettings.java" \
    || die "per-user app install policy missing"

  if [[ "$experimental" -eq 1 ]]; then
    # Independent experimental markers. These are source-level assertions, not
    # proof that the features build or behave correctly.
    grep -q 'CLIPBOARD_CLEAR_ON_SCREEN_OFF' \
      "$SRC/frameworks/base/core/java/android/provider/Settings.java" \
      || die "experimental screen-off clipboard setting missing"
    grep -q 'NativeDebuggingBlock.apply' \
      "$SRC/frameworks/base/core/java/android/app/ActivityThread.java" \
      || die "experimental native-debugging hook missing"
    grep -q 'UsbPortSecurityController' \
      "$SRC/frameworks/base/services/usb/java/com/android/server/usb/UsbService.java" \
      || die "experimental USB port security missing"
    grep -q 'lenos_crash_logs' \
      "$SRC/packages/apps/Settings/res/xml/my_device_info.xml" \
      || die "experimental crash-log viewer missing"
    grep -q 'ro.boot.verifiedbootstate' \
      "$SRC/packages/apps/SetupWizard/src/org/lineageos/setupwizard/WelcomeActivity.java" \
      || die "experimental Setup Wizard warning missing"
    grep -q 'app.grapheneos' \
      "$SRC/packages/apps/Seedvault/app/src/main/java/com/stevesoltys/seedvault/App.kt" \
      || die "experimental Seedvault prefix missing"
    need_file "$SRC/vendor/lenos/app/LenosOpsec/Android.bp"
    grep -q 'LenosOpsec' "$SRC/vendor/lenos/config/lenos-experimental.mk" \
      || die "experimental product fragment does not include LenosOpsec"
    grep -q 'ro.lenos.experimental=1' "$SRC/vendor/lenos/config/lenos-experimental.mk" \
      || die "experimental product marker missing"
    grep -q '__allocate_hardened_thread_mapping' \
      "$SRC/bionic/libc/bionic/pthread_create.cpp" \
      || die "experimental hardened thread-stack patch missing from bionic"
    grep -q 'ro.lenos.hardened_thread_stacks=1' \
      "$SRC/vendor/lenos/config/lenos-experimental.mk" \
      || die "hardened thread-stack property missing from the experimental product fragment"
    info "hardened thread stacks ENABLED (HTS-1; experimental, still needs a build and boot test)"
    info "experimental markers OK - build is experimental, not device-validated"
  else
    [[ ! -e "$SRC/vendor/lenos/app/LenosOpsec" ]] \
      || die "experimental app present in a stable build tree"
    if grep -q 'lenos_crash_logs' \
        "$SRC/packages/apps/Settings/res/xml/my_device_info.xml" 2>/dev/null; then
      die "experimental Settings changes present in a stable build tree"
    fi
  fi

  if [[ "$experimental" -eq 1 ]]; then
    info "apply OK - tree carries the stable + experimental lenOS series"
  else
    info "apply OK - tree carries the lenOS 1.0 patch series"
  fi
}

cmd_build() {
  cmd_apply
  export LENOS_ALLOW_LOW_MEMORY="${LENOS_ALLOW_LOW_MEMORY:-1}"
  export LENOS_BUILD_JOBS="${LENOS_BUILD_JOBS:-4}"
  info "wizard reset build (clears out/, not the tree)"
  "$WIZARD" reset build
  info "compile --rootless --hardening full  (8–17h, tmux this)"
  "$WIZARD" build --rootless --hardening full
  # The wizard can reset or rewrite parts of the tree. Re-verify that the exact
  # lenOS series is still applied before anyone packages the result.
  info "post-build patchkit --require-applied"
  python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --require-applied \
    || die "the build tree drifted: the stable lenOS series is no longer fully applied. Do not package this build."
  if experimental_enabled; then
    info "post-build experimental patchkit --require-applied"
    python3 "$VENDOR/tools/lenos-patch.py" --tree "$SRC" --experimental --require-applied \
      || die "the build tree drifted: the experimental lenOS series is no longer fully applied. Do not package this build."
  fi
  info "post-build patch verification OK"
  if root_enabled; then
    info "compile finished. root is post-build; next: LENOS_ROOT=$ROOT_MODE $0 root-prepare"
  else
    info "compile finished. next: $0 package"
  fi
}

collect_os_resign() {
  python3 - "$WS" "$KEYS" "$FIRMWARE_DENY_FILE" <<'PY'
import glob, json, os, sys
ws = sys.argv[1]
with open(sys.argv[3], encoding="utf-8") as firmware_file:
    deny = {
        line.strip()
        for line in firmware_file
        if line.strip() and not line.lstrip().startswith("#")
    }
if not deny:
    sys.exit("empty firmware denylist")
parts = []
plan = os.path.join(ws, "signing-plan.json")
if os.path.isfile(plan) and os.path.getsize(plan) > 0:
    try:
        data = json.load(open(plan, encoding="utf-8"))
        parts = list(data.get("resign_partitions") or [])
    except Exception:
        parts = []
if not parts:
    helpers = glob.glob(os.path.expanduser("~/.cache/lenos-single/*/tools/signing_metadata.py"))
    helpers += glob.glob(os.path.expanduser("~/.cache/lenos-single/*/runtime/tools/signing_metadata.py"))
    helpers += [os.path.join(ws, "tools/signing_metadata.py")]
    helper = next((h for h in helpers if os.path.isfile(h)), None)
    if helper and os.path.isfile(plan):
        import subprocess
        r = subprocess.run(["python3", helper, "emit", plan, "resign-partitions"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            parts = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
# Do NOT slurp avbroot_patch.log (tr/mapfile of the whole file kills SSH).
seen, out = set(), []
dropped = []
for p in parts:
    name = p.split("/")[-1].split(".")[0]
    name = name[:-2] if name.endswith("_a") or name.endswith("_b") else name
    if name in deny:
        dropped.append(p)
        continue
    if p and p not in seen and p != "--re-sign":
        seen.add(p)
        out.append(p)
if dropped:
    print("dropped firmware (do not --re-sign): " + " ".join(dropped), file=sys.stderr)
if not out:
    sys.exit(1)
print("\n".join(out))
PY
}

require_root_state() {
  root_enabled || die "root mode is none; set LENOS_ROOT=bakasu or kernelsu"
  [[ -n "$ROOT_STATE_DIR" ]] || die "root state directory is not set"
  need_file "$ROOT_STATE_DIR/init_boot.img"
  need_file "$ROOT_STATE_DIR/root-state.json"
  need_file "$ROOT_STATE_DIR/manager.apk"
}

cmd_root_prepare() {
  root_enabled || die "root is disabled; use LENOS_ROOT=bakasu or kernelsu"
  if [[ -z "$ROOT_LKM" ]]; then
    case "${ROOT_ALLOW_UNVALIDATED_LKM,,}" in
      1|true|yes) ;;
      *)
        die "root needs a kernel module built against this tree's kernel:
    LENOS_ROOT_LKM=/path/to/kernelsu.ko
The pinned module is built for Google's GKI KMI and is not valid for the
hardened lenOS kernel. If you accept the risk anyway, set
LENOS_ALLOW_UNVALIDATED_LKM=1. See docs/root.md."
        ;;
    esac
  fi
  cmd_doctor
  local base
  base="$(select_base_ota)" || exit 1
  info "root mode: $ROOT_MODE"
  info "base OTA:  $base"
  info "state:     $ROOT_STATE_DIR"
  local -a lkm_args=()
  if [[ -n "$ROOT_LKM" ]]; then
    lkm_args+=(--lkm "$ROOT_LKM")
    info "LKM:       $ROOT_LKM (local, must match this kernel)"
  else
    lkm_args+=(--allow-unvalidated-lkm)
    info "LKM:       pinned GKI module (explicitly UNVALIDATED on this kernel)"
  fi
  info "verifying base OTA signature"
  verify_input_ota "$base"
  python3 "$VENDOR/tools/lenos_root.py" prepare \
    --mode "$ROOT_MODE" \
    --base-ota "$base" \
    --state-dir "$ROOT_STATE_DIR" \
    --cache-dir "$ROOT_CACHE" \
    --source "$SRC" \
    --avbroot "$AVBROOT" \
    "${lkm_args[@]}" \
    || die "root-prepare failed"
  cp -f "$ROOT_STATE_DIR/manager.apk" "$WS/lenos-asteroids-$ROOT_MODE-manager.apk"
  chmod 644 "$WS/lenos-asteroids-$ROOT_MODE-manager.apk"
  sha256sum "$WS/lenos-asteroids-$ROOT_MODE-manager.apk" \
    | tee "$WS/lenos-asteroids-$ROOT_MODE-manager.apk.sha256"
  info "manager APK: $WS/lenos-asteroids-$ROOT_MODE-manager.apk"
  info "next: LENOS_ROOT=$ROOT_MODE $0 package"
}

cmd_root_status() {
  if ! root_enabled; then
    info "root: none (rootless); no root state"
    return 0
  fi
  require_root_state
  python3 "$VENDOR/tools/lenos_root.py" status \
    --mode "$ROOT_MODE" \
    --state-dir "$ROOT_STATE_DIR" \
    --avbroot "$AVBROOT"
}

cmd_package() {
  cmd_doctor
  require_boot_verification_tools
  need_file "$FIRMWARE_DENY_FILE"
  need_file "$VENDOR/tools/lenos_root.py"
  local input
  input="$(select_base_ota)" || exit 1
  info "input OTA: $input"
  info "verifying input OTA signature"
  verify_input_ota "$input"

  if root_enabled; then
    require_root_state
    python3 "$VENDOR/tools/lenos_root.py" check-source \
      --mode "$ROOT_MODE" \
      --state-dir "$ROOT_STATE_DIR" \
      --base-ota "$input" \
      --avbroot "$AVBROOT" \
      || die "base OTA does not match the prepared root state; rerun root-prepare"
    python3 "$VENDOR/tools/lenos_root.py" status \
      --mode "$ROOT_MODE" \
      --state-dir "$ROOT_STATE_DIR" \
      --avbroot "$AVBROOT" >/dev/null \
      || die "prepared root state failed its image/manager checks"
    info "root state matches this base OTA: $ROOT_STATE_DIR"
    local lkm_source
    lkm_source="$(python3 - "$ROOT_STATE_DIR/root-state.json" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("lkm_source", "unknown"))
except Exception:
    print("unknown")
PY
)"
    if [[ "$lkm_source" == "pinned-unvalidated" ]]; then
      info "WARNING: this root state uses the pinned GKI LKM, which was not built for this kernel."
    fi
  fi

  local parts_text
  parts_text="$(collect_os_resign)" \
    || die "no OS --re-sign list (need signing-plan.json or signing_metadata.py). do not parse the whole avbroot log."
  mapfile -t PARTS <<< "$parts_text"
  [[ ${#PARTS[@]} -gt 0 ]] || die "empty OS --re-sign list; refusing to patch"
  info "OS re-sign (${#PARTS[@]}): ${PARTS[*]}"
  if root_enabled; then
    local required
    for required in init_boot boot vendor_boot vbmeta; do
      grep -qxF -- "$required" <<< "$parts_text" \
        || die "the signing plan does not re-sign $required; root needs a complete AVB chain"
    done
  fi

  local args=()
  local p
  for p in "${PARTS[@]}"; do
    args+=(--re-sign "$p")
  done
  if root_enabled; then
    args+=(--prepatched "$ROOT_STATE_DIR/init_boot.img")
  else
    args+=(--rootless)
  fi

  rm -f "$OUT.tmp"
  "$AVBROOT" ota patch \
    --input "$input" \
    --key-avb "$KEYS/avb.key" \
    --key-ota "$KEYS/ota.key" \
    --cert-ota "$KEYS/ota.crt" \
    --clear-vbmeta-flags \
    --zip-mode seekable \
    --output "$OUT.tmp" \
    "${args[@]}"

  "$AVBROOT" ota verify \
    --input "$OUT.tmp" \
    --cert-ota "$KEYS/ota.crt" \
    --public-key-avb "$KEYS/avb_pkmd.bin"
  verify_ota_boot_images "$OUT.tmp"
  mv -f "$OUT.tmp" "$OUT"
  chmod 644 "$OUT"
  sha256sum "$OUT" | tee "$OUT.sha256"
  if root_enabled; then
    cp -f "$ROOT_STATE_DIR/manager.apk" "$WS/lenos-asteroids-$ROOT_MODE-manager.apk"
    chmod 644 "$WS/lenos-asteroids-$ROOT_MODE-manager.apk"
    sha256sum "$WS/lenos-asteroids-$ROOT_MODE-manager.apk" \
      | tee "$WS/lenos-asteroids-$ROOT_MODE-manager.apk.sha256"
    info "root manager (install after first boot): $WS/lenos-asteroids-$ROOT_MODE-manager.apk"
  fi
  info "packaged $OUT ($ROOT_MODE)"
  info "next: $0 extract   then copy zip + sha256 + avb_pkmd.bin off the build host"
}

sanitize_fastboot_info() {
  python3 "$VENDOR/tools/sanitize_fastboot_info.py" \
    --deny-file "$FIRMWARE_DENY_FILE" "$1"
}

cmd_extract() {
  cmd_doctor
  require_boot_verification_tools
  need_file "$FIRMWARE_DENY_FILE"
  need_file "$VENDOR/tools/lenos_root.py"
  need_file "$VENDOR/tools/sanitize_fastboot_info.py"
  need_file "$OUT"
  info "verifying $OUT before extract"
  "$AVBROOT" ota verify \
    --input "$OUT" \
    --cert-ota "$KEYS/ota.crt" \
    --public-key-avb "$KEYS/avb_pkmd.bin"
  verify_ota_boot_images "$OUT"
  rm -rf "$EXTRACT_DIR"
  mkdir -p "$EXTRACT_DIR"
  "$AVBROOT" ota extract \
    --input "$OUT" \
    --directory "$EXTRACT_DIR" \
    --fastboot \
    --all
  [[ -s "$EXTRACT_DIR/android-info.txt" ]] \
    || die "extract produced no android-info.txt. do not invent one. abort."
  [[ -s "$EXTRACT_DIR/fastboot-info.txt" ]] \
    || die "extract produced no fastboot-info.txt"
  info "android-info.txt:"
  cat "$EXTRACT_DIR/android-info.txt"
  sanitize_fastboot_info "$EXTRACT_DIR/fastboot-info.txt"
  info "fastboot-info.txt (sanitized):"
  cat "$EXTRACT_DIR/fastboot-info.txt"
  if root_enabled; then
    require_root_state
    python3 "$VENDOR/tools/lenos_root.py" status \
      --mode "$ROOT_MODE" \
      --state-dir "$ROOT_STATE_DIR" \
      --avbroot "$AVBROOT" >/dev/null \
      || die "root manager/state failed verification; rerun root-status"
    need_file "$WS/lenos-asteroids-$ROOT_MODE-manager.apk"
    info "root manager (install after first boot): $WS/lenos-asteroids-$ROOT_MODE-manager.apk"
  fi
  info "extract OK. copy $EXTRACT_DIR and $OUT to the machine that will flash"
}

cmd_flash_plan() {
  local extract_name title="ROOTLESS"
  extract_name="${EXTRACT_DIR##*/}"
  if root_enabled; then title="ROOT ($ROOT_MODE)"; fi
  cat <<EOF
# Flash plan — lenOS 1.0.0-shizuku $title
# This script will not run these. It does not touch the phone.
#
# FORBIDDEN
#   flash partitions one-by-one
#   flash vbmeta before logicals
#   invent android-info.txt
#   flash an unknown or unverified zip
#   flashing lock on a test-key image
#   re-run a sideload that already returned status 0
#   fastboot boot recovery unless your device is known to support it
#   --disable-verity --disable-verification with platform-tools 36
#
# 1. Copy from the build host to the machine that will flash
#    scp "build-host:$OUT" "build-host:$OUT.sha256" ~/lenos/
#    scp -r "build-host:$EXTRACT_DIR" ~/lenos/
#    scp "build-host:$KEYS/avb_pkmd.bin" ~/lenos/
EOF
  if root_enabled; then
    cat <<EOF
#    scp "build-host:$WS/lenos-asteroids-$ROOT_MODE-manager.apk" ~/lenos/
#    scp "build-host:$WS/lenos-asteroids-$ROOT_MODE-manager.apk.sha256" ~/lenos/
EOF
  fi
  cat <<EOF
#
# 2. Gates
#    fastboot --version                 # 35+
#    test -s ~/lenos/$extract_name/android-info.txt
#    grep -i asteroid ~/lenos/$extract_name/android-info.txt
#    # phone must already boot SOME OS (stock or current lenOS). From a brick, use your recovery plan.
#
# 3. From a booting OS → fastbootd (userspace). Bootloader cannot write logicals.
#    adb reboot bootloader
#    fastboot getvar product            # asteroids
#    fastboot getvar unlocked           # yes
#    fastboot reboot fastboot           # MUST end with is-userspace: yes
#    fastboot getvar is-userspace       # yes or STOP
#    fastboot --set-active=a
#
# 4. One command. Do not hand-flash.
#    export ANDROID_PRODUCT_OUT=~/lenos/$extract_name
#    fastboot flashall -w --skip-reboot
#    # -w required when leaving Nothing OS. Skip -w only for same-OS update of this zip.
#
# 5. Do NOT flash avb_custom_key yet. Reboot unlocked.
#    fastboot reboot
#
# 6. After it boots (minutes):
#    adb shell getprop ro.lenos.version          # 1.0.0
#    adb shell getprop ro.boot.veritymode        # enforcing
#    adb shell getprop ro.boot.vbmeta.digest     # record this
#    # OEM unlocking ON. Live with it. Then read lock-gates.
EOF
  if root_enabled; then
    cat <<EOF
#
# 7. Root manager (separate from the OS image; not flashed):
#    adb install -r ~/lenos/lenos-asteroids-$ROOT_MODE-manager.apk
#    open the root manager and grant root when prompted
#    verify the requested root works before installing anything important
EOF
  fi
}

cmd_lock_gates() {
  local root_note
  if ! root_enabled; then
    cat <<EOF
# LOCK GATES — refusing to print a lock sequence for a rootless build.
# Rootless has no root manager, so OEMUnlockOnBoot cannot be installed.
# This script will not run a lock sequence, and you should not lock.
EOF
    return 1
  fi
  root_note="This is a $ROOT_MODE root build. The OTA re-signs init_boot and the OS AVB
# partitions, but this helper does not install or verify a boot-failure recovery
# guard (OEMUnlockOnBoot or equivalent). Root also increases attack surface."
  cat <<EOF
# LOCK GATES — this script will not run a lock command.
# REFERENCE ONLY: locking is unsupported; do not run the steps below.
#
# $root_note
# Locking without a verified recovery guard means: if the phone does not boot
# after lock, OEM unlocking was wiped with /data and you may have no unlock path.
# Slot B now has real _b partitions, which is necessary but not sufficient.
#
# Do not lock unless EVERY line is true:
#   [ ] THIS zip booted UNLOCKED (not a test-key image)
#   [ ] ro.lenos.version = 1.0.0
#   [ ] ro.boot.veritymode = enforcing
#   [ ] ro.boot.vbmeta.digest matches 'avbroot ota verify' of THIS zip
#   [ ] fastboot getvar has-slot:init_boot  / vendor_boot / vbmeta  → yes
#   [ ] fastboot getvar slot-unbootable:b → no
#   [ ] OEM unlocking is ON
#   [ ] you have avb.key / ota.key in >= 2 offline places
#   [ ] you accept that a failed boot after lock may be unrecoverable
#
# Even if every line above were true, this helper still does not support
# locking and will not print a lock sequence. The manual steps in
# docs/flash-and-lock.md are reference-only; do not run them from this helper.
# Locking without a recovery guard can make a failed boot unrecoverable.
#
# After lock: yellow custom-key warning is expected.
# OEM unlocking ON forever. Never sideload an unpatched OTA.
EOF
  return 1
}

main() {
  local cmd cli_root="" cli_root_set=0 args=()
  while (($#)); do
    case "$1" in
      --root)
        (($# >= 2)) || die "--root requires none, bakasu, or kernelsu"
        cli_root="$2"
        cli_root_set=1
        shift 2
        ;;
      --root=*)
        cli_root="${1#*=}"
        cli_root_set=1
        shift
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done
  if ((cli_root_set)); then
    LENOS_ROOT="$cli_root"
  fi
  resolve_root_mode
  set -- "${args[@]}"
  cmd="${1:-}"
  shift || true
  case "$cmd" in
    doctor)      cmd_doctor "$@";;
    apply)       cmd_apply "$@";;
    hardwire)    cmd_apply "$@";;   # legacy name, same strict path
    build)       cmd_build "$@";;
    root-prepare) cmd_root_prepare "$@";;
    root-status) cmd_root_status "$@";;
    package)     cmd_package "$@";;
    extract)     cmd_extract "$@";;
    flash-plan)  cmd_flash_plan "$@";;
    lock-gates)  cmd_lock_gates "$@";;
    -h|--help|help|"") usage;;
    lock|flash|sideload)
      die "refusing '$cmd'. this script never talks to the phone. see flash-plan / lock-gates / the guide."
      ;;
    *) die "unknown command: $cmd";;
  esac
}

main "$@"
