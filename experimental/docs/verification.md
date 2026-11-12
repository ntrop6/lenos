# Verification checklist (after the first build)

Nothing in this repository has been built or booted. Run these checks only in a build window that
follows [`../../docs/flash-and-lock.md`](../../docs/flash-and-lock.md); flashing needs explicit
approval.

## Build-time

1. From the main `vendor/lenos` checkout, apply the **stable series first** and the
   experimental series second, with the opt-in flag:

   ```bash
   LENOS_EXPERIMENTAL=1 ./lenos-1.0-shizuku.sh apply
   ```

   This applies `patches/` then `patches-experimental/`, installs
   `experimental/app/LenosOpsec` into the build tree, adds the HTS-1 property,
   and exports the flag. For a manual `mka` invocation, pass
   `LENOS_EXPERIMENTAL=1` yourself.
2. Build the full `asteroids` product. `config/lenos-experimental.mk` adds `LenosOpsec` to
   `PRODUCT_PACKAGES` only under that flag; confirm it is in the build graph:
   ```bash
   adb shell pm path org.lenos.opsec
   adb shell cmd package resolve-activity --brief \
       -a android.intent.action.SEND -t image/jpeg
   ```
3. Confirm `PackageVerityExt`, `ClipboardPrivacySettings`, `NativeDebuggingBlock` and `LenosOpsec`
   are compiled (inspect the build log for the paths).
4. Confirm no `neverallow` or hidden-API failure was introduced. The brand-new framework APIs are
   `@hide`; Settings and `LenosOpsec` are platform apps. The clipboard and native-debugging patches
   must not require sepolicy changes.
5. Check the experimental product does not include a browser or network code from `LenosOpsec`:
   `adb shell dumpsys package org.lenos.opsec | grep -i internet` must be empty.
6. Run the read-only helpers before manual testing:
   ```bash
   OUT="out/target/product/asteroids" tools/verify-build.sh
   ANDROID_SERIAL=... tools/verify-device.sh
   ```
   `verify-build.sh` only checks artifacts; `verify-device.sh` only reads properties/settings and
   never writes, flashes, reboots or force-stops.

## #20/#21 — system-app update verification

These checks are intentionally destructive to a **test** system-app update, not to a production
device. Use a disposable userdata image or a test device.

1. Boot and filter logcat:
   ```bash
   adb logcat -b all -s PackageVerityExt
   ```
   A normal boot with no `/data` system-app updates should be quiet. If a system app has an
   update, expect `Performing verification of system package update <package>`.
2. Install a test update for a debuggable system app signed with the platform key. It should
   install if its `versionCode` is greater and every split has fs-verity.
3. Try the same `versionCode` as the system image package. The install must fail; the log should
   contain `Not allowed to update system package to the same versionCode`.
4. Try an update without fs-verity (remove the `.idsig`, or use an APK that does not get fs-verity
   set up). The install must fail with the fs-verity message. A debug build can bypass with
   `adb shell setprop persist.disable_install_time_fsverity_check true`; a user build must not.
5. Reboot with a lower-version `/data` update already installed. The boot-time scan must reject it
   and the system image version must be active again. Confirm with:
   ```bash
   adb shell dumpsys package <package> | grep -E 'versionCode|codePath'
   ```
6. Reboot with a valid update. It must survive the reboot and remain the active code path.
7. Verify a mismatched signing certificate is rejected with `INSTALL_FAILED_BAD_SIGNATURE`.

## #25 — screenshot sound

1. With **Settings → Sound & vibration → Touch sounds** (the `SOUND_EFFECTS_ENABLED` setting) on,
   take a screenshot: the normal screenshot sound must play.
2. Turn it off, take a screenshot: no sound.
3. On a device/region where `MediaActionSound.mustPlayShutterSound()` is true, open the camera and
   take a screenshot with sound effects off: the forced shutter sound must still play.
4. Repeat with the camera closed: no forced sound.
5. Check that screenshot capture latency and SystemUI crashes are unchanged in logcat.

## #17 — crash/ANR log viewer

1. Open **Settings → About phone → Crash logs** (wording may differ), trigger a deliberate test
   crash in a disposable app, then confirm the entry appears after DropBox records it.
2. Confirm only crash/ANR/Java/watchdog tags are shown, entries are bounded, and no network
   permission or upload path exists.
3. Use the explicit share action and confirm it opens a chooser; cancel it and verify no file is
   written outside the app's cache.
4. Confirm the viewer does not expose other users' DropBox entries and that a locked device cannot
   open the Settings activity.

## #27 — Seedvault app-id prefix

1. Build Seedvault; confirm `com.stevesoltys.seedvault` is still the package id and the app
   launches.
2. Create a new backup with the GrapheneOS chunker; restore it on a clean test device.
3. Restore an **old** LineageOS Seedvault backup and record whether it succeeds. If it does not,
   the migration path must be written before promotion.
4. Check the internal package prefix with:
   ```bash
   adb shell dumpsys package com.stevesoltys.seedvault | grep -i app.grapheneos
   ```
5. Confirm `BASE_SPLIT` and the allowlist still resolve; do not remove the legacy constant.

## #28 — Setup Wizard bootloader warning

1. On a test build with `ro.boot.verifiedbootstate=green`, run Setup Wizard and confirm the
   warning is absent.
2. On an unlocked/unsigned test build (`orange`/`yellow`/`red`), confirm the warning appears on
   the welcome page, does not block Next, and the text does not tell the user to re-lock an
   unsigned build.
3. Confirm the property read is safe when the property is missing; the warning must not crash
   Setup Wizard.
4. Check the warning survives rotation and is not duplicated on back/forward navigation.

## OPS-1 — metadata scrubber

1. Share a geotagged JPEG to “lenOS OPSEC” from Gallery/Files; choose “Remove metadata and share”.
2. Receive it in a test app and parse it with an external tool:
   ```bash
   exiftool received.jpg | grep -i -E 'gps|exif|xmp|software|date'
   ```
   The output must have no GPS/EXIF/XMP fields and a randomized file name.
3. Repeat with PNG, WebP, HEIF and a multi-select share. Confirm animated GIF is rejected cleanly.
4. Confirm the app requests no network access and that airplane mode does not break the flow.
5. Test “Save sanitized copy” and confirm `Pictures/lenOS` contains a file with no source name.

## OPS-2 — Offline tile

1. Add the “Offline” tile from the Quick Settings edit screen; confirm it appears and the icon
   state reflects airplane mode.
2. With Wi-Fi and Bluetooth on, tap the tile. All three must turn off; the tile must be active.
3. Tap again; airplane mode must turn off, and Wi-Fi/Bluetooth must stay off until explicitly
   re-enabled.
4. Repeat while a call is active and while the screen is locked; record telephony behavior and any
   permission denial in logcat.
5. Confirm no crash when the platform call is denied (revoke `NETWORK_SETTINGS` on a test build or
   use the fallback path) and that the tile still updates.

## OPS-3 — screen-off clipboard wipe

1. Enable **Settings → Security & privacy → More security & privacy → Clipboard privacy**.
2. Copy text, an image URI and a text URI; turn the screen off, wait for the lock screen, then turn
   it on. A test app must get an empty primary clip; URI grants must be revoked.
3. Repeat with the setting disabled; the clip must survive (until AOSP's own auto-clear timer).
4. Confirm the setting is per-user: a second user with the setting off must keep their clipboard.
5. Reboot and confirm the setting persists and the screen-off receiver still fires.
6. Confirm clearing does not crash when the clipboard contains a URI grant or a virtual-device
   clipboard.

## OPS-4 — per-app clipboard access

1. Open **Settings → Security & privacy → More security & privacy → Clipboard access by app** and
   confirm only user-installed packages appear, with labels, package names and switches.
2. Use a test app that reads the clipboard while focused. Allow it, copy text in another app, and
   confirm the test app can read it.
3. Turn the test app off. Copy again and confirm the read returns null/empty while the app is
   focused. Confirm the global Secure Paste setting still wins if it is also blocking reads.
4. Confirm system apps and enabled keyboards are absent, and that a shared-UID package shows the warning.
5. Toggle an app, reboot, and confirm the AppOp persists:
   ```bash
   adb shell cmd appops get <package> android:read_clipboard
   ```
6. Confirm the screen does not crash when the package list is empty or when an app is uninstalled
   while the list is loading.

## OPS-5 — tracking-parameter scrubber

1. Share text containing a URL with `utm_source`, `fbclid`, `gclid`, a functional `id` parameter
   and a fragment to “lenOS OPSEC”; choose “Remove tracking parameters”.
2. Confirm only the known tracking fields are gone, the `id` parameter and fragment remain, and
   the app does not open the link.
3. Share multiple URLs and plain text with no links; confirm only the URLs are changed.
4. Use “Copy cleaned text” and compare it with the preview. Confirm the app has no network code and
   that a malformed URL is left untouched rather than crashing.
5. Check a shortened link: the scrubber must not resolve it and the UI must not imply it is safe.

## HTS-1 — hardened thread stacks

HTS-1 is part of the experimental series (`LENOS_EXPERIMENTAL=1`). The stable
default build keeps the stock mapping. Do not use HTS-1 on a daily driver until
the boot and compatibility checks pass.

1. Build two images for comparison. The HTS-1 image is a normal experimental
   build. For the control, temporarily remove the
   `ro.lenos.hardened_thread_stacks=1` line from
   `$SRC/vendor/lenos/config/lenos-experimental.mk` in a separate tree, rebuild,
   and restore the line afterwards. Confirm the HTS-1 image has the property set
   to exactly `1` and the control build does not have it:
   ```bash
   adb shell getprop ro.lenos.hardened_thread_stacks
   OUT=out/target/product/asteroids LENOS_EXPECT_HARDENED_STACKS=1 \
       tools/verify-build.sh
   ```
   `verify-build.sh` prints the property; the control build should print
   `<unset>`. Do not try to change it with `setprop`; it is a read-only build
   property.

2. Confirm the alternate mapping is actually used for a new thread. Pick a
   debuggable test app, start several worker threads, and inspect its VMAs:
   ```bash
   PID="$(adb shell pidof <test.package>)"
   adb shell cat "/proc/$PID/maps" | grep 'stack_and_tls'
   ```
   With the property set, the mapping should contain a writable stack region,
   a `---p` (PROT_NONE) gap, and a separate writable page for
   `pthread_internal_t`/TLS. With the property absent, use the same command on
   the control build and record the stock layout. If SELinux denies
   `/proc/<pid>/maps`, use a debuggable test app and `run-as`, or a native
   test binary in `/data/local/tmp`; do not weaken SELinux to run the check.

3. Stress thread creation and teardown: create and join at least 10,000
   short-lived threads in a native test app, plus repeated app launches,
   ART/zygote activity, WebView page loads, camera open/close, and Binder-heavy
   flows. Watch for:
   ```bash
   adb logcat -b crash -b main -s libc DEBUG tombstoned
   adb shell dmesg | grep -i -E 'oom|segfault|stack'
   ```
   A `pthread_create` failure with `EAGAIN` is fail-closed behavior, not a
   reason to disable the guard; investigate the mapping arithmetic instead.

4. Compare memory and launch time between the control and HTS-1 builds. The
   random gap is virtual address space, so expect `VmSize` to rise (up to 50%
   of thread stack size on 64-bit, 10% on 32-bit) without a matching RSS rise.
   Record `MemAvailable`, `VmSize`, `VmRSS`, cold app-launch time, and any
   increase in page-fault rate. Reject the feature if RSS or latency regresses
   materially.

5. Reboot, lock/unlock, make an emergency call, use the camera, and run a
   full app-compatibility pass. HTS-1 does not touch AVB, encryption, SELinux,
   recovery or the kernel, but the boot must still be treated as a test build
   until this pass is complete.

6. Only then consider a longer soak. Keep the control build available so a
   regression can be bisected to the property rather than to the rest of the
   experimental series.

Known limitation: the main thread and threads created before the property is
read keep their existing layout. This feature does not add `hardened_malloc`,
MTE/TBI, BTI/PAC, exec spawning, JIT restrictions or seccomp changes.

## ENF-1 / #23 partial — native-debugging block

This verifies the experimental global primitive, **not** GrapheneOS's per-app feature.

1. Build and boot with the framework and Settings patches. Confirm **Block native debugging** is
   off by default:
   ```bash
   adb shell settings get secure block_native_debugging
   ```
   The expected result is `null` or `0`.
2. Enable it in **Settings → Security & privacy → More security & privacy → Block native
   debugging**. Start a fresh non-system, non-debuggable app process and confirm its dumpable bit is
   clear:
   ```bash
   adb shell pidof <package>
   adb shell cat /proc/<pid>/status | grep -i dumpable
   ```
   Also verify from a same-UID non-root context that `ptrace`/`/proc/<pid>/mem` is denied. Do not
   use this check on a production device without a recovery plan.
3. Confirm the exemptions: a debuggable build, a profileable app and a system app must retain
   normal debugging/profiling behavior. Confirm a newly started app after disabling the setting is
   back to normal.
4. Confirm root or a process with `CAP_SYS_PTRACE` (for example the crash dumper) can still collect
   a tombstone; ENF-1 is not a root-of-trust boundary.
5. Reboot and force-stop an app after toggling; verify the setting persists and that running
   processes are not silently retrofitted. This is the documented global approximation, not the
   per-app `GosPackageState` policy.

## Rollback

If the build fails or the device misbehaves, use `lenos-patch.py --reset` on the source tree and
rebuild. Do not attempt to recover a device by weakening verified boot or locking state. Follow
[`../../docs/flash-and-lock.md`](../../docs/flash-and-lock.md).
