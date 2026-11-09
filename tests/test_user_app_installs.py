"""GrapheneOS: per-user app installation policy (#19).

GrapheneOS exposes the standard user restrictions ``DISALLOW_INSTALL_APPS``
and ``DISALLOW_INSTALL_UNKNOWN_SOURCES`` on the user details screen, so the
owner can set, for each secondary user (or the guest), one of three policies:

* apps and updates allowed,
* first-party sources only (unknown sources blocked),
* no installs or updates.

The device-management restriction is a normal platform feature, so the port is
the Settings UI plus a small restriction helper — the framework already
enforces it in ``PackageInstallerService``/``InstallPackageHelper``.

The port keeps GrapheneOS's ``Instrumentable.METRICS_CATEGORY_UNKNOWN`` (A17
defines it), puts the strings in a new ``strings_lenos_users.xml`` instead of
extending the lenOS ext-strings file, and trims the helper to the install path
(GrapheneOS's private-space inheritance is a separate feature).
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestUserAppInstalls(LenosPatchTest):
    PROJECT = "packages/apps/Settings"
    PATCHES = ["0003-lenos-user-app-installs.patch"]

    SCREEN = "src/com/android/settings/users/UserAppsInstallSettings.java"
    HELPER = "src/com/android/settings/users/UserRestrictions.java"
    DETAILS = "src/com/android/settings/users/UserDetailsSettings.java"
    XML = "res/xml/user_details_settings.xml"
    STRINGS = "res/values/strings_lenos_users.xml"

    def test_screen_has_the_three_policies(self):
        self.assert_contains(
            self.SCREEN,
            'INSTALL_ENABLED = "install_apps_enabled"',
            'INSTALL_FIRST_PARTY_ENABLED = "install_apps_first_party_enabled"',
            'INSTALL_DISABLED = "install_apps_disabled"')

    def test_policy_writes_the_standard_restrictions(self):
        self.assert_contains(
            self.SCREEN,
            "userRestrictions.set(UserManager.DISALLOW_INSTALL_APPS, false);",
            "userRestrictions.set(UserManager.DISALLOW_INSTALL_APPS, true);",
            "userRestrictions.set(UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES, true);")

    def test_guest_cannot_get_the_enabled_option(self):
        self.assert_contains(
            self.SCREEN,
            "if (!userRestrictions.userInfo.isGuest()) {",
            "if (userRestrictions.userInfo.isGuest()) {\n                    return false;")

    def test_helper_handles_guests_and_plain_users(self):
        self.assert_contains(
            self.HELPER,
            "userManager.hasUserRestrictionForUser(",
            "userManager.getDefaultGuestRestrictions().getBoolean(restrictionKey)",
            "userManager.setDefaultGuestRestrictions(defaultGuestRestrictions);",
            "userManager.setUserRestriction(\n"
            "                    restrictionKey, enableRestriction, userInfo.getUserHandle());")

    def test_user_details_wiring(self):
        self.assert_contains(
            self.DETAILS,
            'private static final String KEY_APP_INSTALLS = "app_installs";',
            "mAppsInstallsPref = findPreference(KEY_APP_INSTALLS);",
            "UserAppsInstallSettings.launch(preference, mUserInfo.id);",
            "mAppsInstallsPref.setOnPreferenceClickListener(this);",
            "mAppsInstallsPref.setSummary(UserAppsInstallSettings.getDescription(")

    def test_user_details_xml_row(self):
        self.assert_contains(
            self.XML,
            'android:key="app_installs"',
            'android:icon="@drawable/ic_settings_install"',
            'android:title="@string/user_app_install"')

    def test_strings(self):
        self.assert_contains(
            self.STRINGS,
            'name="user_app_install"',
            'name="user_app_install_enabled"',
            'name="user_app_install_enabled_first_party_sources"',
            'name="user_app_install_disabled"',
            'name="user_app_install_enabled_desc"',
            'name="user_app_install_enabled_first_party_sources_desc"',
            'name="user_app_install_disabled_desc"')

    def test_metrics_category(self):
        # A17 has Instrumentable.METRICS_CATEGORY_UNKNOWN, so the port uses
        # GrapheneOS's value instead of an A16 compatibility stand-in.
        self.assert_contains(
            self.SCREEN,
            "return Instrumentable.METRICS_CATEGORY_UNKNOWN;",
            "Instrumentable.METRICS_CATEGORY_UNKNOWN))")

    def test_balanced(self):
        self.assert_balanced(self.SCREEN)
        self.assert_balanced(self.HELPER)


if __name__ == "__main__":
    unittest.main()
