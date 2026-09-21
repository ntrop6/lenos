#!/usr/bin/env bash
# lenOS 1.0 build pipeline for Nothing Phone (3a)/(3a Pro) "asteroids".
#
#   ./build/lenos.sh doctor                     install deps, check disk
#   ./build/lenos.sh sync                       repo init/sync (pinned manifest)
#   ./build/lenos.sh integrate --profile full   apply patches + vendor files
#   ./build/lenos.sh build                      breakfast + m bacon
#   ./build/lenos.sh keys                       generate AVB/OTA keys
#   ./build/lenos.sh resukisu-prepare           phone-assisted LKM init_boot patch
#   ./build/lenos.sh package --root resukisu    sign, inject root, re-sign AVB
#   ./build/lenos.sh verify                     verify final OTA + feature audit
#
# Everything lands in $LENOS_WORKSPACE (default: repo dir /workspace).
# Back up the key directory before flashing; losing it after relock
# permanently bricks the device.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(dirname "$SCRIPT_DIR")"
# shellcheck source=/dev/null
source "$ROOT/config/VERSIONS.sh"

WORKSPACE="${LENOS_WORKSPACE:-$ROOT/workspace}"
TREE="$WORKSPACE/lineage"
KEYS="$WORKSPACE/keys"
LOGS="$WORKSPACE/logs"
STATE="$WORKSPACE/state"
BIN="$WORKSPACE/bin"

DEVICE="$DEVICE_CODENAME"
PROFILE="full"
ROOT_MODE="resukisu"
VARIANT="${LENOS_VARIANT:-userdebug}"
AVBROOT_BIN="$BIN/avbroot"

info() { printf '[lenos] %s\n' "$*"; }
ok()   { printf '[lenos] OK: %s\n' "$*"; }
warn() { printf '[lenos] WARN: %s\n' "$*"; }
die()  { printf '[lenos] ERROR: %s\n' "$*" >&2; exit 1; }

sha256_file() { sha256sum "$1" | awk '{print $1}'; }
mark_done() { mkdir -p "$STATE"; printf '%s\n' "$(date -u +%FT%TZ)" >"$STATE/$1.done"; }
is_done() { [[ -s "$STATE/$1.done" ]]; }

download_pinned() {
    # download_pinned <url> <sha256> <dest>
    local url="$1" want="$2" dest="$3" actual
    if [[ -s "$dest" ]]; then
        actual=$(sha256_file "$dest")
        [[ "$actual" == "$want" ]] && { ok "cached: $dest"; return 0; }
    fi
    mkdir -p "$(dirname "$dest")"
    local tmp; tmp=$(mktemp "$dest.tmp.XXXXXX")
    curl -fL --retry 3 --connect-timeout 20 -o "$tmp" "$url"
    actual=$(sha256_file "$tmp")
    [[ "$actual" == "$want" ]] \
        || { rm -f "$tmp"; die "checksum mismatch for $url ($actual != $want)"; }
    mv "$tmp" "$dest"
    ok "fetched and pinned: $dest"
}

# ---------------------------------------------------------------- doctor ---
cmd_doctor() {
    local deps=(git git-lfs python3 curl unzip openssl cpio flock file sha256sum
                awk sed grep find stat realpath adb fastboot)
    local missing=()
    for c in "${deps[@]}"; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
    if ! command -v repo >/dev/null 2>&1; then
        info "installing repo launcher to $BIN"
        mkdir -p "$BIN"
        curl -fL --retry 3 \
            -o "$BIN/repo" https://storage.googleapis.com/git-repo-downloads/repo
        chmod 755 "$BIN/repo"
    fi
    if ((${#missing[@]} > 0)); then
        warn "missing commands: ${missing[*]}"
        cat <<'EOF'
Install the full dependency set (Ubuntu 24.04):

  sudo apt update && sudo apt install -y \
    git git-lfs python3 curl unzip openssl cpio ccache bc bison build-essential \
    ca-certificates device-tree-compiler dwarves file flex g++-multilib \
    gcc-multilib gperf imagemagick kmod lib32readline-dev lib32z1-dev \
    libc6-dev-i386 libdw-dev libelf-dev libgl1-mesa-dev libgnutls28-dev \
    liblz4-tool libncurses-dev libsdl1.2-dev libssl-dev libxml2 \
    libxml2-utils lz4 lzop patchelf pngcrush protobuf-compiler python3-jinja2 \
    python3-protobuf python-is-python3 rsync schedtool squashfs-tools \
    x11proto-dev libx11-dev xsltproc xxd zip zlib1g-dev zstd \
    android-sdk-platform-tools-common openjdk-21-jdk
EOF
        exit 1
    fi
    local free_gb
    free_gb=$(df --output=avail -BG "$WORKSPACE" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)
    ((free_gb >= 420)) \
        || die "only ${free_gb}GB free at $WORKSPACE; a full tree + out/ needs ~450GB"
    ok "host dependencies present; ${free_gb}GB free"
}

# ------------------------------------------------------------------- sync ---
cmd_sync() {
    mkdir -p "$TREE" "$LOGS" "$STATE"
    if [[ ! -d "$TREE/.repo" ]]; then
        (
            cd "$TREE"
            "$BIN/repo" init -q \
                -u https://github.com/LineageOS/android.git -b "$LINEAGE_BRANCH" \
                --git-lfs --repo-url=https://gerrit.googlesource.com/git-repo
        )
    fi
    mkdir -p "$TREE/.repo/local_manifests"
    install -m 644 "$ROOT/manifest/lenos-asteroids.xml" "$TREE/.repo/local_manifests/lenos.xml"
    info "syncing (this downloads ~200GB and takes a while)..."
    (
        cd "$TREE"
        "$BIN/repo" sync -c -j"$(nproc)" --no-clone-bundle --no-tags --prune --optimized-fetch \
            2>&1 | tee "$LOGS/repo-sync.log" | tail -5 || true
    )
    (
        cd "$TREE"
        "$BIN/repo" manifest -r -o "$LOGS/pinned-manifest.xml"
    )
    verify_pins
    mark_done sync
    ok "source synced; exact revisions recorded in $LOGS/pinned-manifest.xml"
}

verify_pins() {
    # Every repo the patch set touches must be at its pinned revision.
    local pairs=(
        "device/nothing/asteroids:53d7b7e554823155e1d2ceb31cd1e64dc31dfe17"
        "kernel/nothing/sm7635:1b6d6d95170e5f36a532430c8e74b3b1fb139cdb"
        "kernel/nothing/sm7635-modules:4366a514a7ddf1079ec8c60b1d20238fa5573e13"
        "kernel/nothing/sm7635-devicetrees:e0eb1dc2235850f9f966bfb3294967d06c00a0f1"
        "vendor/nothing/asteroids:dec51e71456a55af3f5a4d4744c3e2aab726afc4"
        "packages/apps/ParanoidGlyph:1bdc1cf90e475e7030bad5aa3fe313bba3abae4f"
        "packages/apps/GlyphAdapter:d15021d86dfd5e054dade0683bd51c8f9a501f7f"
        "hardware/dolby:f66b08f3ee8c67a44f292d7edb68d5fbfb2172ed"
        "hardware/nothing:09a3ca569fb0ea9b12f2f29107ff06da0009192c"
        "frameworks/base:c8e9a4a21efb16c923371a740b9c1c755d17ebb2"
        "frameworks/native:9568531f9be7ae65f260699811f32ec4e461de6e"
        "frameworks/opt/telephony:566e62daf4e93be6f934001bc76d60aba087b4d6"
        "system/core:0e96ff13d90df568ddd788bb02b3ddb6e3641528"
        "system/sepolicy:885cc500f6078a766d1f6def5ce4c06c55841773"
        "packages/modules/Permission:ee30155a8872cd022b5b7fb1983fdcf09e752723"
        "packages/modules/Wifi:8e08d5bf50bb82fa66aab3d1e9e224dd2489955f"
        "packages/apps/Settings:ecbe1adc3e207d8dc38c35571171ba9d886092f6"
        "packages/modules/NetworkStack:853cb402bf02cd935d06d42c1155b0023eabd3e6"
        "frameworks/opt/net/wifi:e7e8646a896f2ee736ccca935c862d52f0492b07"
    )
    local p sha
    for pair in "${pairs[@]}"; do
        p="${pair%%:*}"; sha="${pair##*:}"
        [[ -d "$TREE/$p/.git" ]] || die "missing repo: $p (run sync)"
        local head; head=$(git -C "$TREE/$p" rev-parse HEAD 2>/dev/null || true)
        [[ "$head" == "$sha" ]] \
            || die "$p is at $head, expected pin $sha. Re-run: $0 sync"
    done
    ok "all 19 pinned repositories verified at their manifest revisions"
}

# ------------------------------------------------------------- integrate ---
patch_repo() {
    # Map a patch file name to its repository.
    case "$1" in
        0001-frameworks-base-*) echo frameworks/base ;;
        0002-frameworks-native-*) echo frameworks/native ;;
        0003-permissioncontroller-*) echo packages/modules/Permission ;;
        0004-frameworks-base-*) echo frameworks/base ;;
        0005-settings-*) echo packages/apps/Settings ;;
        0006-frameworks-base-*) echo frameworks/base ;;
        0007-frameworks-opt-telephony-*) echo frameworks/opt/telephony ;;
        0008-system-core-*) echo system/core ;;
        0009-system-sepolicy-*) echo system/sepolicy ;;
        0010-wifi-*) echo packages/modules/Wifi ;;
        0011-networkstack-*) echo packages/modules/NetworkStack ;;
        0012-wifitracker-*) echo frameworks/opt/net/wifi ;;
        0013-settings-*) echo packages/apps/Settings ;;
        0014-settings-*) echo packages/apps/Settings ;;
        0015-screenshot-*) echo frameworks/base ;;
        *) die "unknown patch: $1" ;;
    esac
}

cmd_integrate() {
    is_done sync || die "run '$0 sync' first"
    [[ -d "$TREE/device/nothing/$DEVICE" ]] || die "tree incomplete; re-run sync"

    local profile="${1:-$PROFILE}"
    case "$profile" in standard|full|strict|none) ;; *) die "profile: standard|full|strict|none" ;; esac
    info "integrate profile: $profile"

    # Patched repositories must be clean before anything is applied.
    local dev="$TREE/device/nothing/$DEVICE"
    local base=53d7b7e554823155e1d2ceb31cd1e64dc31dfe17
    local repos=(
        "$dev" "$TREE/frameworks/base" "$TREE/frameworks/native"
        "$TREE/packages/modules/Permission" "$TREE/packages/apps/Settings"
        "$TREE/frameworks/opt/telephony" "$TREE/system/core" "$TREE/system/sepolicy"
        "$TREE/packages/modules/Wifi" "$TREE/packages/modules/NetworkStack"
        "$TREE/frameworks/opt/net/wifi"
    )
    local r
    for r in "${repos[@]}"; do
        if [[ -n "$(git -C "$r" status --porcelain 2>/dev/null)" ]]; then
            die "working tree not clean: $r (lenOS refuses to build on top of unknown edits)"
        fi
    done

    # Device patches: replay the four lenOS commits on top of the pinned base.
    git -C "$dev" reset --hard "$base"
    for p in "$ROOT"/device-patches/*.patch; do
        git -c user.name=lenOS -c user.email=lenos@lenos.invalid \
            -C "$dev" am --quiet "$p" \
            || die "device patch failed: $(basename "$p") (tree left at $base)"
    done
    ok "device patches applied ($(ls "$ROOT"/device-patches/*.patch | wc -l) commits)"

    # Framework patches: plain git apply with applied/absent/conflict states.
    local want_from=1 want_to=15
    case "$profile" in
        none)    want_from=0; want_to=0 ;;
        standard) want_from=4 ;;
    esac
    local f num repo n=0
    for f in "$ROOT"/patches/0*.patch; do
        num=$(basename "$f" | cut -d- -f1 | tr -d '0' ); num=$((10#$num))
        if ((num < want_from || num > want_to)); then continue; fi
        repo=$(patch_repo "$(basename "$f")")
        if git -C "$TREE/$repo" apply -R --check "$f" >/dev/null 2>&1; then
            ok "already applied: $(basename "$f")"
        elif git -C "$TREE/$repo" apply --check "$f" >/dev/null 2>&1; then
            git -C "$TREE/$repo" apply "$f"
            ((++n))
            ok "applied: $(basename "$f") -> $repo"
        else
            die "patch conflicts with tree: $(basename "$f") in $repo (no reset performed)"
        fi
    done
    info "framework patches newly applied: $n"

    # Vendored runtime files.
    rm -rf "$TREE/vendor/lenos"
    cp -a "$ROOT/vendor/lenos" "$TREE/vendor/lenos"
    rm -f "$TREE/vendor/lenos/bootanimation/bootanimation.zip" 2>/dev/null || true

    # Kernel hardening fragment (content selected by profile).
    local frag="$TREE/kernel/nothing/sm7635/arch/arm64/configs/vendor/lenos_hardening.config"
    mkdir -p "$(dirname "$frag")"
    case "$profile" in
        none)    : >"$frag" ;;
        standard|full)
            printf '%s\n' \
                "CONFIG_BPF_UNPRIV_DEFAULT_OFF=y" \
                "CONFIG_RANDOMIZE_KSTACK_OFFSET_DEFAULT=y" \
                "CONFIG_LIST_HARDENED=y" >"$frag" ;;
        strict)
            printf '%s\n' \
                "CONFIG_BPF_UNPRIV_DEFAULT_OFF=y" \
                "CONFIG_RANDOMIZE_KSTACK_OFFSET_DEFAULT=y" \
                "CONFIG_LIST_HARDENED=y" \
                "CONFIG_INIT_ON_FREE_DEFAULT_ON=y" \
                "CONFIG_ZERO_CALL_USED_REGS=y" >"$frag" ;;
    esac
    ok "kernel fragment: $frag"

    # Boot animation.
    if [[ "$profile" != none ]]; then
        python3 "$ROOT/tools/make-bootanimation.py" \
            -o "$TREE/vendor/lenos/bootanimation/bootanimation.zip"
    fi

    # Pinned Cromite browser.
    if [[ "${LENOS_NO_CROMITE:-0}" != "1" ]]; then
        "$ROOT/tools/fetch-cromite.sh"
    fi

    printf '%s\n' "$profile" >"$STATE/profile"
    mark_done integrate
    ok "integrate complete (profile: $profile)"
}

# ------------------------------------------------------------------ build ---
cmd_build() {
    is_done integrate || die "run '$0 integrate' first"
    info "building (this takes 1-3 h on a 16-32 vCPU host)..."
    (
        cd "$TREE"
        # envsetup probes unset variables deliberately.
        set +u
        . build/envsetup.sh
        set -u
        breakfast "lenos_asteroids" "$VARIANT"
        m bacon 2>&1 | tee "$LOGS/build.log" | tail -3
    )
    local tf
    tf=$(find "$TREE/out/target/product/$DEVICE/obj/PACKAGING/target_files_intermediates" \
            -name "*-target_files*.zip" -type f -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -d' ' -f2)
    [[ -n "$tf" && -s "$tf" ]] || die "no target-files produced; check $LOGS/build.log"
    printf '%s\n' "$tf" >"$STATE/target-files.path"
    printf '%s\n' "$(sha256_file "$tf")" >"$STATE/target-files.sha256"
    mark_done build
    ok "target-files: $tf"
    ok "sha256: $(sha256_file "$tf")"
}

# ------------------------------------------------------------------- keys ---
cmd_keys() {
    mkdir -p "$KEYS"
    # AVB key (PEM private; avbroot derives the public part).
    if [[ ! -s "$KEYS/avb.pem" ]]; then
        openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \
            -out "$KEYS/avb.pem" 2>/dev/null
        ok "generated AVB key: $KEYS/avb.pem"
    fi
    # AVB public key in the bootloader blob form (PKMD). Both avbroot's
    # --public-key-avb and `fastboot flash avb_custom_key` require this
    # binary form; an OpenSSL SPKI PEM does not parse (verified with the
    # pinned avbroot: "Failed to decode public key as AVB format").
    if [[ ! -s "$KEYS/avb.pkmd.bin" || "$KEYS/avb.pkmd.bin" -ot "$KEYS/avb.pem" ]]; then
        "$AVBROOT_BIN" key encode-avb --key "$KEYS/avb.pem" \
            --output "$KEYS/avb.pkmd.bin"
        ok "encoded AVB public key blob: $KEYS/avb.pkmd.bin"
    fi
    # OTA signing key: avbroot loads --key-ota as PEM only (a PKCS#8 DER
    # .pk8 fails key-load before the input is even opened — verified with
    # the pinned avbroot). The pk8 form is only consumed by releasetools,
    # which uses the per-package keys, never this one.
    if [[ ! -s "$KEYS/ota.pem" || ! -s "$KEYS/ota.x509.pem" ]]; then
        local t; t=$(mktemp -d)
        openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "$t/k.pem" 2>/dev/null
        openssl req -new -x509 -sha256 -days 10000 -key "$t/k.pem" \
            -subj "/CN=lenOS OTA key/" -out "$t/c.pem" 2>/dev/null
        install -m 600 "$t/k.pem" "$KEYS/ota.pem"
        install -m 644 "$t/c.pem" "$KEYS/ota.x509.pem"
        rm -rf "$t"
        ok "generated OTA key: $KEYS/ota.pem + $KEYS/ota.x509.pem"
    fi
    chmod 700 "$KEYS"
    warn "BACK UP $KEYS NOW (offline, never a cloud account)."
    warn "A relocked device without its AVB key is unrecoverable."
    ok "keys: $KEYS"
}

# ------------------------------------------------------- resukisu-prepare ---
init_boot_ramdisk_check() {
    # $1 = image, $2 = stock|resukisu — reuses avbroot cpio tooling.
    # avbroot's --output-* flags are path PREFIXES relative to the process
    # CWD (boot.toml defaults there too), so the unpack must run inside the
    # temp directory or this check never finds the ramdisk.
    local img="$1" mode="$2" t
    t=$(mktemp -d "$WORKSPACE/.initboot-check.XXXXXX")
    (
        cd "$t"
        "$AVBROOT_BIN" boot unpack --input "$img" --no-output-kernel \
            --no-output-second --no-output-recovery-dtbo --no-output-dtb \
            --no-output-bootconfig --output-ramdisk-prefix ramdisk.img. --quiet >/dev/null
    )
    local ramdisk
    ramdisk=$(find "$t" -maxdepth 1 -type f -name 'ramdisk.img.*' | sort | head -1)
    [[ -n "$ramdisk" ]] || { rm -rf "$t"; die "no ramdisk in $img"; }
    "$AVBROOT_BIN" cpio unpack --input "$ramdisk" \
        --output-info "$t/cpio.toml" --output-tree "$t/tree" --quiet >/dev/null
    if [[ "$mode" == resukisu ]]; then
        grep -q 'path = "init.real"' "$t/cpio.toml" \
            || { rm -rf "$t"; die "patched init_boot missing init.real"; }
        grep -q 'path = "kernelsu.ko"' "$t/cpio.toml" \
            || { rm -rf "$t"; die "patched init_boot missing kernelsu.ko"; }
    fi
    rm -rf "$t"
    ok "init_boot ramdisk verified: $mode"
}

cmd_resukisu_prepare() {
    is_done package || true
    [[ -s "$OUT_BASE_OTA" ]] || die "base signed OTA missing; run '$0 package' first"
    local apk="$WORKSPACE/prebuilts/$RESUKISU_APK_NAME"
    download_pinned "$RESUKISU_APK_URL" "$RESUKISU_APK_SHA256" "$apk"
    command -v adb >/dev/null 2>&1 || die "adb required"
    adb get-state >/dev/null 2>&1 || die "connect the phone with USB debugging enabled"
    [[ "$(adb shell getprop ro.product.device 2>/dev/null | tr -d '\r\n')" == "$DEVICE" ]] \
        || die "connected device is not $DEVICE"

    local prep="$WORKSPACE/resukisu"
    rm -rf "$prep"; mkdir -p "$prep"
    "$AVBROOT_BIN" ota extract --input "$OUT_BASE_OTA" --directory "$prep" \
        --partition init_boot >/dev/null
    local src="$prep/init_boot.img"
    init_boot_ramdisk_check "$src" stock
    printf '%s\n' "$(sha256_file "$src")" >"$STATE/resukisu-source-init.sha256"

    unzip -p "$apk" lib/arm64-v8a/libksud.so >"$prep/ksud"
    chmod 755 "$prep/ksud"
    adb push "$prep/ksud" /data/local/tmp/lenos-ksud >/dev/null
    adb push "$src" /data/local/tmp/lenos-init_boot.img >/dev/null
    info "patching init_boot with ReSukiSU ksud (KMI $RESUKISU_KMI) on-device..."
    adb shell "chmod 755 /data/local/tmp/lenos-ksud && /data/local/tmp/lenos-ksud boot-patch \
        -b /data/local/tmp/lenos-init_boot.img --kmi $RESUKISU_KMI \
        --partition init_boot -o /data/local/tmp --out-name lenos-resukisu-init_boot.img"
    adb pull /data/local/tmp/lenos-resukisu-init_boot.img \
        "$STATE/resukisu-init_boot.img" >/dev/null
    init_boot_ramdisk_check "$STATE/resukisu-init_boot.img" resukisu
    printf '%s\n' "$(sha256_file "$STATE/resukisu-init_boot.img")" \
        >"$STATE/resukisu-init_boot.sha256"
    ok "patched init_boot: $STATE/resukisu-init_boot.img"
}

# ---------------------------------------------------------------- package ---
cmd_package() {
    is_done build || die "run '$0 build' first"
    [[ -s "$KEYS/avb.pem" ]] || die "run '$0 keys' first"
    local tf; tf=$(cat "$STATE/target-files.path")
    [[ -s "$tf" ]] || die "recorded target-files missing; rebuild"
    [[ "$(sha256_file "$tf")" == "$(cat "$STATE/target-files.sha256")" ]] \
        || die "target-files changed after build; rebuild"

    local plan="$WORKSPACE/signing-plan.json"
    python3 "$ROOT/tools/signing_metadata.py" inspect "$tf" --output "$plan"

    # Generate per-package and per-APEX keys exactly as the plan demands.
    local id out
    out=$(python3 "$ROOT/tools/signing_metadata.py" emit "$plan" package-ids)
    while IFS= read -r id; do
        [[ -n "$id" ]] || continue
        gen_android_key "$KEYS/packages/$id" 2048 "lenOS package $id" 0
    done <<<"$out"
    out=$(python3 "$ROOT/tools/signing_metadata.py" emit "$plan" apex-mappings)
    while IFS=$'\t' read -r _ name; do
        [[ -n "$name" ]] || continue
        gen_android_key "$KEYS/apex/$name" 4096 "lenOS apex $name" 1
    done <<<"$out"

    OUT_BASE_OTA="$WORKSPACE/base-signed-ota.zip"
    LENOS_TREE="$TREE" TARGET_FILES="$tf" LENOS_KEYS="$KEYS" \
    SIGNING_PLAN="$plan" OUT_DIR="$WORKSPACE" BUILD_VARIANT="$VARIANT" \
        bash "$ROOT/tools/sign_target_files.sh" 2>&1 | tee "$LOGS/sign.log" | tail -5
    [[ -s "$OUT_BASE_OTA" ]] || die "release signing failed; see $LOGS/sign.log"
    "$AVBROOT_BIN" ota verify --input "$OUT_BASE_OTA" \
        --cert-ota "$KEYS/packages/releasekey.x509.pem"
    ok "base signed OTA verified"

    local final="$WORKSPACE/lenos-$DEVICE-$ROOT_MODE.zip"
    local patch_args=(
        ota patch --input "$OUT_BASE_OTA"
        --key-avb "$KEYS/avb.pem"
        --key-ota "$KEYS/ota.pem" --cert-ota "$KEYS/ota.x509.pem"
        --clear-vbmeta-flags --zip-mode seekable
        --output "${final}.tmp"
    )
    case "$ROOT_MODE" in
        resukisu)
            [[ -s "$STATE/resukisu-init_boot.img" ]] \
                || die "run '$0 resukisu-prepare' first (needs the phone once)"
            patch_args+=(--prepatched "$STATE/resukisu-init_boot.img") ;;
        none) patch_args+=(--rootless) ;;
        *) die "root mode: resukisu|none" ;;
    esac
    local part
    while IFS= read -r part; do
        [[ -n "$part" ]] || continue
        patch_args+=(--re-sign "$part")
    done < <(python3 "$ROOT/tools/signing_metadata.py" emit "$plan" resign-partitions)
    "$AVBROOT_BIN" "${patch_args[@]}"
    mv -f "${final}.tmp" "$final"
    printf '%s\n' "$ROOT_MODE" >"$STATE/root-mode"
    printf '%s\n' "$final" >"$STATE/final-ota.path"
    printf '%s  %s\n' "$(sha256_file "$final")" "$(basename "$final")" >"$final.sha256"
    {
        echo "lenOS: $LENOS_VERSION"
        echo "device: $DEVICE / $LINEAGE_BRANCH / profile $(cat "$STATE/profile" 2>/dev/null || echo '?')"
        echo "root mode: $ROOT_MODE"
        echo "final OTA: $final"
        echo "final OTA sha256: $(sha256_file "$final")"
        echo "target-files sha256: $(cat "$STATE/target-files.sha256")"
        echo "resukisu init_boot sha256: $(cat "$STATE/resukisu-init_boot.sha256" 2>/dev/null || echo n/a)"
        echo "avb public key (PKMD) sha256: $(sha256_file "$KEYS/avb.pkmd.bin")"
        echo "ota cert sha256: $(sha256_file "$KEYS/ota.x509.pem")"
        echo "built at (UTC): $(date -u +%FT%TZ)"
    } >"$WORKSPACE/release-info.txt"
    mark_done package
    ok "final OTA: $final"
    warn "Back up $KEYS before installing anything."
}

gen_android_key() {
    # Reused from the audited lenOS 2.8.1 wizard (MIT): pk8 + x509 (+pem).
    local base="$1" bits="$2" cn="$3" keep_pem="$4"
    local pk8="$base.pk8" cert="$base.x509.pem" pem="$base.pem"
    if [[ -s "$pk8" && -s "$cert" && ( "$keep_pem" != 1 || -s "$pem" ) ]]; then
        return 0
    fi
    if [[ -e "$pk8" || -e "$cert" || -e "$pem" ]]; then
        die "partial key set at $base; resolve manually (refusing to mix identities)"
    fi
    mkdir -p "$(dirname "$base")"
    local t; t=$(mktemp -d)
    openssl genpkey -algorithm RSA -pkeyopt "rsa_keygen_bits:$bits" -out "$t/k.pem" 2>/dev/null
    openssl req -new -x509 -sha256 -days 10000 -key "$t/k.pem" \
        -subj "/CN=$cn/" -out "$t/c.pem" 2>/dev/null
    openssl pkcs8 -topk8 -inform PEM -outform DER -nocrypt \
        -in "$t/k.pem" -out "$t/k.pk8" 2>/dev/null
    install -m 600 "$t/k.pk8" "$pk8"
    install -m 644 "$t/c.pem" "$cert"
    [[ "$keep_pem" == 1 ]] && install -m 600 "$t/k.pem" "$pem"
    rm -rf "$t"
    ok "generated key: $base"
}

# ----------------------------------------------------------------- verify ---
cmd_verify() {
    [[ -s "$STATE/final-ota.path" ]] || die "no final OTA; run package"
    local final; final=$(cat "$STATE/final-ota.path")
    "$AVBROOT_BIN" ota verify --input "$final" \
        --cert-ota "$KEYS/ota.x509.pem" --public-key-avb "$KEYS/avb.pkmd.bin"
    ok "avbroot verifies the final OTA against your keys"

    python3 - "$final" "$STATE/root-mode" <<'PY'
import sys, zipfile
ota, root_mode = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(ota) as z:
    names = set(z.namelist())
    missing = [p for p in ("META-INF/com/android/metadata",) if p not in names]
    if missing:
        raise SystemExit("final OTA missing: " + ", ".join(missing))
    meta = z.read("META-INF/com/android/metadata").decode()
    fp = next((l.split("=",1)[1] for l in meta.splitlines()
               if l.startswith("post-build=")), "")
    print("post-build:", fp)
print("final OTA metadata verified")
PY
    ok "verify complete — follow README 'Flashing and relocking' next"
}

# ------------------------------------------------------------------ entry ---
OUT_BASE_OTA="$WORKSPACE/base-signed-ota.zip"

cmd_status() {
    for s in sync integrate build package; do
        printf '%-12s %s\n' "$s" "$(is_done "$s" && cat "$STATE/$s.done" || echo pending)"
    done
    [[ -s "$STATE/final-ota.path" ]] && info "OTA: $(cat "$STATE/final-ota.path")"
}

mkdir -p "$WORKSPACE" "$LOGS" "$STATE" "$BIN"
case "${1:-}" in
    doctor) cmd_doctor ;;
    sync) cmd_sync ;;
    integrate) shift || true; cmd_integrate "${1:-}" ;;
    build) cmd_build ;;
    keys) cmd_keys ;;
    resukisu-prepare) cmd_resukisu_prepare ;;
    package) shift || true
        case "${1:-}" in
            --root) ROOT_MODE="${2:-}"; shift 2 || exit 2 ;;
        esac
        cmd_package ;;
    verify) cmd_verify ;;
    status) cmd_status ;;
    *)
        sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'
        echo
        echo "usage: $0 <command> [args]"
        echo "  package --root resukisu|none"
        exit 2 ;;
esac
