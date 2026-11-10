# Provenance and deviations

The patches were produced by reading the GrapheneOS trees and re-applying the logic to the pinned
LineageOS 24.0 checkouts. They are not cherry-picks with hidden context: each patch is a complete
diff against the commit below. Original lenOS work is marked as such.

## Pinned targets

| Project | Revision | Used by |
|---|---|---|
| `bionic` | `ff3bb041547924ac1a7504e4b3bd3ea18169ca2f` (`lineage-24.0`) | HTS-1 hardened thread stacks |
| `frameworks/base` | `7c7188f8585e20c035eb43fed72df5e717614b38` (`lineage-24.0`) | #20/#21, #22, #23 partial, #25, OPS-3 |
| `packages/apps/Settings` | `2f16bfe2c784623a324350cd19dae7f6066e2cfb` (`lineage-24.0`) | #17, #22, #23 partial, OPS-3, OPS-4 |
| `packages/apps/SetupWizard` | `9c75b8a75bb3e48d4ec96375fba00b1e409c8763` (`lineage-24.0`) | #28 |
| `packages/apps/Seedvault` | `cd6ab3fa1631d8c230b16a66239faca1e370b27e` (`lineage-24.0`) | #27 |
| `vendor/lenos` (main patchkit) | this repository, `lenos-1.0` | OPS-1 / OPS-2 source and opt-in product integration |

## GrapheneOS references

The local reference tree is `graphene-repos/fwb-full` at `ef402132a` (branch `17`). The Seedvault
reference is `GrapheneOS/platform_packages_apps_Seedvault` at `7cfffed` (branch `17`). The bionic
reference is the GrapheneOS bionic branch `17` at `e93ce48518dc0fba69878cb4ace37a3525862cbe`; the
hardened-thread-stack changes come from commits `4aefb578a7a0` (guard pages between static TLS and
stack), `369305a6632d` (move `pthread_internal_t` behind a guard page), `ff25c271653a` (secondary
stack randomization) and `b777629641e8` (missing overflow-check fixup). The relevant upstream files
are:

| lenOS patch | GrapheneOS source |
|---|---|
| `bionic/0001-hardened-thread-stacks.patch` | `libc/bionic/pthread_create.cpp` from the four GrapheneOS bionic commits listed above; no header change is needed |
| `frameworks_base/0001-system-app-update-verity.patch` | `services/core/java/com/android/server/pm/PackageVerityExt.java`; hooks in `services/core/java/com/android/server/pm/InstallPackageHelper.java` (`scanPackageForInitLI`, `preparePackageLI`) |
| `frameworks_base/0002-screenshot-sound-settings.patch` | `packages/SystemUI/src/com/android/systemui/screenshot/ScreenshotSoundController.kt` and `ScreenshotSoundPolicy.kt`; the existing `multivalentTests` for both classes |
| `frameworks_base/0003-usb-port-security.patch` | `core/java/android/hardware/usb/UsbPortSecurity.java`, `core/java/android/ext/settings/UsbPortSecurity.java`, `services/core/java/com/android/server/policy/keyguard/UsbPortSecurityHooks.java`, `core/java/android/hardware/usb/UsbManager.java`; AOSP `UsbService.enableUsbDataInternal` / `UsbPortManager.enableUsbData` |
| `packages_apps_Settings/0002-usb-port-security.patch` | GrapheneOS Settings `UsbPortSecurityPrefController.java` and `exploit_protection_settings.xml` (adapted to a standalone lenOS preference fragment) |
| `packages_apps_Seedvault/0001-grapheneos-app-id-prefix.patch` | Seedvault commit `db21e16` (internal `app.grapheneos` package prefix), binary chunker commit `61d1b60` / `libs/seedvault-chunker-0.1.jar` |
| `packages_apps_Settings/0004-clipboard-app-access.patch` | AOSP `AppOpsManager.OP_READ_CLIPBOARD` policy; the GrapheneOS per-app `GosPackageState` switch is not ported. This is the AppOps route anticipated by the stage-2 note in §8 of the main porting guide. |

## Original lenOS work

| Patch | Why it is original |
|---|---|
| `packages_apps_Settings/0001-crash-log-viewer.patch` | GrapheneOS's crash-reporting stack is a 17-file system-server service with a different UI and upload flow. This is a smaller, local-only DropBox reader with explicit sharing. |
| `packages_apps_SetupWizard/0001-bootloader-unlocked-warning.patch` | GrapheneOS's SetupWizard fork has no bootloader/unlocked warning; the feature was specified for lenOS and implemented against the LineageOS 24.0 Kotlin wizard. |
| `experimental/app/LenosOpsec` (source tree, installed only with `LENOS_EXPERIMENTAL=1`) | Original lenOS OPSEC tools: a metadata-scrubbing image share target, an Offline Quick Settings tile, and a tracking-parameter scrubber for shared text. |
| `frameworks_base/0004-clipboard-clear-on-screen-off.patch` + `packages_apps_Settings/0003-clipboard-privacy.patch` | Original lenOS OPSEC control. AOSP has a DeviceConfig auto-clear timer, not a screen-off wipe and not a user-facing setting. |
| `packages_apps_Settings/0004-clipboard-app-access.patch` | Original lenOS Settings UI over AOSP's existing `OP_READ_CLIPBOARD` AppOp. It does not port GrapheneOS's `GosPackageState` per-app state or its denial notification/toolbar path. |
| `frameworks_base/0005-native-debugging-block.patch` + `packages_apps_Settings/0005-native-debugging-block.patch` | Original lenOS global approximation of GrapheneOS's native-debugging control. It uses `prctl(PR_SET_DUMPABLE, 0)` for newly bound user app processes; the GOS per-app `GosPackageState`, SELinux package domains, denial notification and per-app UI are not ported. |

## Deliberate deviations

### HTS-1 — hardened thread stacks

* GrapheneOS enables the alternate layout unconditionally. lenOS keeps the four
  changes in one patch but selects them at runtime with
  `ro.lenos.hardened_thread_stacks`; only the exact value `1` enables the
  hardened path. The property is part of the experimental series
  (`LENOS_EXPERIMENTAL=1`), so the stable/default build adds no property and
  keeps the stock mapping.
* The port is limited to `libc/bionic/pthread_create.cpp`; no
  `pthread_internal.h`, linker, ART or allocator change is included. The main
  thread stays on the old path because `__libc_init_main_thread.cpp` calls the
  old allocator directly.
* The hardened path keeps the GrapheneOS layout: a page-aligned stack, a random
  `PROT_NONE` gap of at least one page (up to 50% of the stack on LP64 and 10%
  on LP32), a dedicated page for `pthread_internal_t`, and a stack top
  randomized within the old `pthread_internal_t` slot and aligned to 16 bytes.
* **lenOS deviation:** the zero-size mapping used for a caller-supplied stack
  skips the stack `mprotect` and the stack-top randomization. GrapheneOS's
  single `mprotect` range is not zero-length there, but splitting the regions
  in this port would otherwise call `mprotect(..., 0, ...)`. The metadata
  region is still protected and the gap remains `PROT_NONE`.
* **lenOS deviation:** all size additions on the hardened path use
  `__builtin_add_overflow`; the GrapheneOS code relies on the surrounding
  size checks. This is fail-closed: an overflow returns the empty mapping and
  `pthread_create` fails with `EAGAIN`.
* The existing AOSP `__allocate_thread_mapping` function is left unchanged and
  remains the only path when the property is absent or false.

### #20/#21 — system-app update verification

* The GrapheneOS class is ported in full for the normal package path, including static shared
  library handling. The AndroidPackageUtils original-package exception used by GrapheneOS for its
  browser and PDF viewer is **not** ported; lenOS does not ship those packages, and adding an
  allowlist without a concrete renamed system app would weaken the check.
* The boot-time signature check uses the same `INSTALLED_DATA` / `ROLLBACK` capability decision as
  GrapheneOS. LineageOS's additional signing-lineage helpers do not change that decision.
* The debug-only properties (`persist.disable_boot_time_fsverity_check`,
  `persist.disable_same_versionCode_sys_pkg_update_check`,
  `persist.disable_install_time_fsverity_check`) are retained so a debuggable build can recover
  from a bad test APK. They are never read on user builds.
* `PackageVerityExt` is not wired into `AndroidPackageUtils.getRealPackageOrNull`; this only
  matters for renamed system packages, which are not present in this product.

### #25 — screenshot sound

* Android 17 already removed the `screenshotForceShutterSound` gate from `ScreenshotSoundPolicy`
  and moved `registerAvailabilityCallback` into an application-scoped coroutine. The lenOS patch
  therefore changes only `ScreenshotSoundController` and its existing `multivalentTests`; the
  policy classes are copied into the test sandbox unchanged to pin that baseline.
* The `screenshotRemoveNonforcedSound` aconfig flag remains in place. It is a separate GrapheneOS
  feature that removes the non-forced sound on devices where it should not exist.
* The forced-shutter path is unchanged: `MediaActionSound.mustPlayShutterSound()` still forces the
  sound when the camera is open, even if sound effects are disabled.
* **lenOS deviation:** GrapheneOS branch 17 checks `SOUND_EFFECTS_ENABLED` before evaluating the
  forced path, which can silence a legally required shutter sound when touch sounds are off. lenOS
  evaluates `shouldForceShutterSound()` first and gates only the non-forced player. The test
  `screenshotSoundForced_ignoresSoundEffectsSetting` pins that behavior.
* `shouldForceShutterSound()` is suspend and the callback is registered unconditionally because
  the callback must exist on every build, not only on builds where the old flag was compiled in.

### #22 — USB-C data-line control

* GrapheneOS enforces the policy through vendor sysprops (`sys.port_security_mode`,
  `security.deny_new_usb2`) and its keyguard hooks. Those props are not portable to `asteroids`
  without the matching vendor HAL/kernel support, so this port uses the standard Android 17
  per-port `UsbPortManager.enableUsbData` HAL operation.
* Consequence: the AOSP operation disables the data lines only. Modes `ALL_PORTS_DISABLED` (0) and
  `CHARGING_ONLY` (1) are therefore equivalent on this build; a true VBUS-off mode needs a vendor
  HAL and is not claimed. The persistent key remains GrapheneOS's `persist.security.usb_mode` so a
  future HAL can consume it.
* The mode is applied on boot, on keyguard lock/unlock, and on first user unlock. AFU
  (`MODE_CHARGING_ONLY_WHEN_LOCKED_AFU`) uses an in-memory first-unlock flag, reset by every boot.
* User builds default to `MODE_CHARGING_ONLY_WHEN_LOCKED`; debuggable builds default to
  `MODE_ALL_PORTS_ENABLED` to keep adb available during bring-up. The Settings UI requires the
  device to be unlocked and asks for confirmation before allowing USB data while locked.
* The service has a deny gate for ordinary enable requests while the port-security policy is
  blocking; the controller bypasses it through `UsbPortManager` directly. This is intentionally
  asymmetric: security policy wins over app/HAL requests, while disable requests are always
  allowed.
* No `sys.port_security_mode`/`security.deny_new_usb2` writes are added. If the `asteroids` USB HAL
  does not implement `enableUsbData`, the policy is a no-op; the Settings screen detects “no USB
  ports” but cannot detect a HAL that reports ports and silently rejects the operation, hence the
  experimental status and physical verification step.

### #17 — crash/ANR log viewer

* Not a GrapheneOS port. It reads the existing DropBox crash/ANR/watchdog tags, bounds the number
  of records, and shares only on an explicit user action. There is no upload, no network
  permission, and no background reporting service.
* Settings needs `READ_LOGS`; the Settings UID is the system UID. The viewer is an About-phone
  entry, not a replacement for `logcat` or a full crash reporter.

### #27 — Seedvault app-id prefix

* LineageOS 24.0 already ships the Android 17 Seedvault upstream. This port applies the
  internal-prefix commit (`db21e16`) plus the GrapheneOS prebuilt chunker
  (`sha256 121735802e8e8c5e558379c9f3cfd5230e1baa60f73cd3905e935d40208148bb`).
* The public application id remains `com.stevesoltys.seedvault`, and the legacy
  `org.calyxos.seedvault.BASE_SPLIT` constant is retained for allowlist/backup compatibility.
  Only the internal `app.grapheneos` package prefix and permission names are renamed.
* Existing LineageOS Seedvault backups use the old internal names and may not restore. A migration
  test is required before this can be promoted.

### #28 — bootloader warning

* Original lenOS feature. GrapheneOS has no equivalent Setup Wizard code, and the LineageOS
  wizard is a different app. The warning is inserted on the welcome page, uses the hidden
  `ro.boot.verifiedbootstate` property, and is conditional on a non-green state. It does not block
  setup, does not ask the user to re-lock, and points out that re-locking an unsigned build can
  brick it.

### ENF-1 / #23 partial — native-debugging block

* Original lenOS implementation. GrapheneOS enforces `BLOCK_NATIVE_DEBUGGING` per package through
  `GosPackageState` and SELinux package domains, with per-app toggles and a denial notification.
  lenOS instead adds one global secure setting, one `prctl(PR_SET_DUMPABLE, 0)` native helper and
  an ActivityThread hook. It exempts system, debuggable and profileable apps, and it does not
  block root or any caller with `CAP_SYS_PTRACE`.
* It is intentionally not described as a full #23 port. Running processes are not changed, and
  there is no per-app state, denial UI or SELinux integration. It is an experimental primitive that
  must be boot-tested and reviewed before it could be promoted.

### OPS-1 — metadata scrubber

* Original lenOS work. Re-encoding is chosen over metadata parsing because it removes unknown
  metadata fields as well as EXIF/XMP/GPS, at the cost of recompression. The output is a new random
  file; the source is never modified. Animated GIF is rejected rather than silently flattened.
* The app has no `INTERNET` permission and no network code. It is platform-signed only because
  the same package also contains the privileged Offline tile; the scrubber itself uses no
  privileged API.

### OPS-2 — Offline tile

* Original lenOS work. Airplane mode is the authoritative switch; Wi-Fi and Bluetooth are turned
  off first. It does not toggle NFC and does not claim to power down the baseband. The
  platform-signed service uses `NETWORK_SETTINGS`, `WRITE_SECURE_SETTINGS` and
  `BLUETOOTH_PRIVILEGED`; the fallback path writes the airplane setting and sends the protected
  broadcast rather than crashing.

### OPS-3 — screen-off clipboard wipe

* Original lenOS work. AOSP's existing auto-clear is a DeviceConfig timer (default one hour) that
  runs after a clip is read; this patch adds a per-user `Settings.Secure` opt-in and clears the
  clipboard when `ACTION_SCREEN_OFF` is received.
* The wipe uses the existing internal clear path, so URI grants are revoked and listeners are
  notified. It does not clear app-owned histories, IMEs or autofill storage, and it is off by
  default because deleting clipboard content without warning is a data-loss risk.

### OPS-4 — per-app clipboard access

* Original lenOS UI. GrapheneOS implements per-app clipboard access with `GosPackageState` and a
  denial notification/toolbar path; lenOS uses the existing AOSP `OP_READ_CLIPBOARD` AppOp instead.
  That is the stage-2 route anticipated in the main §8 audit. It deliberately does not port the
  `GosPackageState` core, the per-app state storage or the SystemUI toolbar.
* Only user-installed apps are listed. System apps, enabled keyboards and disabled packages are
  excluded to avoid breaking keyboard paste; shared-UID apps are shown with a warning because the
  AppOp applies to the package, not an isolated process. The global Secure Paste setting remains
  authoritative.

### OPS-5 — tracking-parameter scrubber

* Original lenOS work. The URL matcher and parameter list are local and intentionally conservative;
  the app never resolves a shortener, fetches a page or checks a blocklist. It preserves functional
  query parameters and fragments, so it is not a complete URL anonymizer. No GrapheneOS code is used.

## License

New files carry the Apache-2.0 header and credit GrapheneOS where the implementation derives from
it and the lenOS contributors. Modified AOSP files keep their original headers. See
[`../../LICENSE`](../../LICENSE).
