# Building lenOS

lenOS is a patch set, not a full source tree. You supply a LineageOS 24.0 tree,
the normal Android build environment, and your own signing keys.

The series was developed against the `6.6/lineage-24.0` device trees in the
[NullDebris manifest](https://github.com/NullDebris/manifest). It is not a
general-purpose patch set for every LineageOS revision: `--check` will stop if
the surrounding source has drifted.

## 1. Get a compatible tree

Follow the normal LineageOS build setup for your host, using the
`lineage-24.0` branch. Add the device manifest before the first sync:

```bash
repo init -u https://github.com/LineageOS/android.git -b lineage-24.0
mkdir -p .repo/local_manifests
curl -fsSL -o .repo/local_manifests/asteroids.xml \
  https://raw.githubusercontent.com/NullDebris/manifest/main/asteroids-6.6-lineage-24.0.xml
repo sync -c -j"$(nproc --all)"
```

The manifest tracks `kernel/nothing/sm7635-devicetrees` at `6.6/lineage-23.2`
and `ParanoidGlyph`/`GlyphAdapter` at `lineage-23.1`/`15`. Those are the newest
upstream branches available for those projects; they are kernel/device sources
and standalone apps, not Android framework code, so they do not need a 24.0
branch. Leave the manifest pins as-is unless NullDebris publishes newer ones.

This initial sync is expected. Do **not** run `repo sync` again after applying
the patches; reset the tree first if you need to move it.

## 2. Apply the patch series

Clone the patchkit into `vendor/lenos` and apply the default series:

```bash
git clone https://github.com/ntrop6/lenos-patches.git vendor/lenos
python3 vendor/lenos/tools/lenos-patch.py --tree . --check
python3 vendor/lenos/tools/lenos-patch.py --tree . --apply
```

`--check` is read-only. `--apply` writes the patches with strict `git apply`;
a patch that does not match is a hard error, not a warning. Do not edit the
tree by hand and do not apply the patches with plain `git apply`.

To undo the series:

```bash
python3 vendor/lenos/tools/lenos-patch.py --tree . --reset
```

`--reset` restores tracked files and deletes files the series created. It will
discard local edits in the patched projects, so commit or save your work first.

## 3. Build

```bash
source build/envsetup.sh
lunch lenos_asteroids-user
mka bacon
```

The build uses the signing and OTA setup configured in your tree. No signing
keys are stored in this repository. If you use custom AVB keys or the
rootless/avbroot packaging flow, use the same procedure you use for any other
LineageOS build.

## Experimental series

The experimental work is a second series applied only after the default one.
It is not part of a normal build. Read
[`experimental.md`](experimental.md) for the full apply/reset contract.

Manual apply:

```bash
python3 vendor/lenos/tools/lenos-patch.py --tree . --experimental --check
python3 vendor/lenos/tools/lenos-patch.py --tree . --experimental --apply
```

The experimental product fragment adds `LenosOpsec`, but its source lives
outside the normal app directory. Copy it in before building:

```bash
cp -a vendor/lenos/experimental/app/LenosOpsec vendor/lenos/app/
LENOS_EXPERIMENTAL=1 mka bacon
```

To switch back, remove the copied app and reset the experimental series before
resetting the default series:

```bash
rm -rf vendor/lenos/app/LenosOpsec
python3 vendor/lenos/tools/lenos-patch.py --tree . --experimental --reset
python3 vendor/lenos/tools/lenos-patch.py --tree . --reset
```

If the patchkit is not inside the build tree, copy `config/`, `app/`, `rro/`,
and `release/` into `$SRC/vendor/lenos/` before building. For an experimental
build also copy `experimental/app/LenosOpsec` into
`$SRC/vendor/lenos/app/`.

## Optional helper

`lenos-1.0-shizuku.sh` is a wrapper used for one local build/signing setup. It
is not needed to build lenOS and it has extra dependencies (the LineageOS
signing wizard, avbroot 3.33.0+ for packaging, and a key directory). `package`
verifies the input OTA against your `ota.crt`/`avb_pkmd.bin`, and both the
rootless and root paths verify the final `init_boot` ramdisk and OTA/AVB chain.
If you use it, keep the patchkit outside the build tree:

```bash
git clone https://github.com/ntrop6/lenos-patches.git ~/lenos-patches
LENOS_SOURCE=$HOME/lineage ~/lenos-patches/lenos-1.0-shizuku.sh doctor
LENOS_SOURCE=$HOME/lineage ~/lenos-patches/lenos-1.0-shizuku.sh apply
LENOS_SOURCE=$HOME/lineage ~/lenos-patches/lenos-1.0-shizuku.sh build
```

The wrapper replaces `$LENOS_SOURCE/vendor/lenos` with its build inputs during
`apply`, so do not run it from a checkout that lives inside the build tree.
Use the manual path above in that case.

## Root (optional)

The default output is rootless. An opt-in root OTA is produced after the normal
rootless build, from the exact signed base OTA:

```bash
LENOS_SOURCE=$HOME/lineage LENOS_ROOT=bakasu \
  ~/lenos-patches/lenos-1.0-shizuku.sh root-prepare
LENOS_SOURCE=$HOME/lineage LENOS_ROOT=bakasu \
  ~/lenos-patches/lenos-1.0-shizuku.sh package
```

Use `LENOS_ROOT=kernelsu` for the fallback. `root-prepare` needs avbroot 3.33.0
or newer, network access for the pinned assets, and the `asteroids` device tree.
It verifies the base OTA against your configured OTA/AVB keys, does not modify
the source tree, and does not include a root manager in the system image.
Packaging re-signs `init_boot` and the OS AVB partitions, then verifies the final
OTA and its init_boot ramdisk.

Read [`root.md`](root.md) before using it. Root has not been boot-tested, and
locking is still not supported.

## Tests

From the patchkit checkout, the tests expect a pristine tree and do not build
Android:

```bash
LENOS_WORKSPACE=/path/to/lineage bash tests/run-tests.sh
```

`LENOS_PYTHON` can point at a Python with tree-sitter installed; Java syntax
checks are skipped when tree-sitter is unavailable, never silently passed as a
different check.

## After a build

Read-only helpers:

```bash
OUT=/path/to/out/target/product/asteroids tools/verify-build.sh
ANDROID_SERIAL=... tools/verify-device.sh
```

The device checklist, including the items that cannot be checked without a
cable or a reboot, is in
[`experimental/docs/verification.md`](../experimental/docs/verification.md).
Flashing and locking rules are in
[`flash-and-lock.md`](flash-and-lock.md).
