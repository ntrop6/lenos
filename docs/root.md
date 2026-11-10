# Opt-in root

The default lenOS build is rootless. Root is an explicit, post-build choice:

```bash
LENOS_ROOT=bakasu LENOS_ROOT_LKM=/path/to/kernelsu.ko ./lenos-1.0-shizuku.sh root-prepare
LENOS_ROOT=bakasu ./lenos-1.0-shizuku.sh package
```

`LENOS_ROOT` accepts `none` (default), `bakasu`, and `kernelsu`. The CLI form
`--root bakasu` does the same thing. `LENOS_ROOT_LKM` must point at a module
built against the kernel in this tree (see “Kernel module compatibility”
below). The pinned GKI module is refused unless you also set
`LENOS_ALLOW_UNVALIDATED_LKM=1`.

This is not an official or supported root method. It changes the attack surface
and it has not been boot-tested on hardware. Do not treat a successful
`avbroot ota verify` as proof that the device will boot.

## What this does and does not do

It does:

- build the normal rootless LineageOS image first;
- verify the base OTA against your configured OTA certificate and AVB public key
  before using it;
- extract `init_boot.img` from that exact signed base OTA;
- use a pinned x86_64 boot-image patcher to inject the selected root LKM and
  `ksuinit` into the `init_boot` ramdisk;
- verify the stock and patched ramdisk with avbroot;
- package a new OTA with `avbroot --prepatched`, re-signing `init_boot` and the
  other OS AVB partitions with your AVB key;
- keep the root manager as a separate APK that you install after first boot.

It does not:

- add a manager APK, `su`, BakaSU, KernelSU, or Magisk to the system image;
- change the kernel image, SELinux, encryption, or product configuration. It
  patches only the `init_boot` ramdisk; packaging re-signs the OS AVB tree
  (including `boot` and `vendor_boot`) and may update OTA certs as avbroot does
  for any OTA. The module you inject must already match the kernel that the
  build produced;
- flash, wipe, relock, or change any device setting;
- install or verify OEMUnlockOnBoot or any other boot-failure recovery guard;
- prove that the resulting image boots.

## Kernel module compatibility

The lenOS kernel is built from `kernel/nothing/sm7635` with the vendor configs
plus `vendor/lenos_hardening.config` (`CONFIG_RANDOM_KMALLOC_CACHES`,
`INIT_ON_FREE_DEFAULT_ON`, `RANDOMIZE_KSTACK_OFFSET_DEFAULT`,
`ZERO_CALL_USED_REGS`, and friends). Those options change kernel internals, and
`RANDOM_KMALLOC_CACHES` changes the allocator layout. A module built for
Google's GKI KMI is not guaranteed to load against that kernel, and if the
loader accepts it anyway it can index the wrong allocator cache.

The pinned BakaSU/KernelSU modules are GKI-built release artifacts. They are
therefore **not** accepted by default:

```bash
# preferred: build kernelsu.ko against this tree's kernel, then:
LENOS_ROOT=bakasu LENOS_ROOT_LKM=/path/to/kernelsu.ko \
  ./lenos-1.0-shizuku.sh root-prepare

# only if you explicitly accept that the pinned module is unvalidated:
LENOS_ROOT=bakasu LENOS_ALLOW_UNVALIDATED_LKM=1 \
  ./lenos-1.0-shizuku.sh root-prepare
```

The local module path is hashed and recorded in `root-state.json`; `package`
and `extract` re-verify the patched ramdisk against that hash. A module built
without `RANDOM_KMALLOC_CACHES` is only a candidate until it loads and the
manager reports root on the device. Do not assume that a successful
`avbroot ota verify` proves the module ABI.

## Requirements

- Linux x86_64 build host.
- avbroot 3.33.0 or newer (`boot unpack` and `cpio unpack` are required).
- Your existing `LENOS_KEYDIR` with `avb.key`, `ota.key`, `ota.crt`, and
  `avb_pkmd.bin`.
- The signed `base-signed-ota.zip` produced from the same source build. You can
  override the path with `LENOS_BASE_OTA=/path/to/ota.zip`. The OTA must verify
  against your configured `ota.crt` and `avb_pkmd.bin`; a stock OTA, an unsigned
  zip, or one signed by different keys is refused before it is patched.
- Network access for the pinned manager APK and host patcher. The manager APK
  always supplies the manager app; when the pinned profile is used it also
  supplies the BakaSU LKM and `ksuinit`. The cache lives at
  `$LENOS_WORKSPACE/.root-cache` by default. Override it with
  `LENOS_ROOT_CACHE`.
- A root LKM built against this tree's kernel (`LENOS_ROOT_LKM`), unless you
  explicitly accept the pinned GKI module with `LENOS_ALLOW_UNVALIDATED_LKM=1`.

The source tree must still contain the `asteroids` device tree so the helper can
read `BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE`. It does not edit the tree.

## Commands

```bash
# 1. Normal rootless build
LENOS_ROOT=bakasu ./lenos-1.0-shizuku.sh build

# 2. Patch init_boot from base-signed-ota.zip
LENOS_ROOT=bakasu LENOS_ROOT_LKM=/path/to/kernelsu.ko \
  ./lenos-1.0-shizuku.sh root-prepare

# 3. Inspect the recorded hashes at any time
LENOS_ROOT=bakasu ./lenos-1.0-shizuku.sh root-status

# 4. Re-sign the complete OTA; this does not touch the phone
LENOS_ROOT=bakasu ./lenos-1.0-shizuku.sh package

# 5. Extract the fastboot plan
LENOS_ROOT=bakasu ./lenos-1.0-shizuku.sh extract
```

The outputs are:

- `lenos-asteroids-bakasu.zip` (or `...-kernelsu.zip`);
- `lenos-asteroids-bakasu-manager.apk` and its `.sha256`;
- `extracted-bakasu/` (or `extracted-kernelsu/`);
- root state under `$LENOS_WORKSPACE/lenos-root/<mode>/`.

`root-prepare` records the base OTA hash, the stock `init_boot` hash, the LKM
source (`local` or `pinned-unvalidated`), and the payload hashes in
`root-state.json`. `package` verifies the base OTA
signature against your keys, re-hashes both the OTA and its init_boot, and checks
the state against the pinned profile before patching. `extract` verifies the
final OTA and re-checks the manager/state. Re-run `root-prepare` after every new
build.

The default rootless `package` path also requires avbroot 3.33.0+ and verifies
that the final `init_boot` ramdisk is stock. Passing `--rootless` to avbroot
only means "do not add root"; it is not a way to remove root from a pre-patched
base OTA.

## The two profiles

### BakaSU (preferred)

BakaSU is the renamed successor to ReSukiSU. The profile pins BakaSU 4.2.0-rc3,
source commit `239e1e8871b8fcd51a6e5b3002e0ba522fdd99fb`, and KMI
`android15-6.6`.

BakaSU publishes manager APKs, not separate LKM or `ksuinit` release assets.
The signed arm64 manager APK contains the matching
`android15-6.6_kernelsu.ko` and `ksuinit` inside its
`lib/arm64-v8a/libksud.so` payload, compressed as raw DEFLATE. The profile pins
the manager APK, that inner `libksud.so`, the two stream offsets, and the final
payload hashes. This avoids nightly.link and expiring CI artifacts while using
exactly the payload BakaSU's own manager ships.

| Asset | SHA-256 |
|---|---|
| manager APK | `25657bc449439687608fffa04b4b586de90fc405e3dc6217bd997fc71ba0a0a1` |
| `lib/arm64-v8a/libksud.so` | `c80b0cb7a5b240ea442a3963f2f0cfabde0b1cd197056772793064766ae9263a` |
| `android15-6.6_kernelsu.ko` | `4241d4334d22b5824023c848086f803973b8af44f28032572bd1146cd938501d` |
| `ksuinit` | `761afc0cac6ad839685493246cb352fa70a51ac2898daad70d1e88bf394b6dde` |
| LKM stream offset | `920170` (`0xE0A6A`) |
| `ksuinit` stream offset | `2405158` (`0x24B326`) |

The manager APK's full-file SHA-256 is the authentication pin. The helper also
extracts the first v2 signer certificate and compares its byte pin: 887 bytes,
SHA-256 `d3469712b6214462764a1d8d3e5cbe1d6819a0b629791b9f4101867821f1df64`.
This is not a full APK signature verification; keep the full-file hash and the
certificate pin together when updating the profile.

The upstream release asset is still named
`ReSukiSU_v4.2.0-rc3_35171-arm64-v8a-release.apk`. That is the upstream filename
for the renamed BakaSU project; it is not the obsolete 4.1.0 profile. Do not
silently swap in a newer manager or payload; update the JSON and all hashes and
offsets together.

### KernelSU (fallback)

The fallback pins KernelSU 3.3.1, source commit
`0c0fdb960178fa12d80d6cbcfdcb6ad8be6a865d`, and KMI `android15-6.6`.

| Asset | SHA-256 |
|---|---|
| manager APK | `b4a059ace71de2fa65cc7f12b1c58d55fc23ab25e057ee4230ce779742abe450` |
| `android15-6.6_kernelsu.ko` | `e57ce23de951be6b0dee5030f6724322fed126aa4af71828994437bfb0bb61ad` |
| `ksuinit-aarch64` | `365c66e5435a9ecdb3dbb23ceda2d9253568defeee3682af95220087094eff5d` |

The manager APK's full-file pin is the authentication control; its first v2
signer certificate is also pinned at 827 bytes, SHA-256
`c371061b19d8c7d7d6133c6a9bafe198fa944e50c1b31c9d8daa8d7f1fc2d2d6`. The
certificate check does not verify the whole APK signature.

### Why both use the KernelSU host `ksud`

KernelSU publishes a static x86_64 boot-image patcher. BakaSU publishes only an
arm64 Android `ksud` inside its manager, which cannot run directly on the build
host. The host patcher is only a file-level boot-image rewriter: it unpacks the
ramdisk, adds `init.real`, installs the selected `ksuinit` as `init`, and copies
the selected `kernelsu.ko`.

The host patcher is pinned separately:

| Asset | SHA-256 |
|---|---|
| `ksud-x86_64-unknown-linux-musl` | `29b50f946a3cc40b04aef3dd587adad227fe0f70edf9c56b02c84479f0b0e954` |

In `bakasu` mode the injected LKM and `ksuinit` are extracted from BakaSU's
signed manager APK when the pinned profile is explicitly allowed; otherwise
pass a locally built module with `LENOS_ROOT_LKM`. In `kernelsu` mode both are
KernelSU's pinned files (same explicit-allow rule).

The extraction and the pinned host patcher were exercised on a synthetic GKI
`init_boot` image: the patched ramdisk contains the pinned `ksuinit` as
executable `init`, the original init as `init.real`, and the pinned
`kernelsu.ko`, and the helper's ramdisk verifier accepts the result. That
proves the payloads are accepted by the patcher and verifier; it does not
prove the LKM loads on `asteroids`. Device boot validation is still required.

## AVB and verified boot

`package` passes the patched image with `--prepatched` and re-signs the OS AVB
partitions listed by the signing plan. For a root build the plan must include at
least `init_boot`, `boot`, `vendor_boot`, and `vbmeta`; packaging stops if any are
missing.

After signing, the helper also:

1. verifies the patched OTA with `avbroot ota verify` before moving it into
   place;
2. extracts `boot`, `init_boot`, and `vendor_boot` from that OTA;
3. checks the final `init_boot` fits the pinned partition size;
4. reopens its ramdisk and checks for executable `init`, executable
   `init.real`, and the pinned `kernelsu.ko` with the expected hashes.

`extract` repeats the OTA and boot-image checks before unpacking the fastboot
plan. These checks catch a broken package, not a device-specific boot failure.
The bootloader, kernel module ABI, vendor init, and Nothing's verified-boot
behavior still need a real unlocked boot test.

Locking remains unsupported. This repository does not install a recovery guard,
and a failed boot after locking can be unrecoverable. The default rootless
build has the same limitation: there is no in-image OEM-unlock safety
mechanism, so it must stay unlocked and verified boot reports `orange`. Even
with a re-signed AVB chain, do not lock. The checklist in
[`flash-and-lock.md`](flash-and-lock.md) is reference-only; `lock-gates` refuses
to print a lock sequence for a rootless build and marks the root checklist as
unsupported.

## Installing the manager

The manager is deliberately not part of the OS image. After the root OTA boots:

```bash
adb install -r lenos-asteroids-bakasu-manager.apk
```

Open the manager, let it detect the installed LKM, and grant root. If it does not
detect root, stop and capture `adb shell su --version` / the manager diagnostics
before changing the boot image again.

If the kernel rejects the LKM (for example, module loading is disabled or
signature enforcement blocks it), this helper cannot fix that. Capture
`adb shell dmesg` and the manager logs. Do not disable verity or SELinux to work
around it, and do not flash a different boot image from another build.

## Updating

A root OTA must be built from the exact new base OTA:

1. build the new rootless base;
2. run `root-prepare` again with the same `LENOS_ROOT`;
3. package, verify, and flash the complete new OTA;
4. reinstall the pinned manager only if its profile changed.

Do not carry an old patched `init_boot` across builds, and do not sideload an OTA
signed with different keys.
