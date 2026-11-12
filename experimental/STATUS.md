# Untestable-work status

This file is the honest boundary between what is implemented here and what is still only a
workstream. "Implemented" means the source patch exists and the static tests in
`experimental/tests/` pass with the stable base. It does **not** mean the code compiles, boots, or
behaves correctly on a device.

Everything below is opt-in: apply it only with `LENOS_EXPERIMENTAL=1` (or the explicit
`--experimental` patchkit mode), and only after the stable 1.0 series. HTS-1 is part of that
series; see its section below.

## Implemented in this repository

| ID | Feature | Patch | Why it cannot be tested yet |
|---|---|---|---|
| #17 | On-device crash/ANR log viewer | `packages_apps_Settings/0001` | Needs a Settings build, DropBox entries on a booted device, and confirmation that the Settings UID can read the tags |
| #20 | fs-verity enforcement for system-app updates | `frameworks_base/0001` | Needs a full system image and a booted device to exercise `scanPackageForInitLI` and the PackageInstaller path |
| #21 | Reject same/older system-app updates at boot | `frameworks_base/0001` | Same; the failure mode only appears across a reboot with a `/data` update |
| #25 | Screenshot sound follows `SOUND_EFFECTS_ENABLED`; forced shutter regions unchanged | `frameworks_base/0002` | Needs a SystemUI build and a device with/without a forced-shutter region |
| #27 | Seedvault GrapheneOS app-id prefix + chunker | `packages_apps_Seedvault/0001` | Needs a full Seedvault build and a backup/restore cycle, including migration from a pre-prefix backup |
| #28 | Setup Wizard unlocked-bootloader warning | `packages_apps_SetupWizard/0001` | Needs a Setup Wizard build and first-boot states with a green and non-green verified-boot property |
| #23 partial / ENF-1 | Global opt-in native-debugging block | `frameworks_base/0005` + `packages_apps_Settings/0005` | Needs a framework build, a booted device and a same-UID ptrace test; per-app `GosPackageState`/SELinux policy is still absent |
| HTS-1 / #33 partial | Hardened thread stacks: randomized guard gap, separate `pthread_internal_t` page, randomized stack top | `bionic/0001` | Part of the experimental series; needs a full bionic build, boot, thread-creation stress, app/ART compatibility and memory/performance checks |
| OPS-1 | Metadata-scrubbing image share target | `experimental/app/LenosOpsec` | Needs an app build and a real share flow; verify metadata removal with an external parser |
| OPS-2 | One-tap Offline radio tile | `experimental/app/LenosOpsec` | Needs a system app build and airplane-mode/Wi-Fi/Bluetooth behavior on `asteroids` |
| OPS-3 | Clear clipboard on screen off | `frameworks_base/0004` + `packages_apps_Settings/0003` | Needs a framework build and a screen-off cycle with text, image and URI clips |
| OPS-4 / #8 stage 2 | Per-app clipboard read control | `packages_apps_Settings/0004` | Needs a Settings build and an app-op read test; the UI is source-complete and uses the existing AppOps policy |
| OPS-5 | Tracking-parameter scrubber for shared text | `experimental/app/LenosOpsec` | Needs an app build and a real text-share flow; verify the link set with a local parser and no network |

Patch count: 11 (4 frameworks/base, 4 Settings, 1 SetupWizard, 1 Seedvault, 1 bionic) plus the
`experimental/app/LenosOpsec` source tree. The promoted USB and cellular defaults are part of the
stable `patches/` series and are tested in the main suite.

Static tests: 81 in `experimental/tests/` plus 16 build-gate tests in the main suite.
Each test sandbox applies the stable base first, then the experimental series. The Settings
patches are tested both one at a time and in series order; the reset driver removes rename
destinations and empty directories. The source-level review is in `docs/security-review.md`.

## Still to implement (in rough order)

These remain out of scope for the current experimental series, but are not implemented yet. Each
entry names the blocker rather than pretending the work is a small patch.

| ID | Feature | Blocker / prerequisite | Size |
|---|---|---|---|
| #23 | **Full** native debugging (ptrace) block with per-app toggles | ENF-1 provides the global kernel-dumpable primitive, but the per-app `GosPackageState` / SELinux-flags core, denial notification and sepolicy are still absent | L |
| #30 | Storage Scopes / Contact Scopes | XL port of the 64-file `GosPackageState` PackageManager core plus Settings/Permission UI; cannot be done safely without a build loop | XL |
| #31 | Two-factor fingerprint unlock (`LockDomain`) | XL backport (tens of files) with lock-screen and credential logic; needs a build/device loop and synthetic-password upgrade tests | XL |
| #33 | Full runtime/allocator hardening (hardened_malloc, quarantine/canaries, MTE/BTI, exec spawning, JIT policy) | HTS-1 only changes the pthread stack layout; the allocator, ART, MTE and JIT work plus a build/device/performance loop are still absent | XL |
| #34 | SELinux/seccomp tightening | Device-specific sepolicy; must be validated with `neverallow`, a boot loop, and app compatibility before shipping | XL |
| #35 | Browser/WebView replacement | Product decision (Vanadium vs Cromite vs Jelly) and an update channel; not a source-only framework patch. The current experimental batch does not choose a browser | decision |

### Deliberately not in this batch

* **#30/#31** are not “partially” implemented. A Storage Scope or contact picker without the
  PackageManager state core would be security theatre; a second-factor lock screen without the
  credential-domain storage would risk locking users out.
* **#33/#34** are program-level workstreams. HTS-1 is a narrow experimental-series bionic experiment;
  hardened_malloc, MTE/BTI, exec spawning and SELinux tightening are still absent. The
  portability-safe kernel subset is already in the main 1.0 series (#32); the remaining
  allocator/SELinux work cannot be validated without a build and boot loop.
* **#35** needs a product/browser decision. No prebuilt browser is silently added here.
* **#23** is represented by ENF-1 only as a global opt-in primitive. The GOS package-state core is
  still needed for per-app toggles, denial UI and the SELinux package-domain policy; ENF-1 is not
  described as the complete feature.

## What the OPSEC additions deliberately do not do

* They do not upload anything. `LenosOpsec` has no `INTERNET` permission and no network code.
* They do not auto-enable themselves. OPS-3 is off by default; the Offline tile must be added by
  the user; the metadata scrubber only runs when the user shares an image with it. OPS-4 only
  changes the AppOps mode of user-installed apps the user selects; it does not list system apps or
  enabled keyboards, and it cannot override the global Secure Paste block. OPS-5 strips only
  known tracking parameters; it does not open links, detect phishing, or rewrite functional query
  parameters.
* They do not claim a cryptographic wipe. Re-encoding removes metadata from the output file, and
  clipboard clearing removes the system clipboard and its URI grants; source files, thumbnails,
  app histories, IMEs and autofill storage are out of scope.
* They do not change verified boot, encryption, SELinux enforcement, emergency calling or recovery.

## Hardened thread stacks (HTS-1) limits

* The bionic patch is part of the experimental series. `LENOS_EXPERIMENTAL=1` sets the read-only
  property `ro.lenos.hardened_thread_stacks=1`; an absent value keeps the pinned AOSP mapping. The
  stable/default build has no property and keeps the stock mapping.
* It changes the layout of newly created pthread stacks only. The main thread, already-running
  threads, the allocator, static TLS for other mappings, and non-pthread stacks are unchanged.
* It is not `hardened_malloc`, MTE/TBI, BTI/PAC, exec spawning, a JIT policy or a sandbox. It does
  not stop a memory-corruption exploit; it makes stack-overflow-into-thread-metadata harder.
* The random guard gap reserves up to 50% extra virtual address space per 64-bit thread (10% on
  32-bit). This is virtual address space, not committed RSS, and the real memory/performance cost
  is unmeasured. A full boot and app-compatibility run is required.
* Code that assumes `pthread_internal_t` is at the top of the stack, or that computes a thread's
  metadata from its stack pointer, may break. ART, zygote, WebView/Chrome, camera and Binder-heavy
  apps are the priority compatibility tests.
* The property is read-only per boot; switching it requires a rebuild. There is no per-app or
  runtime toggle.

## Promotion rule

A row moves to the main `lenos-1.0` series only after:

1. the experimental patch applies to the pinned tree;
2. the full `asteroids` build succeeds with the main 1.0 series;
3. the feature’s `docs/verification.md` checks pass on a booted device;
4. there is an explicit product decision to include it.

Until then this repository is a staging area, not a claim of shipped behavior.
