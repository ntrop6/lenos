# lenOS design notes

This document maps every feature to its enforcement point, records the
reasoning, and states the limits explicitly.

## Philosophy

1. **Build-time, in-tree, pinned.** Anything that matters is a patch or a
   device-tree commit applied against pinned revisions. Xposed modules and
   Magisk-module spoofing are Java-layer and can be bypassed by native code
   and by consistency checks; framework-level enforcement cannot.
2. **Anti-fingerprinting means blending into the largest honest herd.**
   Every lenOS install presents the *stock Nothing 3a build identity* that
   the upstream device tree already spoofs — the same fingerprint, the same
   props, no lenOS display ID, no `ro.lenos.*` properties, no lenOS package
   names. Adding lenOS branding to observable strings would make every
   lenOS device MORE identifiable as a member of a tiny herd, so nothing
   lenOS-named enters the booted image: the brand exists only in the build
   tree (lunch target), the Settings panel (in-app strings), and the boot
   animation (device-local). Per-device randomization of model strings is
   rejected outright: rotating fake identities fails consistency checks
   (performance timing, sensors) and is MORE unique than a stable one.
   Where randomization is genuinely per-connection state (Wi-Fi MAC), we
   randomize aggressively instead.
3. **Daily drivability is a requirement, not a failure.** Captive portals,
   MMS, banking apps, navigation: lenOS ships with enforcement that doesn't
   turn the phone into a brick, and makes the strict options opt-in switches.
4. **Honest threat model.** See OPSEC.md. Software cannot defeat the radio.

## Feature → enforcement map

| Threat/surface | Enforcement | Location | Notes |
|---|---|---|---|
| Coerced unlock | Duress PIN/password → irreversible data + eSIM wipe | framework patch 0006, telephony patch 0007, Settings UI patch 0013 | GrapheneOS-derived; wipe runs without reboot, cannot be interrupted; identical duress+real credential resolves to real unlock |
| Data-at-rest after idle | Automatic BFU reboot | system/core patch 0008 (init owns CLOCK_BOOTTIME alarm), sepolicy patch 0009 | init-owned so a compromised system_server cannot cancel it; chain reboots avoided |
| Shoulder-surfing | PIN layout scrambling default-on | patches 0004/0005 | Lineage feature, default flipped |
| Covert sensor reading (accel, proximity…) | `OTHER_SENSORS` runtime permission | patches 0001/0002/0003 | revoke-able per app |
| Wi-Fi correlation | New MAC per connection, DHCP lease state flushed, DHCP hostname suppressed, per-connection UI | patches 0010/0011/0012/0013 | strongest practical anti-correlation layer that survives daily use |
| Radio downgrade attacks | LTE-only radio toggle (2G/3G code paths dropped, LTE/5G kept) | patch 0014 (TelephonyManager, MODIFY_PHONE_STATE) | opt-in switch; GrapheneOS LTE-only parity |
| Connectivity beacons | Captive-portal detection off by default (captive_portal_mode=2 seeded once; no probes, no portal auto-open) | lenos-netd first-boot seed + panel toggle | probes go to Google only if the user re-enables detection |
| DNS leaks | UDP+TCP/53 REJECT kernel-side except loopback/VPN tunnels, always — from post-fs-data (no boot-window leak; the settings file is unreadable pre-unlock and the daemon then applies fail-closed defaults) | vendor firewall daemon (system_ext, init-managed, sepolicy domain `lenos_netd`) | apps cannot fall back to plaintext DNS; DoT/DoH and VPN DNS keep working |
| Clock disclosure | NTP (UDP/123) REJECT outside tun interfaces by default; strict mode drops everything anyway | same daemon (`lenos_ntp_shield`) | time sync rides the VPN or the carrier; usable defaults without a VPN |
| Full network lockdown | Strict mode: default-DROP output except loopback, established, `tun+` interfaces and configured VPN UIDs | same daemon, toggled from the lenOS Settings panel (`lenos_strict_firewall`) | for use with always-on VPN; AOSP lockdown remains the daily-driver killswitch |
| Settings surface | "lenOS security" category above every other Settings entry | patch 0014 | writes `lenos_killswitch` / `lenos_strict_firewall` / `lenos_vpn_uids` to Settings.Global; no separate app package to fingerprint |
| Screenshot metadata | Screenshots carry no OS build display id and no capture timezone offset; width/height and local time kept, per-capture random UUID kept (never repeats) | patch 0015 (SystemUI ImageExporter) | GrapheneOS "private screenshots" parity, minus the parts users want |
| Compartmentalization | 32 user profiles via static framework-res overlay (`config_multiuserMaximumUsers`) | device-patches 0005 | GrapheneOS profile-count parity; profiles remain the strongest practical compartment on a rooted phone |
| App-visible identity | Stock Nothing build identity preserved (upstream spoof); zero lenOS strings in props | device-patches | only `ro.product.name` remains custom-ROM-shaped (as upstream); neutralization is an EXPERIMENTAL item |
| Browser fingerprinting | Cromite (hardened Chromium fork) as the only shipped browser; stock browser/camera/gallery/etc. removed | device-patches + pinned presigned import | fingerprinting defense belongs in the browser, not the ROM |
| Bloat/uninstall | Remaining Lineage apps uninstallable | lenOS Settings panel (`pm uninstall --user 0`) | denylist protects critical components |
| Root detection surface | ReSukiSU LKM (KernelSU family) | build pipeline (init_boot injection) | root is a chosen tradeoff; relock restores AVB |
| Seizure/forensics | FBE (stock), BFU reboot (above), duress (above), relocked verified boot | platform + pipeline | |

## What lenOS deliberately does NOT do

- **IMEI/IMSI/radio spoofing.** IMEI is burned into modem NVRAM; spoofing it
  is device-specific, fragile and illegal in many jurisdictions; the carrier
  identifies the SIM regardless. The honest mitigations are operational
  (OPSEC.md).
- **Per-device randomized build identity.** See philosophy §2.
- **Forcing a specific DoT provider.** lenOS blocks plaintext 53 and leaves
  provider choice to the user (Settings → Private DNS).
- **GrapheneOS-grade exploit hardening.** A solo project cannot match GOS's
  patch cadence or hardened malloc. lenOS adds kernel config hardening and
  sysctls; it does not claim security parity with GrapheneOS, which is also
  unavailable on this hardware.

## Root and verified boot

The signed OTA chain: built target-files → APK/APEX re-signed with generated
package keys (`sign_target_files_apks`) → audited (`tools/verify_signed_target.py`)
→ base OTA (`ota_from_target_files -k releasekey`) → ReSukiSU LKM injected
into init_boot ramdisk via `ksud boot-patch` → avbroot `ota patch --prepatched
--re-sign` with **your** AVB/OTA keys → verified OTA.

Because the bootloader verifies your key, `fastboot flashing lock` is safe
after install and future OTAs signed with the same keys verify. The BFU
reboot timer lives in init (PID 1) so a rooted-but-compromised system_server
still loses the race to data-at-rest.

**Signature visibility (honest note):** any app can read the signing
certificate of system packages. With per-builder keys, that signature is
unique to you — a fingerprinting vector lenOS cannot remove while keeping
your platform key private (a *public* shared key would blend into a herd but
let anyone sign platform-privileged code against your device: rejected).
If you run several lenOS devices under one identity, generate the keys once
and reuse them across those devices; see EXPERIMENTAL.md. The AVB key is
not app-visible (bootloader-layer only).

## The firewall daemon

`/system_ext/bin/lenos-netd` is started by init (`vendor/lenos/init/lenos_net.rc`)
with `seclabel u:r:lenos_netd:s0` and re-applies owned iptables/ip6tables
chains whenever its state changes (polled from
`/data/system/users/0/settings_global.xml`, the Settings.Global database —
no binder dependency):

- `lenos_dns_block` (always): REJECT UDP+TCP/53 outbound, except loopback and
  `tun+` interfaces. When the user's VPN is up, DNS rides the tunnel; DoT to
  any provider keeps working; plaintext DNS never leaves the device.
- `lenos_strict` (opt-in): default-DROP output except loopback, established,
  `tun+`, and UIDs listed in `lenos_vpn_uids` (comma-separated, configured in
  the LenOS app). This is the power-user killswitch; daily-driver default is
  off with AOSP's native lockdown ("Block connections without VPN") as the
  usable path.

Fail-open semantics are documented: if the daemon dies between re-applies,
previously applied rules persist; it retries every 10 s.

## Patch discipline

Patches apply with plain `git apply` against the pinned manifest. The
integrator: (1) verifies the tree is clean and at the pinned revisions,
(2) journals applied/absent state per patch, (3) aborts on the first conflict
*without* modifying the tree (no resets), (4) supports `--revert` of exactly
lenOS-owned changes. This mirrors the audited lenOS 2.8.1 integrator behavior
that proved safe in the field.
