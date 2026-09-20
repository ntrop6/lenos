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
