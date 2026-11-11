"""Local-only visual customization (Settings panel + SystemUI overlays).

Feature contract (see docs/axion-ui.md):

* The personalization layer is a local panel inside Settings and
  preinstalled resource overlays. It has no network code, account, telemetry
  or Google/GMS/Play Integrity code path.
* Theme packs are mutable SystemUI overlays. The lenOS Settings panel enables
  exactly one pack (or none) through OverlayManager.
* Notification corner radius and grouped-notification dividers are separate
  mutable SystemUI overlays, independent of the theme packs.
* The status bar clock size is a separate mutable SystemUI overlay choice.
  Clock position, seconds, AM/PM, battery and network controls stay in the
  stock LineageOS panel; the lock-screen dynamic clock stays in stock Settings.
* Motion controls write only the standard Android animation-scale settings,
  one surface at a time, plus an explicit reset.
* The launcher section uses Launcher3's exported grid-control provider through
  its signature-scoped GRID_CONTROL permission, with the stock Home settings
  intent as the fallback.
* The stock LineageOS status bar panel remains the source of truth for clock,
  battery, network-traffic and brightness controls.
"""
from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET

from harness import VENDOR, LenosPatchTest

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

THEMES = {
    "LenosThemeEmberSystemUI": "org.lenos.theme.ember.systemui",
    "LenosThemeMintSystemUI": "org.lenos.theme.mint.systemui",
    "LenosThemeMonoSystemUI": "org.lenos.theme.mono.systemui",
}

FRAMEWORK_THEMES = {
    "LenosThemeEmberFrameworks": "org.lenos.theme.ember.frameworks",
    "LenosThemeMintFrameworks": "org.lenos.theme.mint.frameworks",
    "LenosThemeMonoFrameworks": "org.lenos.theme.mono.frameworks",
}

QS_OVERLAYS = {
    "LenosQsColumns3": ("org.lenos.qs.columns3", "columns", 3),
    "LenosQsColumns5": ("org.lenos.qs.columns5", "columns", 5),
    "LenosQsRows3": ("org.lenos.qs.rows3", "rows", 3),
    "LenosQsRows5": ("org.lenos.qs.rows5", "rows", 5),
}

NOTIFY_CORNER_OVERLAYS = {
    "LenosNotifyCornersRound": (
        "org.lenos.notify.corners.round", "24dp", "6dp"),
    "LenosNotifyCornersCompact": (
        "org.lenos.notify.corners.compact", "16dp", "4dp"),
    "LenosNotifyCornersSquare": (
        "org.lenos.notify.corners.square", "6dp", "2dp"),
}
NOTIFY_DIVIDERS_OVERLAY = "LenosNotifyDividersHidden"
NOTIFY_DIVIDERS_PACKAGE = "org.lenos.notify.dividers.hidden"

CLOCK_OVERLAYS = {
    "LenosClockCompact": ("org.lenos.clock.compact", "12sp"),
    "LenosClockLarge": ("org.lenos.clock.large", "16sp"),
    "LenosClockXLarge": ("org.lenos.clock.xlarge", "18sp"),
}

BANNED_JAVA = (
    "java.net.",
    "HttpURLConnection",
    "OkHttp",
    "new Socket",
    "Firebase",
    "com.google.android.gms",
    "PlayIntegrity",
    "TrickyStore",
    "axthemestore",
    "AxionParts",
)

BANNED_APP_TEXT = (
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.ACCESS_WIFI_STATE",
    "android.permission.USE_BIOMETRIC",
    "com.google.android.gms",
    "firebase",
    "playintegrity",
    "trickystore",
    "axthemestore",
)


def parse_xml(rel: str) -> ET.Element:
    return ET.parse(VENDOR / rel).getroot()


class SettingsPanelTest(LenosPatchTest):
    """Apply the Settings series and assert on the merged lenOS panel."""

    PROJECT = "packages/apps/Settings"
    PATCHES = [
        "0001-lenos-ext-settings-ui.patch",
        "0002-lenos-disable-user-apps.patch",
        "0003-lenos-user-app-installs.patch",
        "0004-lenos-panel.patch",
    ]
    PANEL = "src/com/android/settings/lenos/LenosSettingsFragment.java"
    DURESS = "src/com/android/settings/lenos/LenosDuressFragment.java"
    BRIDGE = "src/com/android/settings/lenos/LenosLockBridge.java"
    MANIFEST = "AndroidManifest.xml"
    TOP_LEVEL = "res/xml/top_level_settings.xml"
    PANEL_XML = "res/xml/lenos_settings.xml"
    STRINGS = "res/values/strings_lenos.xml"
    LAYOUT = "res/layout/lenos_duress_fragment.xml"
    ICON = "res/drawable/ic_lenos_settings.xml"


class TestSettingsPanel(SettingsPanelTest):
    def test_manifest_grants_the_narrow_permissions(self):
        root = ET.fromstring(self.text(self.MANIFEST))
        permissions = {
            node.get(f"{ANDROID_NS}name")
            for node in root.findall("uses-permission")
        }
        for required in (
            "android.permission.CHANGE_OVERLAY_PACKAGES",
            "android.permission.WRITE_SECURE_SETTINGS",
            "android.permission.ACCESS_KEYGUARD_SECURE_STORAGE",
            "com.android.launcher3.permission.GRID_CONTROL",
        ):
            self.assertIn(required, permissions)
        self.assertNotIn("android.permission.BIND_WALLPAPER", permissions,
                         "the broad wallpaper permission is not needed")

    def test_top_level_entry_opens_the_panel(self):
        root = ET.fromstring(self.text(self.TOP_LEVEL))
        entries = [
            node for node in root.iter()
            if node.get(f"{ANDROID_NS}key") == "top_level_lenos"
        ]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(
            entry.get(f"{ANDROID_NS}fragment"),
            "com.android.settings.lenos.LenosSettingsFragment")
        self.assertEqual(entry.get(f"{ANDROID_NS}title"),
                         "@string/lenos_settings_title")

    def test_panel_resources_are_well_formed(self):
        for rel in (self.TOP_LEVEL, self.PANEL_XML, self.STRINGS,
                    self.LAYOUT, self.ICON):
            with self.subTest(resource=rel):
                self.assert_xml(rel)

    def test_source_uses_local_overlays_and_settings_only(self):
        body = self.text(self.PANEL)
        for needle in (
            "OverlayManager",
            "Process.myUserHandle()",
            "getOverlayInfosForTarget(",
            "installedPackages(",
            "systemUiInstalled.contains(",
            "org.lenos.theme.ember.systemui",
            "org.lenos.theme.mint.systemui",
            "org.lenos.theme.mono.systemui",
            "org.lenos.theme.ember.frameworks",
            "org.lenos.theme.mint.frameworks",
            "org.lenos.theme.mono.frameworks",
            "org.lenos.qs.columns3",
            "org.lenos.qs.columns5",
            "org.lenos.qs.rows3",
            "org.lenos.qs.rows5",
            "org.lenos.notify.corners.round",
            "org.lenos.notify.corners.compact",
            "org.lenos.notify.corners.square",
            "org.lenos.notify.dividers.hidden",
            "org.lenos.clock.compact",
            "org.lenos.clock.large",
            "org.lenos.clock.xlarge",
            "configureQuickSettingsPreferences(",
            "configureNotificationPreferences(",
            "configureClockPreference(",
            "applyOverlayChoice(",
            "applyNotifyDividers(",
            "refreshClockPreference(",
            "openLockScreenSettings(",
            "Settings.ACTION_LOCKSCREEN_SETTINGS",
            "Settings.ACTION_SECURITY_SETTINGS",
            "applyLauncherGrid(",
            "applyLauncherShape(",
            "applyLauncherThemedIcons(",
            "openLauncherSettings(",
            "Intent.ACTION_APPLICATION_PREFERENCES",
            "Settings.ACTION_HOME_SETTINGS",
            "com.android.launcher3.grid_control",
            "applyMonetSeed(",
            "restoreMonetSeed(",
            "backupMonetValue(",
            "Settings.Secure.THEME_CUSTOMIZATION_OVERLAY_PACKAGES",
            "android.theme.customization.system_palette",
            "android.theme.customization.theme_style",
            "android.theme.customization.color_source",
            "C96A1E",
            "2FA37C",
            "6B6F76",
            "VIBRANT",
            "TONAL_SPOT",
            "MONOCHROMATIC",
            "Settings.Global.ANIMATOR_DURATION_SCALE",
            "Settings.Global.TRANSITION_ANIMATION_SCALE",
            "Settings.Global.WINDOW_ANIMATION_SCALE",
            "org.lineageos.lineageparts.STATUS_BAR_SETTINGS",
        ):
            self.assertIn(needle, body)
        for banned in BANNED_JAVA:
            self.assertNotIn(banned, body)
        self.assertNotIn("LenosParts", body)
        self.assertNotIn("LenosSecurity", body)

    def test_duress_ui_stays_inside_settings(self):
        duress = self.text(self.DURESS)
        bridge = self.text(self.BRIDGE)
        for needle in (
            "extends Fragment",
            "FLAG_SECURE",
            "setDuress(",
            "hasDuress(",
            "deleteDuress(",
            "zeroize(",
        ):
            self.assertIn(needle, duress)
        for needle in (
            "LockPatternUtils",
            "LockscreenCredential",
            "setDuressCredentials",
            "hasDuressCredentials",
            "deleteDuressCredentials",
        ):
            self.assertIn(needle, bridge)
        for banned in BANNED_JAVA:
            self.assertNotIn(banned, duress)
            self.assertNotIn(banned, bridge)

    def test_java_parses(self):
        for rel in (self.PANEL, self.DURESS, self.BRIDGE):
            with self.subTest(source=rel):
                self.assert_java_syntax(rel)


class TestMonetSeeding(SettingsPanelTest):
    def test_seed_and_style_arrays_are_aligned(self):
        body = self.text(self.PANEL)
        seeds_match = re.search(r"THEME_SEEDS = \{(.*?)\};", body, re.S)
        styles_match = re.search(r"THEME_STYLES = \{(.*?)\};", body, re.S)
        self.assertIsNotNone(seeds_match)
        self.assertIsNotNone(styles_match)
        seeds = re.findall(r'"([0-9A-F]{6})"', seeds_match.group(1))
        styles = re.findall(r'"([A-Z_]+)"', styles_match.group(1))
        self.assertEqual(seeds, ["C96A1E", "2FA37C", "6B6F76"])
        self.assertEqual(
            styles, ["VIBRANT", "TONAL_SPOT", "MONOCHROMATIC"])

    def test_stock_restores_only_values_the_panel_wrote(self):
        body = self.text(self.PANEL)
        self.assertIn("restoreMonetSeed(", body)
        self.assertIn("restoreMonetValue(", body)
        self.assertIn("owned.equals(current)", body,
                      "a user's later wallpaper/preset choice must survive")
        self.assertIn(
            "Settings.Secure.THEME_CUSTOMIZATION_OVERLAY_PACKAGES", body)
        self.assertIn('COLOR_SOURCE_PRESET = "preset"', body)


class TestThemeOverlays(unittest.TestCase):
    def test_overlays_are_mutable_systemui_packages(self):
        for name, package in THEMES.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"),
                    "com.android.systemui",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false",
                    "theme packs must be user-toggleable, not static",
                )
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)
                self.assertNotIn("device_specific", build)

    def test_overlays_define_distinct_visual_values(self):
        scrims = set()
        for name in THEMES:
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/theme.xml")
                values = {
                    node.get("name"): (node.text or "").strip()
                    for node in root
                }
                for resource in (
                    "notification_scrim_base",
                    "notification_legacy_background_color",
                    "status_bar_clock_color",
                    "qs_tile_divider",
                    "qs_corner_radius",
                    "qs_tile_margin_horizontal",
                ):
                    self.assertIn(resource, values)
                # Notification radii belong to the independent notification
                # overlays; a pack must not race them for the same resource.
                self.assertNotIn("notification_corner_radius", values)
                self.assertNotIn("notification_corner_radius_small", values)
                scrims.add(values["notification_scrim_base"])
        self.assertEqual(len(scrims), len(THEMES),
                         "each pack must have a distinct notification scrim")

    def test_no_network_or_remote_code_in_overlay_sources(self):
        for name in (*THEMES, *FRAMEWORK_THEMES, *QS_OVERLAYS,
                     *NOTIFY_CORNER_OVERLAYS, NOTIFY_DIVIDERS_OVERLAY,
                     *CLOCK_OVERLAYS):
            for path in (VENDOR / f"rro/{name}").rglob("*"):
                if not path.is_file():
                    continue
                body = path.read_text(encoding="utf-8", errors="replace")
                for banned in BANNED_APP_TEXT:
                    self.assertNotIn(banned.lower(), body.lower(),
                                     f"{path}: {banned}")


class TestFrameworkThemeOverlays(unittest.TestCase):
    KEY_ROLES = (
        "system_accent1_100_light",
        "system_accent1_100_dark",
        "system_accent1_500_light",
        "system_accent1_500_dark",
        "system_neutral1_500_light",
        "system_neutral1_500_dark",
        "system_primary_light",
        "system_primary_dark",
        "system_on_primary_light",
        "system_on_primary_dark",
        "system_surface_light",
        "system_surface_dark",
        "system_on_surface_light",
        "system_on_surface_dark",
    )

    def test_overlays_are_mutable_framework_packages(self):
        for name, package in FRAMEWORK_THEMES.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"), "android")
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false",
                    "framework palettes must be user-toggleable",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}priority"), "1000",
                    "advisory only; the Monet seed is the reliable accent path",
                )
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)

    def test_palette_sets_are_complete_and_distinct(self):
        reference = None
        primary_tones = set()
        for name in FRAMEWORK_THEMES:
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/colors.xml")
                values = {
                    node.get("name"): (node.text or "").strip()
                    for node in root
                }
                self.assertEqual(len(values), 236,
                                 "every pack must define the same palette")
                for role in self.KEY_ROLES:
                    self.assertIn(role, values)
                for role, value in values.items():
                    self.assertRegex(
                        value, r"^#[0-9A-F]{8}$",
                        f"{name}: invalid color for {role}",
                    )
                if reference is None:
                    reference = set(values)
                else:
                    self.assertEqual(set(values), reference)
                primary_tones.add(values["system_primary_light"])
        self.assertEqual(
            len(primary_tones), len(FRAMEWORK_THEMES),
            "each pack must generate a distinct primary palette",
        )


class TestQuickSettingsOverlays(unittest.TestCase):
    def test_overlays_are_mutable_systemui_packages(self):
        for name, (package, kind, value) in QS_OVERLAYS.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"),
                    "com.android.systemui",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false")
                self.assertEqual(
                    node.get(f"{ANDROID_NS}priority"), "200")
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)

    def test_overlays_override_the_expected_grid_resources(self):
        for name, (_, kind, value) in QS_OVERLAYS.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/config.xml")
                values = {
                    node.get("name"): int((node.text or "").strip())
                    for node in root
                }
                if kind == "columns":
                    self.assertEqual(
                        values,
                        {
                            "quick_settings_infinite_grid_num_columns": value,
                            "quick_settings_dual_shade_num_columns": value,
                            "quick_settings_split_shade_num_columns": value,
                        },
                    )
                else:
                    self.assertEqual(
                        values,
                        {"quick_settings_paginated_grid_num_rows": value},
                    )


class TestNotificationOverlays(unittest.TestCase):
    def test_corner_overlays_are_mutable_systemui_packages(self):
        for name, (package, radius, small) in NOTIFY_CORNER_OVERLAYS.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"),
                    "com.android.systemui",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false")
                self.assertEqual(
                    node.get(f"{ANDROID_NS}priority"), "200")
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)

                values = {
                    child.get("name"): (child.text or "").strip()
                    for child in parse_xml(
                        f"rro/{name}/res/values/dimens.xml")
                }
                self.assertEqual(
                    values,
                    {
                        "notification_corner_radius": radius,
                        "notification_corner_radius_small": small,
                    },
                )

    def test_corner_overlays_are_distinct(self):
        radii = {
            values[1:]
            for values in NOTIFY_CORNER_OVERLAYS.values()
        }
        self.assertEqual(len(radii), len(NOTIFY_CORNER_OVERLAYS),
                         "each corner overlay must have a distinct radius")

    def test_divider_overlay_hides_only_the_divider_color(self):
        root = parse_xml(
            f"rro/{NOTIFY_DIVIDERS_OVERLAY}/AndroidManifest.xml")
        self.assertEqual(root.get("package"), NOTIFY_DIVIDERS_PACKAGE)
        node = root.find("overlay")
        self.assertIsNotNone(node)
        self.assertEqual(
            node.get(f"{ANDROID_NS}targetPackage"), "com.android.systemui")
        self.assertEqual(node.get(f"{ANDROID_NS}isStatic"), "false")
        self.assertEqual(node.get(f"{ANDROID_NS}priority"), "200")
        self.assertEqual(
            root.find("application").get(f"{ANDROID_NS}hasCode"), "false")

        build = (VENDOR / f"rro/{NOTIFY_DIVIDERS_OVERLAY}/Android.bp").read_text()
        self.assertIn("runtime_resource_overlay", build)
        self.assertIn(f'name: "{NOTIFY_DIVIDERS_OVERLAY}"', build)
        self.assertIn("product_specific: true", build)
        self.assertIn('certificate: "platform"', build)

        values = {
            child.get("name"): (child.text or "").strip()
            for child in parse_xml(
                f"rro/{NOTIFY_DIVIDERS_OVERLAY}/res/values/colors.xml")
        }
        self.assertEqual(values, {"notification_divider_color": "#00000000"})


class TestNotificationControls(SettingsPanelTest):
    def test_corners_and_dividers_have_independent_controls(self):
        body = self.text(self.PANEL)
        for needle in (
            "NOTIFY_CORNER_VALUES",
            "NOTIFY_CORNER_PACKAGES",
            "org.lenos.notify.corners.round",
            "org.lenos.notify.corners.compact",
            "org.lenos.notify.corners.square",
            "NOTIFY_DIVIDERS_PACKAGE",
            "org.lenos.notify.dividers.hidden",
            "configureNotificationPreferences(",
            "refreshNotificationPreferences(",
            "applyOverlayChoice(",
            "applyNotifyDividers(",
        ):
            self.assertIn(needle, body)

    def test_notification_controls_do_not_write_theme_pack_resources(self):
        body = self.text(self.PANEL)
        # Radius choices are separate overlays; the theme-pack selector must
        # not also set the notification radii.
        self.assertNotIn("notification_corner_radius", body)
        self.assertNotIn("notification_corner_radius_small", body)


class TestClockOverlays(unittest.TestCase):
    def test_overlays_are_mutable_systemui_packages(self):
        for name, (package, size) in CLOCK_OVERLAYS.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"),
                    "com.android.systemui",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false")
                self.assertEqual(
                    node.get(f"{ANDROID_NS}priority"), "200")
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)

                values = {
                    child.get("name"): (child.text or "").strip()
                    for child in parse_xml(
                        f"rro/{name}/res/values/dimens.xml")
                }
                self.assertEqual(
                    values, {"status_bar_clock_size": size})

    def test_overlays_are_distinct(self):
        sizes = {values[1] for values in CLOCK_OVERLAYS.values()}
        self.assertEqual(len(sizes), len(CLOCK_OVERLAYS),
                         "each clock-size overlay must have a distinct size")

    def test_theme_packs_do_not_set_the_clock_size(self):
        for name in THEMES:
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/theme.xml")
                names = {node.get("name") for node in root}
                self.assertNotIn(
                    "status_bar_clock_size", names,
                    "clock size belongs to the dedicated overlays",
                )


class TestStatusBarControls(SettingsPanelTest):
    def test_clock_size_is_a_separate_overlay_choice(self):
        body = self.text(self.PANEL)
        for needle in (
            "CLOCK_VALUES",
            "CLOCK_PACKAGES",
            "org.lenos.clock.compact",
            "org.lenos.clock.large",
            "org.lenos.clock.xlarge",
            "configureClockPreference(",
            "refreshClockPreference(",
            "applyOverlayChoice(",
        ):
            self.assertIn(needle, body)
        strings = self.text(self.STRINGS)
        self.assertIn("System default (14 sp)", strings)
        self.assertIn("Compact (12 sp)", strings)
        self.assertIn("Extra large (18 sp)", strings)

    def test_stock_clock_and_battery_settings_are_not_duplicated(self):
        body = self.text(self.PANEL)
        for key in (
            "clock_seconds",
            "lockscreen_use_double_line_clock",
            "status_bar_show_battery_percent",
            "status_bar_am_pm",
        ):
            self.assertNotIn(
                key, body,
                "the stock panel remains the only writer for this setting",
            )
        self.assertNotIn("LineageSettings", body)

    def test_lock_screen_shortcut_uses_the_stock_intent(self):
        body = self.text(self.PANEL)
        for needle in (
            "Settings.ACTION_LOCKSCREEN_SETTINGS",
            "Settings.ACTION_SECURITY_SETTINGS",
            "openLockScreenSettings(",
        ):
            self.assertIn(needle, body)


class TestMotionControls(SettingsPanelTest):
    def test_surfaces_have_independent_controls(self):
        body = self.text(self.PANEL)
        for needle in (
            "configureMotionPreference(KEY_MOTION_ANIMATOR",
            "configureMotionPreference(KEY_MOTION_TRANSITION",
            "configureMotionPreference(KEY_MOTION_WINDOW",
            "Settings.Global.ANIMATOR_DURATION_SCALE",
            "Settings.Global.TRANSITION_ANIMATION_SCALE",
            "Settings.Global.WINDOW_ANIMATION_SCALE",
            "applyMotion(settingKey, scale",
            "resetMotion(",
            'return "System animations";',
            'return "Transition animations";',
            'return "Window animations";',
        ):
            self.assertIn(needle, body)

    def test_no_master_preset_rewrites_all_surfaces(self):
        body = self.text(self.PANEL)
        self.assertNotIn("applyMotion(MOTION_VALUES", body,
                         "the old master preset must not overwrite every scale")


class TestLauncherIntegration(SettingsPanelTest):
    def test_grid_control_permission_is_narrow_and_signature_scoped(self):
        root = ET.fromstring(self.text(self.MANIFEST))
        permissions = {
            node.get(f"{ANDROID_NS}name")
            for node in root.findall("uses-permission")
        }
        self.assertIn(
            "com.android.launcher3.permission.GRID_CONTROL", permissions)
        self.assertNotIn("android.permission.BIND_WALLPAPER", permissions,
                         "the broad wallpaper permission is not needed")

    def test_grid_provider_uses_the_documented_contract(self):
        body = self.text(self.PANEL)
        for needle in (
            "com.android.launcher3.grid_control",
            '"/list_options"',
            '"/default_grid"',
            '"name"',
            '"grid_title"',
            '"rows"',
            '"cols"',
            '"is_default"',
            "ContentValues",
            "getContentResolver().update(",
        ):
            self.assertIn(needle, body)
        # The grid provider is the supported API; never touch the launcher's
        # workspace database or ask for ACCESS_LAUNCHER_DATA.
        self.assertNotIn("LauncherProvider", body)
        self.assertNotIn("ACCESS_LAUNCHER_DATA", body)

    def test_shape_and_themed_icon_contract(self):
        body = self.text(self.PANEL)
        for needle in (
            '"/shape_options"',
            '"/shape"',
            '"/get_icon_themed"',
            '"/set_icon_themed"',
            '"shape_key"',
            '"shape_title"',
            '"boolean_value"',
            "applyLauncherShape(",
            "applyLauncherThemedIcons(",
        ):
            self.assertIn(needle, body)

    def test_launcher_settings_intent_has_a_stock_fallback(self):
        body = self.text(self.PANEL)
        for needle in (
            "Intent.ACTION_APPLICATION_PREFERENCES",
            "setPackage(LAUNCHER_PACKAGE)",
            "Settings.ACTION_HOME_SETTINGS",
            "openLauncherSettings(",
            "tryStartActivity(",
        ):
            self.assertIn(needle, body)

    def test_launcher_calls_do_not_block_the_ui_thread(self):
        body = self.text(self.PANEL)
        for needle in (
            "lenos-launcher-grid-query",
            "lenos-launcher-grid-apply",
            "lenos-launcher-shape-query",
            "lenos-launcher-shape-apply",
            "lenos-launcher-themed-query",
            "lenos-launcher-themed-apply",
            "runOnUiThread(",
            "LauncherGridRequest",
            "LauncherShapeRequest",
            "LauncherThemedRequest",
        ):
            self.assertIn(needle, body)


class TestProductWiring(unittest.TestCase):
    def test_personalization_is_shipped(self):
        body = (VENDOR / "config/lenos.mk").read_text()
        for needle in (*THEMES, *FRAMEWORK_THEMES, *QS_OVERLAYS,
                       *NOTIFY_CORNER_OVERLAYS,
                       NOTIFY_DIVIDERS_OVERLAY, *CLOCK_OVERLAYS):
            self.assertIn(needle, body)
        self.assertIn("merged lenOS panel", body)
        self.assertNotIn("LenosParts", body)
        self.assertNotIn("LenosSecurity", body)

    def test_standalone_apps_and_allowlists_are_gone(self):
        for rel in (
            "app/LenosParts",
            "app/LenosSecurity",
            "config/privapp-permissions-org.lenos.parts.xml",
            "config/privapp-permissions-org.lenos.security.xml",
        ):
            self.assertFalse((VENDOR / rel).exists(), rel)

    def test_docs_describe_the_local_only_boundary(self):
        doc = (VENDOR / "docs/axion-ui.md").read_text()
        self.assertIn("local-only", doc.lower())
        self.assertIn("lenOS Settings panel", doc)
        self.assertNotIn("LenosParts", doc)
        self.assertIn("Theme Store", doc,
                      "the excluded online store must be explicit")
        features = (VENDOR / "docs/features.md").read_text()
        self.assertIn("personalization", features.lower())


if __name__ == "__main__":
    unittest.main()
