# lenOS operational security playbook

lenOS enforces what software can enforce. This document is the rest — the
operational discipline that makes the enforced layer actually mean something.
It is written for realistic adversaries: commercial trackers, apps, network
observers, opportunistic seizure. It is not written for SIGINT-level
adversaries; nothing on a daily-driver phone is.

## The three honest layers

1. **Enforced by the OS** (duress wipe, BFU auto-reboot, MAC randomization,
   DNS enforcement, sensor permissions, no telemetry surfaces, verified
   boot with your key).
2. **Enforced by you** (SIM strategy, network choice, compartmentalization).
3. **Not enforceable at all** (radio-layer identity; see below).

## SIM strategy (the part software can't fix)

The carrier sees: IMSI (from the SIM), IMEI (from the modem NVRAM), cell
location, and every time the radio registers. No ROM changes this. What
actually works, in increasing commitment:

- **Separate the identity from the device.** A data-only prepaid eSIM bought
  without linking to your identity (where legal) is the strongest practical
  separation. Never put your personal SIM in the same phone you use for
  pseudonymous work — not even temporarily.
- **Airplane mode as the default state.** Everything sensitive is done over
  Wi-Fi; the radio wakes only when you choose. lenOS keeps no background
  connectivity checks that would betray this.
- **Wi-Fi calling off, VoLTE only, 2G/legacy fallback off** (carrier settings
  + the ROM's defaults). Legacy fallbacks are the weakest links.
- If a SIM must be present: accept that the carrier layer is identified, and
  move your anonymity boundary to the network layer (VPN over Wi-Fi, no SIM
  data usage).

## Network behavior

- Always-on VPN + "Block connections without VPN" (stock Android lockdown)
  is the daily-driver killswitch. lenOS's strict firewall is the escalated
  belt-and-braces for high-risk periods.
- lenOS blocks plaintext DNS fleet-wide. Pick a DoT provider you trust or
  route DNS through the VPN; both work, nothing leaks.
- Wi-Fi MAC is already per-connection. Do not defeat it by disabling
  randomization "for stability".
- Expect captive-portal and network-privacy implications when using the
  strict firewall; that is its documented tradeoff.

## Compartmentalization

- One device, one identity era. Do not carry the pseudonymous phone to
  places/events tied to your legal identity, and never log personal accounts
  into it "just once".
- Use Android's work profile (Shelter/Insular) for app-level isolation of
  anything that must never see your main apps.
- Payment, transit cards, Bluetooth pairing history and saved Wi-Fi networks
  are physical-world identity beacons. Keep them out of the pseudonymous
  profile.

## Browser and app layer

- Cromite ships as the browser; keep its strict mode on. For sensitive
  browsing, Tor Browser on Android is the reference; Mullvad-style VPNs are
  the speed/privacy middle ground.
- App-level fingerprinting of device model/performance is not fully solvable
  (see DESIGN.md); lenOS makes every lenOS device identical instead, so the
  "fingerprint" you present is shared with the whole fleet.

## Coercion and seizure

- Set a duress PIN in the lenOS app surface (Settings → Security) and know
  what it does: irreversible wipe, including eSIM profiles, without reboot.
- Automatic BFU reboot puts data at rest after your chosen window; keep it
  short enough to matter.
- Back up your signing keys OFFLINE, away from the phone, away from cloud
  accounts. Losing them after relock is unrecoverable.

## What this playbook cannot give you

- Protection against a targeted radio/RF analysis of your person.
- Anonymity while a SIM tied to you is registered in the device.
- Protection against compromise of your own opsec discipline.
- Security parity with GrapheneOS's exploit chain; lenOS chooses feature
  depth over their security breadth, on hardware they don't support.
