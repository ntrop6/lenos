# Experimental builds (opt-in)

Experimental work lives in this repository but is **not** part of the default
1.0 build. It is selected at build time with `LENOS_EXPERIMENTAL=1`.

If you use the optional helper, the two modes are:

```bash
# default 1.0
./lenos-1.0-shizuku.sh apply
./lenos-1.0-shizuku.sh build

# experimental image
LENOS_EXPERIMENTAL=1 ./lenos-1.0-shizuku.sh apply
LENOS_EXPERIMENTAL=1 ./lenos-1.0-shizuku.sh build
```

For the manual path, see [Apply-order contract](#apply-order-contract) below.
The driver normalizes the flag to `0` or `1` and exports it to the build.
`config/lenos.mk` inherits `config/lenos-experimental.mk` only when the value
is `1`, `true` or `yes`. If you apply patches manually and then run `mka`, pass
the same variable yourself:

```bash
LENOS_EXPERIMENTAL=1 mka bacon
```

Without it, `LenosOpsec` is not in `PRODUCT_PACKAGES` and the experimental app
source is not installed into `$WS/vendor/lenos/app/`. For a manual build, copy
it there yourself after applying the series:

```bash
cp -a experimental/app/LenosOpsec "$WS/vendor/lenos/app/"
```

## Layout

| Path | Purpose |
|---|---|
| `patches-experimental/<alias>/series` | Upstream-project patches applied **after** `patches/` |
| `experimental/app/LenosOpsec/` | OPSEC app source, installed only for an experimental build |
| `config/lenos-experimental.mk` | Experimental product fragment (`LenosOpsec`, `ro.lenos.experimental=1`, `ro.lenos.hardened_thread_stacks=1`) |
| `experimental/docs/` | OPSEC threat model, provenance, security review, device checklist |
| `experimental/tests/` | Source-level tests for the experimental series and app |
| `tools/verify-build.sh` | Read-only post-build artifact check |
| `tools/verify-device.sh` | Read-only adb property/setting/package check |

There is no `patches-experimental/vendor_lenos/` patch. The former
`vendor_lenos/0001-opsec-tools.patch` is now the gated source tree above, so
the patchkit never edits its own checkout.

## Apply-order contract

The experimental series is a **second series on top of the stable tree**, not
an alternative fork:

```bash
PY=python3
WS=/path/to/lineage

$PY tools/lenos-patch.py --tree "$WS" --check
$PY tools/lenos-patch.py --tree "$WS" --apply

$PY tools/lenos-patch.py --tree "$WS" --experimental --check
$PY tools/lenos-patch.py --tree "$WS" --experimental --apply

$PY tools/lenos-patch.py --tree "$WS" --require-applied
$PY tools/lenos-patch.py --tree "$WS" --experimental --require-applied
```

`--experimental --check` must be run after the stable series is applied. Each
experimental patch still has to apply with strict `git apply`, and the test
suite rebuilds the stable base in a sandbox before applying every experimental
patch independently and in series order.

`--require-applied` reverse-replays the whole series in reverse order in a
throwaway copy of every touched file. This is the authoritative check: a single
reverse check can report an earlier patch as `missing` when a later patch in
the same file changes its context. `--status` remains a per-patch display;
`--require-applied` is what the driver uses before it builds. Validate the
stable series **before** applying the experimental overlays.

## Reset / switching back

The driver detects an applied experimental series before resetting stable
projects, runs `--experimental --reset` first, then resets the stable series.
That removes experimental source files (including renames) before returning to
a stable build. To do it manually:

```bash
$PY tools/lenos-patch.py --tree "$WS" --experimental --reset
$PY tools/lenos-patch.py --tree "$WS" --reset
```

Never leave a partially applied series in the tree.

## Safety

Experimental means **source-complete, not validated**:

* no full `asteroids` build has been run for this combined series;
* no image has been flashed, wiped, relocked or booted;
* untested items include fs-verity updates, Seedvault restore migration, ENF-1
  ptrace behavior, Setup Wizard verified-boot states, HTS-1 thread-stack
  behavior/compatibility, and every OPSEC UI flow. The promoted USB and cellular
  features are documented and verified separately in `features.md`.

The no-flash/no-wipe/no-relock rules in
[`flash-and-lock.md`](flash-and-lock.md) still apply. An experimental build
must not be flashed without explicit approval and a recovery plan.

## Hardened thread stacks (HTS-1, experimental only)

`bionic/0001-hardened-thread-stacks.patch` is a source port of the GrapheneOS
pthread stack-layout changes. It is part of the experimental series: a normal
`LENOS_EXPERIMENTAL=1` build applies the patch and
`config/lenos-experimental.mk` adds `ro.lenos.hardened_thread_stacks=1`. The
stable/default build has no property and keeps the pinned AOSP mapping.

Bionic reads the property for each new `pthread_create` and accepts only the
exact value `1`. When the property is absent, the pinned AOSP mapping is used
unchanged. `verify-build.sh` reports the property and `verify-device.sh` prints
it on a booted device.

When enabled, a new thread mapping is laid out as:

```
[ stack guard ][ stack ][ random PROT_NONE gap ][ pthread_internal_t ][ static TLS ][ libgen ][ guard ]
```

The gap is at least one page and up to 50% of the stack on 64-bit (10% on
32-bit); the stack top is randomized within the old `pthread_internal_t` slot.
The main thread is intentionally unchanged because
`__libc_init_main_thread.cpp` calls the old allocator directly.

This is not `hardened_malloc`, MTE/TBI, BTI/PAC, exec spawning, JIT policy or a
sandbox. It only makes a stack overflow less likely to overwrite
`pthread_internal_t` and TLS. It has not been built or booted, and the extra
virtual address space and app/ART compatibility are unmeasured. See
[`../experimental/docs/verification.md`](../experimental/docs/verification.md)
for the required boot and thread-stress checks, and
[`../experimental/STATUS.md`](../experimental/STATUS.md) for the limits.

## Verification

```bash
# source-level tests (main suite, no build)
LENOS_WORKSPACE="$WS" LENOS_PYTHON=$PY bash tests/run-tests.sh

# experimental feature tests (stable base is built inside each sandbox)
cd experimental/tests
LENOS_WORKSPACE="$WS" LENOS_PYTHON=$PY ./run-tests.sh

# after a real build, read-only artifact check
OUT=/path/to/out/target/product/asteroids tools/verify-build.sh

# after an approved flash, read-only device check
ANDROID_SERIAL=... tools/verify-device.sh
```

The device checklist and honest limitations remain in
[`experimental/docs/verification.md`](../experimental/docs/verification.md),
[`experimental/STATUS.md`](../experimental/STATUS.md) and
[`experimental/docs/security-review.md`](../experimental/docs/security-review.md).
