# EXPERIMENTAL — vetted next steps, not yet integrated

Nothing in this file is wired into the build. These are the next features
worth porting, in priority order, with the exact place to implement them.
Do not cherry-pick blindly: each item must be re-generated as a patch
against the pinned revisions in `manifest/lenos-asteroids.xml`.

## 1. ANDROID_ID (SSAID) tied to app-install lifetime

GrapheneOS direction (their FAQ lists it as planned): SSAID should rotate
when an app is (re)installed, so uninstall/reinstall breaks a tracking key.

- Implementation point: `frameworks/base/packages/SettingsProvider`
  (`SettingsProviderImpl`, the SSAID maintenance path).
- Upstream reference: GrapheneOS platform discussions; no public commit to
  copy yet — write it, don't paste it.
- Risk: settings database migrations; test upgrade paths.

## 1b. Longer lockscreen passwords (128 chars)

GrapheneOS raises the password cap from 16 to 128. Bounded investigation
against the pinned tree found no length cap in `LockSettingsService`,
`LockPatternUtils`, `LockscreenCredential`, or `ChooseLockPassword`; locate
the actual enforcement site (likely keyguard input or `PasswordMetrics`)
before authoring. Do not guess.

## 2. Cromite as the system WebView

`arm64_SystemWebView.apk` exists in the pinned Cromite release. Swapping the
WebView hardens every app that renders web content, not just the browser.

- Requirements: `PRODUCT_PACKAGES` replacement of the stock WebView, matching
  provider expectations (`com.android.webview` package name compatibility),
  and acceptance testing with apps that use the WebView.
- The pin and fetch script already support the asset.

## 3. NTP/connectivity-check normalization

Current state: captive portal detection stays enabled for daily drivability
and rides the VPN when one is up. The strict alternative:

- Point `captive_portal_http_url`/`https_url` Settings.Global at a
  neutral generate-204 endpoint of the user's choice, or
- Ship an RRO overlay for `config_captivePortalDetectionEnabled` (false) for
  users who prefer detection off fleet-wide.

## 4. Known-neighbor Wi-Fi BSSID randomization knobs

Stock Android already supports non-persistent MAC mode; patch 0010 defaults
per-connection. A follow-up: randomize per-connection even on reconnects to
*previously seen* SSIDs (the "known neighbor" leak class) by defaulting the
WifiTrackerLib mode to the strictest value in all paths.

## 5. Inter-app carrier-info normalization

TelephonyManager surfaces carrier name, ISO country, network type to any app.
A framework patch could normalize display values (keep SIM function, remove
locale/carrier correlation value for non-telephony callers). Scope: touch
only what apps read for correlation, not what Dialer/SMS need. This is the
in-tree replacement for the PrivacyMask/Xposed approach — stronger, native,
unbypassable by NDK apps.

## 6. Tor as a system component

Orbot-style integration as a built-in profile ("network privacy mode") that
combines strict firewall + SOCKS routing for whitelisted apps. Large effort;
design before code.

## 7. Known rough edges flagged by the pre-build audit

- **Auto-BFU failure is not surfaced in the UI.** Patch 0008 deliberately
  fail-stops (LOG(ERROR), feature disabled) instead of crashing init when
  `timer_create` fails, but patch 0013's UI cannot observe the failure and
  can display an armed timer while none is. Fix: have init set an error
  property the panel reads.
- **On-device sepolicy confirmation.** The `lenos_netd` domain was written
  conservatively (mirroring what pinned netd.te grants for iptables: generic
  `netlink_socket`, `net_admin/net_raw`), but first-boot AVCs are still
  expected. After booting: `adb shell dmesg | grep -E 'avc.*lenos_netd'`,
  feed through audit2allow, iterate. The daemon is iptables-only by design
  (no binder, no ART), so the grant surface is small.
- **System app removal is one-way from the panel.** `pm uninstall --user 0`
  keeps the APK on the read-only partition; restore with
  `adb shell pm install-existing --user 0 <package>` from a PC. The panel's
  denylist covers critical components but is not exhaustive — audit the list
  before removing anything you cannot afford to lose.
- **LTE-only persistence is device-dependent.** The switch records its
  intent in Settings.Global (`lenos_lte_only`), but whether telephony
  preserves the reason-mask across reboots must be verified on hardware; if
  the radio resets it, re-toggling from the panel re-applies it.

## Explicitly rejected

- IMEI/IMSI spoofing: not feasible in software on SM7635, illegal in many
  jurisdictions, breaks emergency services. Rejected.
- Per-device randomized model/fingerprint: consistency-check failure; makes
  devices MORE unique. Rejected (DESIGN.md §2).
- lenOS-identifying strings in the system image (display id, `ro.lenos.*`
  props, a lenOS settings *app package*): they shrink the herd. Rejected;
  the brand lives in build-time artifacts, the Settings panel and the boot
  animation only.
- Killing 2G/SMS fallback without user toggle: daily-drivability violation.
- Shipped GMS or microG: rejected fleet-wide; those who need them can sideload
  and accept the tradeoff consciously.
- A publicly shared platform signing key (maximal herd, zero security):
  anyone could sign platform-privileged code against the device. Rejected.

## Candidate follow-ups requiring verification against the build

- **Neutralize `ro.product.name` to the stock value.** The global
  `ro.product.name` currently reads `lenos_asteroids` (as upstream's
  `lineage_asteroids`); per-partition product props already spoof to the
  stock values. Verify how buildinfo maps `PRODUCT_BUILD_PROP_OVERRIDES` on
  23.2 before attempting, and re-check any consistency check that compares
  fingerprint vs product name.
- **Shared per-identity signing set.** Generate the key set once, reuse
  across all devices you control; signature herd = your own device fleet.
  Tradeoff: one leaked key burns the fleet.
