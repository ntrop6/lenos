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
| `LenosParts` | `app/LenosParts` | Local dashboard: theme-pack selection, notification corners/dividers, motion controls, launcher grid/icon-shape/themed-icon controls, links to the stock LineageOS status-bar panel and Launcher3 settings |
| Ember / Mint / Mono | `rro/LenosTheme*SystemUI` | Mutable SystemUI resource overlays: notification/scrim colors, QS corner radius and tile spacing |
| Ember / Mint / Mono | `rro/LenosTheme*Frameworks` | Mutable framework-res palettes: full Material 3 tonal palettes and dynamic color roles for light and dark themes |
| Quick Settings layout | `rro/LenosQs*` | Mutable SystemUI overlays for 3/5 columns and 3/5 expanded rows; the stock 4/4 layout needs no overlay |
| Notification styling | `rro/LenosNotify*` | Mutable SystemUI overlays: three corner radii (round/compact/square) and hidden group dividers; the stock 28dp/4dp radii and visible divider need no overlay |
| Privapp allowlist | `config/privapp-permissions-org.lenos.parts.xml` | Only `CHANGE_OVERLAY_PACKAGES` and `WRITE_SECURE_SETTINGS` |
| Product wiring | `config/lenos.mk` | Installs the app and the fourteen overlays on the product partition |

The theme packs are **preinstalled and disabled by default**. Selecting one
enables exactly one SystemUI overlay and one framework palette through
`OverlayManager`; selecting "Stock" disables all six. The Quick Settings layout
and notification styling overlays are independent of the theme: selecting the
stock layout or the stock notification style disables the corresponding
non-default overlays. Nothing is downloaded, and the app has no network
permission.

Selecting a pack also seeds Monet through
`Settings.Secure.THEME_CUSTOMIZATION_OVERLAY_PACKAGES`:
`android.theme.customization.system_palette` gets the pack's seed color,
`android.theme.customization.theme_style` gets its style, and
`android.theme.customization.color_source` is set to `preset` so a wallpaper
change does not clear the choice. This is the reliable accent path on Android
17: `ThemeOverlayController` builds its fabricated overlays at runtime, and
manifest priority is advisory for unconfigured overlays. The framework palettes
therefore act as a fallback when dynamic color is disabled. The original secure
values are backed up in the app's private preferences and restored when the user
selects "Stock"; a value is only restored if it still holds what this app wrote,
so a later wallpaper/preset choice is never overwritten.

The palette XML is static output from Material Color Utilities; there is no
runtime dependency on that library. If a pack ever misbehaves on a device, it
can be disabled without the app:

```bash
adb shell cmd overlay disable org.lenos.theme.ember.frameworks
adb shell cmd overlay disable org.lenos.theme.ember.systemui
```

Motion controls write the three standard Android `Settings.Global` animation
scales independently: `animator_duration_scale` (system animations),
`transition_animation_scale` (activity and fragment transitions) and
`window_animation_scale` (window animations). Each can be 1.0x (default), 1.25x,
0.75x, 0.5x or 0x; "Reset all to 1.0x" restores the defaults. The user can
change them again at any time, and accessibility/battery-saver behavior is
unchanged.

## Notification controls

Notification styling is split out of the theme packs so the two choices do not
race for the same Android 17 overlay resource. The theme packs still set
notification and scrim colors; the notification section owns the geometry:

| Choice | Overlay | Resources |
|---|---|---|
| System default | none | LineageOS `28dp` radius, `4dp` grouped radius |
| Round | `LenosNotifyCornersRound` | `24dp`, `6dp` |
| Compact | `LenosNotifyCornersCompact` | `16dp`, `4dp` |
| Square | `LenosNotifyCornersSquare` | `6dp`, `2dp` |

`LenosParts` enables exactly one corner overlay (or none) through
`OverlayManager`. "Hide dividers between grouped notifications" toggles
`LenosNotifyDividersHidden`, which sets `notification_divider_color` to
transparent. The divider view and its spacing are unchanged, so notification
layout and touch targets do not move. Both controls are independent of the
selected theme pack and of the Quick Settings layout.

## Launcher controls

LineageOS 24.0 ships its Launcher3 fork as `com.android.launcher3`. The launcher
exports `LauncherCustomizationProvider` at
`content://com.android.launcher3.grid_control` with the documented
`/list_options` query and `/default_grid` update. `LenosParts` reads the
available grid options (name, title, rows, columns, current selection) and
writes only the selected grid name. It does not open or modify the launcher's
workspace database and does not request `ACCESS_LAUNCHER_DATA`.

The same provider exposes `/shape_options` and `/shape` for the launcher icon
mask, and `/get_icon_themed`/`/set_icon_themed` for themed icons. `LenosParts`
lists the launcher's translated shape names, applies only the selected
`shape_key`, and toggles the themed-icon preference through `boolean_value`.
These are launcher-level preferences, not framework or SystemUI substitutions,
so they survive without an overlay and do not add another permission beyond
`GRID_CONTROL`.

The provider accepts either `BIND_WALLPAPER` or the signature-scoped
`com.android.launcher3.permission.GRID_CONTROL`. lenOS uses the narrow
permission: both apps are platform-signed, so it is granted at install without a
privileged-permission allowlist entry. If a derivative launcher does not expose
the provider or the permission is not granted, the grid and shape spinners
disable themselves and the dashboard falls back to the launcher's own settings
screen.

"Open launcher settings" starts
`android.intent.action.APPLICATION_PREFERENCES` against
`com.android.launcher3`, then falls back to `Settings.ACTION_HOME_SETTINGS` on
builds with a different home app. Notification dots and the remaining Home
options stay in that stock screen. Grid, shape and themed-icon queries and
updates run off the UI thread because the provider may start the launcher
process.

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
| Theme tokens | Full Material 3 palettes plus SystemUI colors/dimens via three local packs | Add a local pack manifest and user-defined seed; keep dynamic-color precedence explicit |
| Status bar | Link to LineageOS's existing clock/battery/network/brightness panel | Add Axion-style icon controls only where LineageOS has no equivalent |
| Quick Settings | 3/5 columns and 3/5 expanded rows via local overlays (rows apply to the paginated grid; the dual-shade infinite grid scrolls); theme pack controls tile shape/spacing | Split tile shape from the theme pack and add a compact/collapsed-rows control |
| Notifications | Independent corner radii and hidden group dividers; theme packs control notification/scrim colors | Add optional background/blur styling; blur stays device-dependent and off by default |
| Motion | Independent system, transition and window scales plus reset | Add higher-level presets only after A17 SystemUI hooks are reviewed |
| Lock screen | Not yet | Start with clock styles and local media-art styling; Lockscreen Studio is a later project |
| Launcher / Recents | Grid selection, icon shape and themed icons through Launcher3's grid-control provider, plus a link to the stock launcher settings | Recents is a separate risk |
| Dynamic Bar | Not yet | Local-only subset (media, timer, alarm, charging, torch); exclude sports/online feeds |

This slice still avoids framework Java and the security patches: it proves the
overlay/application architecture and gives the user visible controls using only
preinstalled resource overlays. Later slices add SystemUI and framework hooks
behind `LENOS_UI=1`/a dedicated patch series, with the same tests and no network
surface.

## Validation checklist

Source-level (runs without a device):

```bash
cd vendor/lenos
LENOS_WORKSPACE=/path/to/lineage python3 -m unittest tests.test_ui_customization -v
LENOS_WORKSPACE=/path/to/lineage bash tests/run-tests.sh
```

When a build/device is available:

1. Build `lenos_asteroids-user` with the stable series.
2. Confirm `LenosParts` and the fourteen overlays are installed:
   `adb shell pm list packages | grep -E 'lenos.parts|lenos.theme|lenos.qs|lenos.notify'`.
3. Open lenOS personalization and apply each pack; confirm the overlay list
   changes with `adb shell cmd overlay list --user 0 | grep -E 'lenos.theme|lenos.qs|lenos.notify'`.
   The SystemUI pack and the framework palette for the selected theme must both
   be enabled.
4. Confirm notification/QS colors plus the global accent change (Settings,
   Dialer, Files), then select Stock and confirm the resources return to the
   LineageOS defaults. The seeded values are visible with
   `adb shell settings get secure theme_customization_overlay_packages`.
5. Select 3, 5, and the default Quick Settings columns/rows; confirm the grid
   changes and that only one overlay per dimension is enabled.
6. Select each notification corner choice and confirm the shade reflects it;
   toggle "Hide dividers" on a grouped notification and confirm the lines
   disappear without changing the row height. Confirm only one notification
   corner overlay is enabled at a time.
7. Open the Launcher section and change the Home/All apps grid. Confirm the
   spinner lists the launcher's grid options and that the workspace rearranges
   immediately. Change the icon shape and toggle themed icons; confirm both are
   reflected on the Home screen and in All apps. If a spinner is disabled,
   confirm "Open launcher settings" still reaches the stock launcher
   preferences.
8. Change each motion scale independently and verify only that `Settings.Global`
   key changes; use "Reset all to 1.0x" and verify all three return to `1.0`.
9. Confirm the app has no network access and no `INTERNET` permission:
   `adb shell dumpsys package org.lenos.parts | grep -i internet` should be empty.
10. Confirm the launcher grid permission is the narrow one, not the wallpaper
    permission: `adb shell dumpsys package org.lenos.parts | grep -E
    'GRID_CONTROL|BIND_WALLPAPER'` should list only `GRID_CONTROL`.
11. If SystemUI becomes unusable after a pack change, disable the framework
    overlay and the SystemUI overlay with `cmd overlay disable` from `adb` (see
    above) and reboot.

## Attribution

No AxionOS source was copied into this slice. The design is an independent
local implementation of common customization ideas. If a later patch reuses
Axion code, the file must retain its Apache-2.0 header and the commit must name
the upstream repository and revision; assets require a separate
redistribution check.
