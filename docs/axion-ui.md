# Local personalization (Axion-inspired)

Status: **source-complete, not built or device-validated.** This is the first
slice of the lenOS visual-customization layer. It deliberately does not import
AxionOS source; it establishes the local-only architecture and the first
user-visible controls.

Base: LineageOS 24.0 / Android 17 (`asteroids`).

## Why this is a port, not a merge

AxionOS stable is based on LineageOS 23.2 / Android 16. Its
`android_frameworks_base` has no `lineage-24.0` branch, its 24.0 manifest still
defaults most projects to 23.2, and the framework fork is hundreds of commits
ahead of LineageOS 23.2. Merging it would replace lenOS's security baseline and
would also bring in `vendor/gms`, the online Theme Store, online configuration
and Play Integrity/TrickyStore components that lenOS explicitly does not ship.

The practical route is therefore:

1. keep lenOS on the pinned LineageOS 24.0 tree;
2. reuse small, self-contained Apache-2.0-compatible pieces only after review;
3. reimplement the visual behavior locally where the Axion code is tied to its
   framework fork, its online services or its security model;
4. keep every new component free of `INTERNET`, GMS and telemetry.

## What ships in this slice

| Component | Path | Behavior |
|---|---|---|
| `LenosParts` | `app/LenosParts` | Local dashboard: theme-pack selection, motion presets, link to the stock LineageOS status-bar panel |
| Ember / Mint / Mono | `rro/LenosTheme*SystemUI` | Mutable SystemUI resource overlays: notification/scrim colors, notification corner radii, QS corner radius and tile spacing |
| Privapp allowlist | `config/privapp-permissions-org.lenos.parts.xml` | Only `CHANGE_OVERLAY_PACKAGES` and `WRITE_SECURE_SETTINGS` |
| Product wiring | `config/lenos.mk` | Installs the app and the three overlays on the product partition |

The theme packs are **preinstalled and disabled by default**. Selecting one
enables exactly one SystemUI overlay through `OverlayManager`; selecting
"Stock" disables all three. Nothing is downloaded, and the app has no network
permission.

Motion presets write the standard Android `Settings.Global` animation scales
(`animator_duration_scale`, `transition_animation_scale`,
`window_animation_scale`). The "Off" preset sets all three to `0`; the user can
change them again at any time, and accessibility/battery-saver behavior is
unchanged.

## Local-only boundary

The following are **not** part of this work and must not be added without a
separate review and an explicit product decision:

* AxThemeStore, the online Theme Store and any theme-download endpoint;
* `vendor/gms`, Play Integrity Fix, TrickyStore, attestation spoofing;
* `axion_online_configs`, telemetry, analytics or remote feature flags;
* weather/smartspace services that require a network call;
* PC Mode/freeform desktop, app sandboxing, root hiding and app spoofing;
* any app-level `INTERNET` permission or network client in the customization
  stack.

The test suite enforces the static part of this boundary: no `INTERNET`
permission in the new app or overlays, no network APIs in the Java source, and
no GMS/Theme Store/Play Integrity references.

## Feature map and next slices

| Area | Current state | Next step |
|---|---|---|
| Theme tokens | SystemUI colors/dimens via three local packs | Add framework accent overlays and a local pack manifest; keep dynamic-color precedence explicit |
| Status bar | Link to LineageOS's existing clock/battery/network/brightness panel | Add Axion-style icon controls only where LineageOS has no equivalent |
| Quick Settings | Theme pack controls tile shape/spacing | Add columns/rows and tile-shape controls without duplicating LineageOS settings |
| Notifications | Theme pack controls corners/colors | Add optional background/blur styling; blur stays device-dependent and off by default |
| Motion | Three scales plus off | Add per-surface animation presets only after A17 SystemUI hooks are reviewed |
| Lock screen | Not yet | Start with clock styles and local media-art styling; Lockscreen Studio is a later project |
| Launcher / Recents | Not yet | Port small Launcher3 preferences first; Recents is a separate risk |
| Dynamic Bar | Not yet | Local-only subset (media, timer, alarm, charging, torch); exclude sports/online feeds |

The first vertical slice intentionally avoids framework code: it proves the
overlay/application architecture and gives the user visible controls without
touching the security patches or SystemUI Java. Later slices add SystemUI and
framework hooks behind `LENOS_UI=1`/a dedicated patch series, with the same
tests and no network surface.

## Validation checklist

Source-level (runs without a device):

```bash
cd vendor/lenos
LENOS_WORKSPACE=/path/to/lineage python3 -m unittest tests.test_ui_customization -v
LENOS_WORKSPACE=/path/to/lineage bash tests/run-tests.sh
```

When a build/device is available:

1. Build `lenos_asteroids-user` with the stable series.
2. Confirm `LenosParts` and the three overlays are installed:
   `adb shell pm list packages | grep -E 'lenos.parts|lenos.theme'`.
3. Open lenOS personalization and apply each pack; confirm the overlay list
   changes with `adb shell cmd overlay list --user 0 | grep lenos.theme`.
4. Confirm notification/QS corner and color changes, then select Stock and
   confirm the resources return to the LineageOS defaults.
5. Change each motion preset and verify the three `Settings.Global` values.
6. Confirm the app has no network access and no `INTERNET` permission:
   `adb shell dumpsys package org.lenos.parts | grep -i internet` should be empty.

## Attribution

No AxionOS source was copied into this slice. The design is an independent
local implementation of common customization ideas. If a later patch reuses
Axion code, the file must retain its Apache-2.0 header and the commit must name
the upstream repository and revision; assets require a separate
redistribution check.
