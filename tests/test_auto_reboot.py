"""Auto reboot to before-first-unlock (init + frameworks/base + vendor/lenos).

Feature contract (see docs/features.md), ported from GrapheneOS:
* init owns the timer (system/core/init/property_service.cpp). The framework
  special-cases ``sys.auto_reboot_ctl`` so system_server can arm it without
  a binder service: the value is the timeout in seconds, or
  ``on_device_unlocked`` to cancel.
* The timer uses CLOCK_BOOTTIME_ALARM (counts through suspend), and on
  expiry init performs a normal ``reboot`` via HandlePowerctlMessage.
* Requests that arrive before the device has been unlocked at least once
  are ignored (BFU handling: the timer must never reboot a device the user
  has not yet used this boot).
* A running timer is not restarted by repeated lock events; durations below
  20 seconds are clamped.
* frameworks/base (AutoReboot.java) translates keyguard showing-state
  changes for the current user into those property writes, using
  ExtSettings.AUTO_REBOOT_TIMEOUT (Settings.Global
  ``settings_reboot_after_timeout``, GrapheneOS-compatible key, 18h default).
* The lenOS security app writes the same key; the product property reports
  the init backend. There is no SettingsProvider def_* seed.
"""
from __future__ import annotations

import unittest

from harness import VENDOR, LenosPatchTest

APP = "app/LenosSecurity/src/org/lenos/security/MainActivity.java"
RRO = "rro/LenosSettingsProviderOverlay/res/values/defaults.xml"
LEGACY_KEY = "lenos_auto_reboot_timeout_ms"


def read_vendor(rel: str) -> str:
    return (VENDOR / rel).read_text(encoding="utf-8")


class TestAutoRebootInitTimer(LenosPatchTest):
    PROJECT = "system/core"
    PATCHES = ["0001-lenos-auto-reboot-init.patch"]
    SRC = "init/property_service.cpp"

    def test_source_is_still_balanced(self):
        self.assert_balanced(self.SRC)

    def test_control_property_is_special_cased(self):
        self.assert_contains(
            self.SRC,
            'if (name == "sys.auto_reboot_ctl") {',
            "auto_reboot_handle_property_set(value)",
        )

    def test_timer_uses_boottime_alarm_and_reboots(self):
        self.assert_contains(
            self.SRC,
            "timer_create(CLOCK_BOOTTIME_ALARM, &sev, &auto_reboot_timer)",
            "SIGEV_THREAD",
            'HandlePowerctlMessage("reboot");',
        )

    def test_timer_starts_with_the_property_service(self):
        body = self.text(self.SRC)
        thread = body.index("static void PropertyServiceThread(int fd, bool listen_init) {")
        call = body.index("auto_reboot_timer_init();", thread)
        loop = body.index("while (true) {", thread)
        self.assertLess(thread, call, "timer must be initialized in the property thread")
        self.assertLess(call, loop, "timer must exist before the epoll loop starts")
        self.assert_contains(self.SRC, "if (!IsMicrodroid()) {")

    def test_requests_are_ignored_until_the_device_was_unlocked(self):
        self.assert_contains(
            self.SRC,
            "static bool device_unlocked_at_least_once;",
            "auto_reboot: device was never unlocked, skipped setting timer",
        )

    def test_unlock_event_cancels_the_timer(self):
        self.assert_contains(
            self.SRC,
            'if (value == "on_device_unlocked")',
            "auto_reboot_timer_set(0);",
        )

    def test_running_timer_is_not_restarted_by_relock(self):
        self.assert_contains(
            self.SRC,
            "static bool is_auto_reboot_timer_started;",
            "auto_reboot: timer is already started, ignored request to restart it;",
        )

    def test_minimum_duration_is_clamped(self):
        self.assert_contains(
            self.SRC,
            "const time_t min_duration = 20;",
            "auto_reboot: raised timer duration",
        )


class TestAutoRebootFramework(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = [
        "0003-lenos-auto-reboot.patch",
        "0006-lenos-ext-settings.patch",
    ]
    AUTO_REBOOT = "services/core/java/com/android/server/policy/keyguard/AutoReboot.java"
    MONITOR = "services/core/java/com/android/server/policy/keyguard/KeyguardServiceDelegate.java"
    EXTSETTINGS = "core/java/android/ext/settings/ExtSettings.java"
    SETTINGS = "core/java/android/provider/Settings.java"

    def test_java_still_parses(self):
        for rel in (self.AUTO_REBOOT, self.MONITOR, self.EXTSETTINGS, self.SETTINGS):
            self.assert_java_syntax(rel)

    def test_framework_arms_and_cancels_via_the_init_property(self):
        self.assert_contains(
            self.AUTO_REBOOT,
            'private static final String SYS_PROP = "sys.auto_reboot_ctl";',
            'SystemProperties.set(SYS_PROP, "on_device_unlocked");',
            "ExtSettings.AUTO_REBOOT_TIMEOUT.get(ctx)",
            "SystemProperties.set(SYS_PROP, Integer.toString(timeoutSeconds));",
        )

    def test_keyguard_state_drives_the_timer(self):
        self.assert_contains(
            self.MONITOR,
            "private final Context mContext;",
            "mContext = context;",
            "AutoReboot.onKeyguardShowingStateChanged(mContext, showing, mKeyguardState.userId);",
        )
        # A17 delivers the keyguard callback per user; the userId check in
        # IKeyguardStateCallback must drop stale callbacks before they reach
        # the forwarding method (and therefore the global timer).
        body = self.text(self.MONITOR)
        self.assertLess(body.index("if (userId != mKeyguardState.userId) return;"),
                        body.index("KeyguardServiceDelegate.this.onShowingStateChanged(showing);"))

    def test_timeout_key_and_default_match_grapheneos(self):
        self.assert_contains(
            self.EXTSETTINGS,
            "Settings.Global.AUTO_REBOOT_TIMEOUT",
            "TimeUnit.HOURS.toMillis(18)",
        )
        self.assert_contains(
            self.SETTINGS,
            'public static final String AUTO_REBOOT_TIMEOUT = "settings_reboot_after_timeout";',
        )


class TestAutoRebootProductWiring(unittest.TestCase):
    def test_backend_status_prop_is_init(self):
        self.assertIn("ro.lenos.security.auto_bfu=init", read_vendor("config/lenos.mk"))

    def test_app_writes_the_extsettings_key(self):
        app = read_vendor(APP)
        self.assertIn('BFU_SETTING = "settings_reboot_after_timeout"', app)
        self.assertIn(
            "Settings.Global.putInt(getContentResolver(), BFU_SETTING, value)", app)
        self.assertIn(
            "Settings.Global.getInt(getContentResolver(), BFU_SETTING, BFU_DEFAULT_MS)",
            app)

    def test_app_default_matches_the_extsettings_default(self):
        self.assertIn("BFU_DEFAULT_MS = 64_800_000", read_vendor(APP))

    def test_app_choices_cover_the_extremes(self):
        app = read_vendor(APP)
        self.assertIn('BFU_CHOICES.put(0, "Off")', app)
        self.assertIn("BFU_CHOICES.put(600_000,", app)
        self.assertIn("BFU_CHOICES.put(259_200_000,", app)

    def test_legacy_key_is_gone_everywhere(self):
        for rel in (APP, RRO):
            self.assertNotIn(LEGACY_KEY, read_vendor(rel), rel)
        for name in ("0002-lenos-first-boot-defaults.patch",
                     "0003-lenos-auto-reboot.patch"):
            patch = VENDOR / "patches" / "frameworks_base" / name
            self.assertNotIn(LEGACY_KEY, patch.read_text(encoding="utf-8"), name)
        for name in ("0001-lenos-auto-reboot-init.patch",):
            patch = VENDOR / "patches" / "system_core" / name
            self.assertNotIn(LEGACY_KEY, patch.read_text(encoding="utf-8"), name)

    def test_docs_describe_the_init_backend(self):
        docs = read_vendor("docs/features.md")
        self.assertIn("sys.auto_reboot_ctl", docs)


if __name__ == "__main__":
    unittest.main()
