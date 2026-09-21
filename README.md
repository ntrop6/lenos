<p align="center">
  <img src="docs/banner.jpg" alt="lenOS" width="360">
</p>

# lenOS

**lenOS** is a hardened, anti-correlation LineageOS 23.2 distribution for the
Nothing Phone (3a) / (3a Pro) — codename `asteroids`, Snapdragon 7s Gen 3
(SM7635), GKI kernel 6.6 — with every feature integrated as a source patch or
device-tree commit, built and signed by you, with your own keys, and with
KernelSU-family root (ReSukiSU) injected into `init_boot` so the bootloader can
still be **relocked** against your own AVB key.

Nothing here is a runtime "module" bolted onto a stock ROM: the anonymity,
duress and hardening behavior is compiled into the system image from pinned
source.

## What you get

| Area | Feature | Where it lives |
|---|---|---|
| Coercion | Duress PIN/password → irreversible wipe, eSIM wipe isolated to SYSTEM_UID | patches 0006/0007 (GrapheneOS port) |
| Data-at-rest | Automatic BFU reboot, timer owned by init (survives system_server compromise), SEPolicied | patches 0008/0009 |
| Unlock | PIN scrambling on by default (lockscreen + SIM PIN) | patches 0004/0005 |
| Correlation | Per-connection Wi-Fi MAC randomization, DHCP state unlinkability, no DHCP hostname, Settings UI | patches 0010/0011/0012/0013 |
| Sensors | `OTHER_SENSORS` runtime permission, SensorService enforcement | patches 0001/0002/0003 |
| Privacy surface | Screenshots carry no OS build id and no capture timezone (EXIF stripped) | patch 0015 |
| Radio | LTE-only radio toggle (drops the 2G/3G downgrade surface), via TelephonyManager | patch 0014 (Settings panel) |
| Probes | Captive-portal detection off by default — zero connectivity probes, ever | lenos-netd seed + panel toggle |
| Network | Plaintext DNS (UDP+TCP/53) **and** NTP (UDP/123) blocked kernel-side at all times, from `post-fs-data` (no boot-window leak); optional strict output killswitch (allow only tun/loopback/VPN UIDs) | vendor/lenos firewall + sepolicy |
| Identity | The image presents the upstream stock Nothing build identity: no lenOS display ID, no `ro.lenos.*` props, no lenOS package names | device-patches |
| Apps | Camera, browser, SIM toolkit, gallery, contacts, recorder, calendar removed at build; Cromite shipped; the rest uninstallable | device-patches + Settings panel |
| Compartmentalization | 32 user profiles (GrapheneOS parity) via framework overlay | device-patches |
| Settings | A "lenOS security" category above every other Settings entry: DNS shield, time-sync shield, strict firewall, VPN UIDs, LTE-only radio, portal detection, system app removal | patch 0014 (Settings app) |
| Root | ReSukiSU LKM in init_boot ramdisk; presigned manager preinstalled | build pipeline |
| Verified boot | Custom AVB/OTA keys, relock supported | build pipeline (avbroot) |
| Kernel | Hardened config fragments + sysctl baseline | integrate step + device patch |

Read **DESIGN.md** for the reasoning and the honest limits (carrier/radio
identity is not solvable in software — see OPSEC.md), and **EXPERIMENTAL.md**
before adding more.

## Status (read this first)

This is a young, self-built project: no releases, no external audit, no
binary distributions — you build everything yourself from pinned source, which
is its main safety property. It ports the coercion-resistance features
faithfully (the duress code is byte-identical to GrapheneOS's), and it does
**not** claim GrapheneOS-grade exploit hardening (hardened malloc, MTE,
attestation) or patch cadence. Read the honest tables in DESIGN.md and
OPSEC.md before trusting any of this. Nothing in this repository is affiliated
with, endorsed by, or produced by Nothing, LineageOS, GrapheneOS, NullDebris,
or the Cromite project; see NOTICE for full attribution and licensing.

## Requirements

- Build host: Ubuntu 24.04 x86_64 (a clean GCP instance is ideal), 16+ vCPU,
  64 GB RAM recommended, **~450 GB free disk** (repo sync + out/).
- Root `adb` access to the phone for exactly one step per build
  (`resukisu-prepare`, which patches `init_boot` with the ReSukiSU LKM using
  the device itself). Everything else runs on the build host.
- One unlocked bootloader flash to install the first signed OTA. After that
  the bootloader can be relocked against your own key.

## Quickstart

```bash
sudo ./build/lenos.sh doctor          # installs deps, checks disk/tools
./build/lenos.sh sync                 # repo init/sync from pinned manifest
./build/lenos.sh integrate --profile full   # apply all patches + vendor files
./build/lenos.sh build                # breakfast + m bacon
./build/lenos.sh keys                 # generate AVB/OTA/package/APEX keys (BACK THESE UP)
./build/lenos.sh package --root resukisu    # sign APK/APEX, inject root LKM, re-sign AVB
./build/lenos.sh verify               # verify final OTA + built-in feature audit
```

Flash + relock: see the *Flashing and relocking* section below and the printed
instructions of `avbroot`.

Keep `keys/` and `release-info.txt` off any cloud account. If you lose the AVB
key, a relocked device is a paperweight.

## Flashing and relocking (first install)

1. Unlock once (wipes data): enable OEM unlocking, `fastboot flashing unlock`.
2. `avbroot ota extract --input <final-ota.zip>` gives you `boot.img`,
   `init_boot.img`, `vendor_boot.img`, `recovery.img` plus the super_empty
   image; follow avbroot's printed fastboot instructions (flash the signed
   images or the whole OTA via sideload).
3. Boot, complete setup, confirm ReSukiSU shows LKM mode and root works.
4. Relock: `fastboot flashing lock`. The device now verifies **your** key.
   Every subsequent lenOS OTA (signed with the same keys) installs cleanly.

## Repository layout

- `manifest/lenos-asteroids.xml` — pinned local manifest (every patched repo).
- `device-patches/` — `git am`-format commits against the pinned NullDebris
  device tree: rebrand, integration makefile, sepolicy, kernel fragment,
  32-user overlay.
- `patches/` — the 13 GrapheneOS-derived platform patches, the lenOS Settings
  panel (0014), and the screenshot-privacy patch (0015), authored against the
  pinned revisions.
- `vendor/lenos/` — vendored runtime: init rc files, firewall daemon,
  Cromite import + pinned fetcher.
- `tools/` — signing/verification tooling, bootanimation generator,
  Cromite fetcher, repository self-check.
- `build/lenos.sh` — the pipeline.
- `config/VERSIONS.sh` — every external pin (sha256-verified).

## Honest limits

- **Carrier/radio anonymity is not achievable in software.** IMEI lives in
  modem NVRAM, IMSI on the SIM, RF fingerprints are physical. lenOS cannot
  and does not pretend otherwise; OPSEC.md covers what actually works.
- Root weakens the security model by design; relocking with your own key
  restores verified boot, and the BFU timer is deliberately placed in init so
  data-at-rest survives a compromised system_server.
- Patches were written against the exact pinned revisions in the manifest.
  Moving the pins requires re-generating the patch set, not hope.
