"""Local-only visual customization (LenosParts + SystemUI theme overlays).

Feature contract (see docs/axion-ui.md):

* The personalization layer is a local dashboard and preinstalled resource
  overlays. It has no INTERNET permission, no account, no telemetry and no
  Google/GMS/Play Integrity code path.
* Theme packs are mutable SystemUI overlays. LenosParts enables exactly one
  pack (or none) through OverlayManager.
* Motion presets only write the standard Android animation-scale settings.
* The stock LineageOS status bar panel remains the source of truth for clock,
  battery, network-traffic and brightness controls.
"""
from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from harness import VENDOR, java_syntax_errors

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

THEMES = {
    "LenosThemeEmberSystemUI": "org.lenos.theme.ember.systemui",
    "LenosThemeMintSystemUI": "org.lenos.theme.mint.systemui",
    "LenosThemeMonoSystemUI": "org.lenos.theme.mono.systemui",
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


class TestLenosPartsApp(unittest.TestCase):
    MANIFEST = "app/LenosParts/AndroidManifest.xml"

    def test_manifest_is_minimal_and_local(self):
        root = parse_xml(self.MANIFEST)
        permissions = {
            node.get(f"{ANDROID_NS}name")
            for node in root.findall("uses-permission")
        }
        self.assertEqual(
            permissions,
            {
                "android.permission.CHANGE_OVERLAY_PACKAGES",
                "android.permission.WRITE_SECURE_SETTINGS",
            },
            "LenosParts must keep its privileged permission set minimal",
        )
        for banned in BANNED_APP_TEXT:
            self.assertNotIn(banned.lower(),
                             (VENDOR / self.MANIFEST).read_text().lower())

        application = root.find("application")
        self.assertIsNotNone(application)
        self.assertEqual(
            application.get(f"{ANDROID_NS}allowBackup"), "false")
        activity = application.find("activity")
        self.assertIsNotNone(activity)
        self.assertEqual(activity.get(f"{ANDROID_NS}exported"), "true")
        actions = {
            node.get(f"{ANDROID_NS}name")
            for node in activity.findall("intent-filter/action")
        }
        self.assertIn("android.intent.action.MAIN", actions)

    def test_build_uses_platform_apis_and_no_network_dependency(self):
        body = (VENDOR / "app/LenosParts/Android.bp").read_text()
        self.assertIn('name: "LenosParts"', body)
        self.assertIn("platform_apis: true", body)
        self.assertIn("privileged: true", body)
        self.assertIn('certificate: "platform"', body)
        for banned in ("static_libs", "jni_libs", "sdk_version"):
            self.assertNotIn(banned, body)
        self.assertNotIn("INTERNET", body)

    def test_source_uses_local_overlays_and_settings_only(self):
        source = VENDOR / "app/LenosParts/src/org/lenos/parts/MainActivity.java"
        body = source.read_text()
        for needle in (
            "OverlayManager",
            "Process.myUserHandle()",
            "getOverlayInfosForTarget(",
            "installed.contains(pkg)",
            "org.lenos.theme.ember.systemui",
            "org.lenos.theme.mint.systemui",
            "org.lenos.theme.mono.systemui",
            "Settings.Global.ANIMATOR_DURATION_SCALE",
            "Settings.Global.TRANSITION_ANIMATION_SCALE",
            "Settings.Global.WINDOW_ANIMATION_SCALE",
            "org.lineageos.lineageparts.STATUS_BAR_SETTINGS",
        ):
            self.assertIn(needle, body)
        for banned in BANNED_JAVA:
            self.assertNotIn(banned, body)

    def test_java_parses(self):
        self.assertEqual(
            java_syntax_errors(
                VENDOR / "app/LenosParts/src/org/lenos/parts/MainActivity.java"),
            0,
        )


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
        radii = set()
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
                    "notification_corner_radius",
                    "qs_corner_radius",
                    "qs_tile_margin_horizontal",
                ):
                    self.assertIn(resource, values)
                radii.add(values["notification_corner_radius"])
        self.assertEqual(len(radii), len(THEMES),
                         "each pack must have a distinct corner radius")

    def test_no_network_or_remote_code_in_overlay_sources(self):
        for name in THEMES:
            for path in (VENDOR / f"rro/{name}").rglob("*"):
                if not path.is_file():
                    continue
                body = path.read_text(encoding="utf-8", errors="replace")
                for banned in BANNED_APP_TEXT:
                    self.assertNotIn(banned.lower(), body.lower(),
                                     f"{path}: {banned}")


class TestProductWiring(unittest.TestCase):
    def test_personalization_is_shipped(self):
        body = (VENDOR / "config/lenos.mk").read_text()
        for needle in ("LenosParts", *THEMES):
            self.assertIn(needle, body)

    def test_privapp_allowlist_is_scoped_to_the_app(self):
        root = parse_xml(
            "config/privapp-permissions-org.lenos.parts.xml")
        node = root.find("privapp-permissions")
        self.assertIsNotNone(node)
        self.assertEqual(node.get("package"), "org.lenos.parts")
        permissions = {
            child.get("name") for child in node.findall("permission")
        }
        self.assertEqual(
            permissions,
            {
                "android.permission.CHANGE_OVERLAY_PACKAGES",
                "android.permission.WRITE_SECURE_SETTINGS",
            },
        )

    def test_docs_describe_the_local_only_boundary(self):
        doc = (VENDOR / "docs/axion-ui.md").read_text()
        self.assertIn("local-only", doc.lower())
        self.assertIn("LenosParts", doc)
        self.assertIn("Theme Store", doc, "the excluded online store must be explicit")
        features = (VENDOR / "docs/features.md").read_text()
        self.assertIn("personalization", features.lower())


if __name__ == "__main__":
    unittest.main()
