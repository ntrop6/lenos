# Experimental work

This is the optional second patch series. It is not part of the default build,
and the combined default + experimental image has not been built or booted.

The series exists for changes that are source-complete but still need a build
and a device to validate. Keeping it separate means a failed experiment cannot
stop the default series from applying.

## What is here

| Feature | Patch | State |
|---|---|---|
| **#20** fs-verity enforcement for system-app updates | `frameworks_base/0001-system-app-update-verity.patch` | Implemented; static checks pass; **not built or booted** |
| **#21** reject same/older system-app updates across reboot | same patch (GrapheneOS `PackageVerityExt` pair) | Implemented; static checks pass; **not built or booted** |
| **#25** screenshot sound follows the system sound-effects setting | `frameworks_base/0002-screenshot-sound-settings.patch` | Implemented; static checks pass; **not built or booted** |
| **#17** on-device crash/ANR log viewer | `packages_apps_Settings/0001-crash-log-viewer.patch` | Implemented; local-only; **not built** |
| **#28** Setup Wizard unlocked-bootloader warning | `packages_apps_SetupWizard/0001-bootloader-unlocked-warning.patch` | Implemented; **not built** |
| **#23 partial / ENF-1** global opt-in native-debugging block | `frameworks_base/0005-native-debugging-block.patch` + `packages_apps_Settings/0005-native-debugging-block.patch` | Implemented source-only; **not per-app** and **not built** |
| **HTS-1 / #33 partial** hardened thread stacks | `bionic/0001-hardened-thread-stacks.patch` | Implemented source-only; **experimental-only**, **not built or booted** |
| **#27** Seedvault/GrapheneOS app-id isolation | `packages_apps_Seedvault/0001-grapheneos-app-id-prefix.patch` | Implemented prefix port + GrapheneOS chunker; **restore compatibility unverified** |
| **OPS-1** metadata-scrubbing share target | `experimental/app/LenosOpsec` | Implemented; re-encodes images; **not built** |
| **OPS-2** one-tap Offline radio tile | `experimental/app/LenosOpsec` | Implemented; **not built** |
| **OPS-3** clear clipboard on screen off | `frameworks_base/0004-clipboard-clear-on-screen-off.patch` + `packages_apps_Settings/0003-clipboard-privacy.patch` | Implemented; opt-in; **not built** |
| **OPS-4 / #8 stage 2** per-app clipboard read control | `packages_apps_Settings/0004-clipboard-app-access.patch` | Implemented with AOSP's existing `OP_READ_CLIPBOARD` AppOps policy; **not built** |
| **OPS-5** tracking-parameter scrubber for shared text | `experimental/app/LenosOpsec` | Implemented; local-only link sanitizer; **not built** |

`STATUS.md` tracks the workstreams that are still blocked and why. The table
above is not a statement that the rest of the roadmap is done.

The OPSEC tools are described, with their threat model and limits, in
[`docs/opsec.md`](docs/opsec.md). They are lenOS-only work: GrapheneOS does not
ship an equivalent metadata sanitizer, offline tile, or screen-off clipboard
wipe.

## Known limitations

* **#20/#21 require fs-verity on the update APK.** AOSP only sets fs-verity up
  when the staged APK has a v4 signature (`.idsig`). A system-app update
  installed without one will be rejected; that is the intended fail-closed
  behavior, not a bug. Debuggable builds have the documented escape properties
  for recovery. Do not weaken this on a user build to make an ad-hoc update
  install.
* **The verifier keeps the system-image package in memory for the boot.** It is
  intentionally not invalidated when an update is installed: the next install
  must still be compared against the immutable package, not against the
  previous `/data` update.
* **#25 uses the existing system sound-effects setting.** There is no new
  lenOS-only screenshot sound switch; turning off touch sounds also silences
  the non-forced screenshot sound. Forced shutter regions still obey
  `MediaActionSound.mustPlayShutterSound()`.
* **#17 reads DropBox, not a full crash-reporting service.** It shows
  crash/ANR/Java/watchdog entries already present in DropBox, has no upload
  path and no automatic sharing. Settings needs `READ_LOGS`; entries are
  bounded. It is a log viewer, not GrapheneOS's crash-reporting app.
* **#27 preserves `com.stevesoltys.seedvault` as the application id.** Only the
  internal GrapheneOS package prefix, permission names and chunker are ported.
  Existing LineageOS Seedvault backups may not restore across the prefix
  change; test migration before relying on them.
* **#28 is a warning, not a lock.** It appears on the Setup Wizard welcome page
  when `ro.boot.verifiedbootstate` is not `green`; it does not block setup and
  does not encourage re-locking an unsigned build.
* **ENF-1 is only a global approximation of #23.** It is not GrapheneOS's
  per-app native-debugging policy: it has no `GosPackageState` state, no per-app
  allow/deny UI, no SELinux package domain and no denial notification. When
  enabled, newly started non-system, non-debuggable, non-profileable app
  processes clear their dumpable bit; existing processes and system apps are
  unchanged. Root or any process with `CAP_SYS_PTRACE` (including the crash
  dumper) is not blocked. An app that deliberately calls
  `prctl(PR_SET_DUMPABLE, 1)` can undo its own bit. The setting is off by
  default and must be built and boot-tested before it can be trusted.
* **HTS-1 is an experimental bionic layout change, not a runtime-hardening
  program.** It is part of the `LENOS_EXPERIMENTAL=1` series; the build then
  adds `ro.lenos.hardened_thread_stacks=1`, and bionic uses a randomized guard
  gap plus a separate page for `pthread_internal_t` on newly created threads.
  The stable/default build keeps the stock mapping. It does not change the main
  thread, existing threads,
  `hardened_malloc`, MTE/TBI, BTI/PAC, exec spawning, JIT policy or seccomp,
  and it is not a sandbox. The gap costs up to 50% extra virtual address space
  per 64-bit thread (10% on 32-bit), not committed RSS. App/ART compatibility
  and performance are unverified; see `STATUS.md` for the promotion blockers.
* **OPSEC tools are not cryptographic wipes.** Image re-encoding removes
  metadata from the output, but the source app, thumbnails and filesystem
  caches may retain the original. The Offline tile turns off airplane-mode
  radios but cannot prove the baseband is powered down; it does not cover NFC.
  Clipboard wiping removes the system clipboard and URI grants, not copies kept
  inside apps, IME history or autofill storage.
* **OPS-4 lists only user-installed apps and does not override the global
  Secure Paste policy.** It sets the existing `android:read_clipboard` AppOp to
  ignored for selected packages; system apps, enabled keyboards and shared-UID
  packages are excluded or warned about in the UI. If the default global Secure
  Paste setting is off, a per-app allow cannot re-enable reads. The screen has
  no search-index provider yet, and the AppOps mode is not a cryptographic
  capability boundary.
* **OPS-5 removes only known tracking parameters, not all query strings.** It
  deliberately keeps functional parameters (for example `source` or a search
  query) and does not follow, resolve or preview links. A shortener or a site
  that echoes tracking data in the path/fragment still leaks; inspect the
  cleaned text before sharing. The cleanup is not a URL reputation or phishing
  check.
* **No runtime evidence exists yet.** The tests are source-level only. See
  `docs/verification.md` for the checks that must pass after the first build.

## Apply and check

The experimental patches target the same pinned workspace as the default
series. They are applied **after** it and are not standalone against a pristine
tree.

```bash
WS=/path/to/lineage
cd /path/to/lenos                 # or vendor/lenos inside the tree

python3 tools/lenos-patch.py --tree "$WS" --check
python3 tools/lenos-patch.py --tree "$WS" --apply

# only after the default series
python3 tools/lenos-patch.py --tree "$WS" --experimental --check
python3 tools/lenos-patch.py --tree "$WS" --experimental --apply
python3 tools/lenos-patch.py --tree "$WS" --experimental --require-applied
```

`--require-applied` reverse-replays the whole series in a temporary copy, so
overlapping patches cannot produce a false `missing`. Use it as the build gate.

For a manual build, copy the experimental app and pass the flag to the build:

```bash
cp -a experimental/app/LenosOpsec "$WS/vendor/lenos/app/"
LENOS_EXPERIMENTAL=1 mka bacon
```

If the patchkit is outside the build tree, copy the normal build inputs first
as described in [`../docs/build.md`](../docs/build.md).

The optional helper does the apply and app copy itself:

```bash
LENOS_EXPERIMENTAL=1 ./lenos-1.0-shizuku.sh apply
LENOS_EXPERIMENTAL=1 ./lenos-1.0-shizuku.sh build
```

Reset the experimental series before the default series when switching back:

```bash
python3 tools/lenos-patch.py --tree "$WS" --experimental --reset
python3 tools/lenos-patch.py --tree "$WS" --reset
```

Remove a manually copied `app/LenosOpsec` as well. The driver detects this
ordering automatically.

Two read-only helpers are included for the first build window:

```bash
# post-build artifact presence (requires an OUT directory)
OUT=/path/to/out/target/product/asteroids tools/verify-build.sh

# read-only device properties/settings/package checks over adb
ANDROID_SERIAL=... tools/verify-device.sh
```

Neither script builds, flashes, wipes, relocks, reboots or writes a setting.
Behavioral checks that need a cable, a lock transition, a ptrace attempt or a
reboot remain manual and are listed in `docs/verification.md`. The source-level
threat review is in [`docs/security-review.md`](docs/security-review.md).

The #23 partial patch touches `core/jni/android_util_Process.cpp` and
`core/java/android/app/ActivityThread.java`. If the framework checkout is
sparse, add those paths before running the patch checker or tests:

```bash
git -C "$WS/frameworks/base" sparse-checkout add core/jni \
    core/java/android/app/ActivityThread.java
```

For HTS-1, make sure bionic's thread allocator is present:

```bash
git -C "$WS/bionic" sparse-checkout add libc/bionic/pthread_create.cpp
```

## Tests

```bash
cd experimental/tests
LENOS_WORKSPACE="$WS" ./run-tests.sh
```

The suite builds the default base in a sandbox and proves:

* every experimental patch applies cleanly after the default series and is
  listed in `series`;
* new and modified Java files parse with tree-sitter;
* the #20/#21 boot scan, install-time checks, fs-verity loop, versionCode
  comparison and signing capability checks are present and ordered correctly;
* the screenshot-sound patch keeps the forced-shutter path intact;
* #17 stays local-only (DropBox tags, explicit share) and #28 is conditional on
  the verified-boot property without blocking setup;
* #27 uses the GrapheneOS prefix while keeping the public application id;
* the OPSEC tools have no `INTERNET` permission or network code, the scrubber
  re-encodes rather than copying EXIF, the Offline tile cuts airplane
  mode/Wi-Fi/Bluetooth, the screen-off clipboard wipe is per-user and off by
  default, the per-app clipboard screen uses the existing `OP_READ_CLIPBOARD`
  AppOp without adding a framework surface, and the link scrubber keeps only
  known functional query parameters while remaining offline;
* the #23 partial clears `PR_SET_DUMPABLE` only for opted-in,
  non-system/debuggable/profileable app processes and does not pretend to be
  the GrapheneOS per-app policy;
* HTS-1 is scoped to `libc/bionic/pthread_create.cpp`, reads the exact
  `ro.lenos.hardened_thread_stacks` value `1`, keeps the stock allocator as
  the property-absent fallback, and keeps the randomized gap `PROT_NONE` while
  placing `pthread_internal_t` in its own page;
* the Settings patches are also applied **in series order** in a sandbox, not
  just one at a time, so a second patch cannot silently stop applying after the
  first one changes the same `strings.xml` or preference XML.

These are **not** runtime tests. The real verification list is in
`docs/verification.md`.

## Safety

Read [`../docs/flash-and-lock.md`](../docs/flash-and-lock.md) before using any
build. No patch here changes verified boot, encryption, SELinux enforcement,
emergency calling, or recovery. Do not flash an experimental build without
explicit approval and a recovery plan.

## Provenance

The GrapheneOS-derived implementations record their upstream source revisions,
files and lenOS deviations in `docs/provenance.md`. Original lenOS work (#17,
#28 and the OPSEC tools) is marked as such. New files carry Apache-2.0 headers
crediting GrapheneOS where applicable and the lenOS contributors. The
repository is licensed under Apache-2.0; see [`../LICENSE`](../LICENSE).
