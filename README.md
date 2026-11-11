# lenOS

A personal LineageOS 24.0 build for the Nothing Phone (3a) and (3a) Pro
(`asteroids`).

This repo is not a ROM distribution. It is the patch set and small apps that
make up the build. The LineageOS tree stays clean and every change is carried
as an ordinary git patch, so the build can be reproduced and reviewed. If you
have the same phone, you can build it too, or take only the changes you want.

lenOS is not affiliated with LineageOS, Nothing, or GrapheneOS. It is a
personal project, not a supported product.

The experimental series is optional and even less tested. A normal build never
applies it.

## What it changes

- strict DNS-over-TLS, non-Google time and captive-portal endpoints
- hardened first-boot defaults, PIN scrambling, duress wipe, and memory clearing
  on lock
- no Google apps or services added; AudioFX excluded
- local-only personalization (theme packs, Quick Settings layout, motion presets) via `LenosParts`
- optional extras behind `LENOS_EXPERIMENTAL=1`

The full list, including what does not work, is in
[`docs/features.md`](docs/features.md).

## Root and verified boot

The default image is rootless: no `su`, BakaSU, KernelSU, or Magisk is
included. Root is an explicit post-build option:

```bash
LENOS_ROOT=bakasu LENOS_ROOT_LKM=/path/to/kernelsu.ko \
  ./lenos-1.0-shizuku.sh root-prepare
LENOS_ROOT=bakasu ./lenos-1.0-shizuku.sh package
```

`bakasu` is the preferred profile and `kernelsu` is the fallback. The kernel
module must be built against this tree's kernel; the pinned GKI module is only
accepted with an explicit `LENOS_ALLOW_UNVALIDATED_LKM=1`. The build itself
stays rootless. The post-build step verifies the base OTA against your
configured OTA/AVB keys, patches `init_boot`, re-signs the OS AVB partitions with
your key, and keeps the root manager as a separate APK. The default rootless
packaging path verifies that the final `init_boot` is stock, so a pre-rooted base
cannot be shipped accidentally. Root has not been boot-tested; see
[`docs/root.md`](docs/root.md) for the exact pins and limitations.

The helper re-signs the OS AVB chain with your AVB/OTA keys via avbroot.
Bootloader locking is manual and unsupported by the helper; the scripts never
flash, wipe, or lock.

> **The default rootless build cannot be locked.** It ships no
> OEMUnlockOnBoot or equivalent boot-failure guard, so the helper refuses to
> produce a lock sequence for it. In practice the bootloader stays unlocked,
> verified boot reports the orange state, and anyone with physical access can
> replace the OS without wiping data. That weakens duress wipe, auto-BFU and the
> kernel hardening against physical attackers. Do not treat this build as a
> locked-device security boundary. Root does not make locking supported either.
> The full lock checklist and its prerequisites are in
> [`docs/flash-and-lock.md`](docs/flash-and-lock.md).

## Build

You need a LineageOS 24.0 tree for `asteroids`, a working Android build
environment, and your own signing setup. The patches were developed against the
`6.6/lineage-24.0` device trees in the
[NullDebris manifest](https://github.com/NullDebris/manifest). A tree that has
drifted may need patch updates; the patch tool is strict and stops rather than
applies with fuzz.

Clone this repo into `vendor/lenos`, then check and apply the series:

```bash
git clone https://github.com/ntrop6/lenos-patches.git vendor/lenos
python3 vendor/lenos/tools/lenos-patch.py --tree . --check
python3 vendor/lenos/tools/lenos-patch.py --tree . --apply
```

Build with your normal LineageOS flow, for example:

```bash
source build/envsetup.sh
lunch lenos_asteroids-user
mka bacon
```

The helper script in the repo root is optional. It automates a particular
build/signing setup, pins the external signing wizard by SHA-256, and is not
required to use the patches. Details are in [`docs/build.md`](docs/build.md).

To return the tree to its pinned state:

```bash
python3 vendor/lenos/tools/lenos-patch.py --tree . --reset
```

## What is here

- `patches/` — the default patch series, grouped by upstream project
- `patches-experimental/` — optional second series, applied after the default one
- `app/LenosSecurity/` — small settings app for controls the stock UI lacks
- `config/`, `rro/` — product configuration and privacy overlays
- `docs/` — build notes, feature list, porting notes, local personalization, flashing safety
- `experimental/` — opt-in app source, checks, and status notes
- `tools/` — patch application, read-only verification helpers, and the pinned
  opt-in root preparer
- `tests/` — source-level and host-side tests for the patches

The feature list and its honest limits are in
[`docs/features.md`](docs/features.md). The long, rough porting notes are in
[`docs/graphene-porting.md`](docs/graphene-porting.md).

## Experimental work

The optional series contains features that are source-complete but still need a
build and a device to validate. It applies only after the default series and is
selected with `LENOS_EXPERIMENTAL=1`. The bionic hardened-thread-stack
experiment is part of this series; the stable/default build keeps the stock
thread mapping. See
[`docs/experimental.md`](docs/experimental.md) for the order, reset rules, and
what remains untested.

## Tests

From the patchkit checkout, set `LENOS_WORKSPACE` to a pristine LineageOS tree
and run:

```bash
LENOS_WORKSPACE=/path/to/lineage bash tests/run-tests.sh
```

The suite checks that every patch applies to the pinned sources and asserts the
resulting code and resources. It does not build or boot Android.

## Flashing

Nothing here flashes, wipes, or locks a phone. Flashing is destructive and can
brick the device. Read [`docs/flash-and-lock.md`](docs/flash-and-lock.md) before
using any build.

## License

Apache-2.0. See [`LICENSE`](LICENSE). Some patches are adapted from GrapheneOS;
the sources and deviations are recorded in
[`docs/graphene-porting.md`](docs/graphene-porting.md),
[`experimental/docs/provenance.md`](experimental/docs/provenance.md), and the
per-patch notes.
