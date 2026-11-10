#!/usr/bin/env bash
#
# Read-only experimental-feature checks over adb.
#
# This script never flashes, wipes, relocks, reboots, force-stops, writes a
# setting or changes a permission. It only reads properties, settings, package
# paths and dumpsys output.
#
# Usage:
#   tools/verify-device.sh
#   ANDROID_SERIAL=... tools/verify-device.sh
#
set -u

ADB="${ADB:-adb}"
if ! command -v "$ADB" >/dev/null 2>&1; then
    printf 'FAIL: adb not found: %s\n' "$ADB" >&2
    exit 1
fi

state="$("$ADB" get-state 2>&1)" || {
    printf 'FAIL: adb device is not ready:\n%s\n' "$state" >&2
    exit 1
}
if [ "$state" != "device" ]; then
    printf 'FAIL: adb state is %s, expected device\n' "$state" >&2
    exit 1
fi

printf 'lenOS experimental read-only device check\n\n'

prop() {
    local label="$1"
    local key="$2"
    local value
    value="$("$ADB" shell getprop "$key" 2>/dev/null | tr -d '\r')"
    printf '%-32s %s\n' "$label" "${value:-<unset>}"
}

setting() {
    local label="$1"
    local key="$2"
    local value
    value="$("$ADB" shell settings get secure "$key" 2>/dev/null | tr -d '\r')"
    printf '%-32s %s\n' "$label" "${value:-<unset>}"
}

printf 'Identity and boot:\n'
prop "device" ro.product.device
prop "build type" ro.build.type
prop "Android release" ro.build.version.release
prop "verified boot state" ro.boot.verifiedbootstate
prop "bootloader locked" ro.boot.flash.locked
prop "USB port mode" persist.security.usb_mode
prop "hardened thread stacks" ro.lenos.hardened_thread_stacks

printf '\nlenOS feature settings (read only):\n'
setting "clipboard screen-off clear" clipboard_clear_on_screen_off
setting "native debugging block" block_native_debugging

printf '\nPackage paths:\n'
for pkg in org.lenos.opsec com.android.settings com.stevesoltys.seedvault; do
    path="$("$ADB" shell pm path "$pkg" 2>/dev/null | tr -d '\r' | head -n 1)"
    printf '%-32s %s\n' "$pkg" "${path:-<not installed>}"
done

printf '\nUSB ports:\n'
"$ADB" shell dumpsys usb 2>/dev/null | tr -d '\r' \
    | grep -E -i 'port|enableUsbData|mode' | head -n 20 || true

printf '\nKernel hardening:\n'
dmesg_restrict="$("$ADB" shell cat /proc/sys/kernel/dmesg_restrict 2>/dev/null | tr -d '\r')"
printf '%-32s %s\n' "kernel.dmesg_restrict" "${dmesg_restrict:-<unreadable>}"
config="$("$ADB" shell test -r /proc/config.gz && echo present || echo absent)"
printf '%-32s %s\n' "/proc/config.gz" "$config"

printf '\nOPSEC app network permission check:\n'
if "$ADB" shell pm path org.lenos.opsec >/dev/null 2>&1; then
    if "$ADB" shell dumpsys package org.lenos.opsec 2>/dev/null \
            | grep -q 'android.permission.INTERNET'; then
        printf 'WARN: LenosOpsec declares INTERNET\n'
    else
        printf 'ok:   no INTERNET declaration observed\n'
    fi
else
    printf 'WARN: LenosOpsec is not installed\n'
fi

printf '\nNOTE: this script made no changes. Behavioral checks that need a\n'
printf 'cable, a lock transition, a trace attempt or a boot cycle are in\n'
printf 'experimental/docs/verification.md and must be run with a recovery plan.\n'
