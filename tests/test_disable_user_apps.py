"""GrapheneOS: user-installed apps can be disabled (not only system apps).

GrapheneOS's app info screen offers the Disable action for user-installed
apps, so an app can be completely prevented from running without uninstalling
it and losing its data. Disabling is stricter than Force stop, which only
stops an app until something else starts one of its components again.

The feature is a Settings change; the framework already allows it:

* ``PackageManagerService.setEnabledSettings`` has no system-app restriction
  for ``COMPONENT_ENABLED_STATE_DISABLED_USER`` (verified by the second test
  class, which pins that invariant).
* Settings shares ``android.uid.system``, which holds
  ``android.permission.CHANGE_COMPONENT_ENABLED_STATE``
  (``signature|privileged``) for other packages.

Ported from GrapheneOS's ``AppDisableButton.kt``:

* ``getActionButton`` no longer returns early for non-system apps; it keys on
  ``app.installed`` like GrapheneOS (archived apps keep using the
  archive/restore flow).
* ``canBeDisabled`` gained GrapheneOS's first branch
  ``!isSystemApp -> appButtonRepository.isAllowUninstallOrArchive(...)``: a
  user app that can be uninstalled or archived can also be disabled, and
  blocks such as ``DISALLOW_APPS_CONTROL`` still apply.
* Clicking Disable on a user app disables it directly (``disable()`` still
  requires user authentication); the confirmation dialog stays for system
  apps, where disabling downgrades to the system version and destroys data.

Documented deviations:

* The SPA app info screen is the one shipped and default on LineageOS 24.0
  (``settings_enable_spa`` defaults to true), which is where GrapheneOS has
  the feature too. The legacy ``AppButtonsPreferenceController`` screen keeps
  its stock behavior of offering Disable only for system apps — it is
  unmodified in GrapheneOS as well.
* GrapheneOS's A17 dialog gained an HSU (headless system user) warning
  title/message; LineageOS 24.0 has that dialog, and user apps skip it
  entirely, so the dialog is unchanged here.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestDisableUserApps(LenosPatchTest):
    PROJECT = "packages/apps/Settings"
    PATCHES = ["0002-lenos-disable-user-apps.patch"]

    FILE = "src/com/android/settings/spa/app/appinfo/AppDisableButton.kt"

    def test_button_offered_for_all_installed_apps(self):
        self.assert_contains(
            self.FILE,
            "import com.android.settingslib.spaprivileged.model.app.installed",
            "if (!app.installed) return null")
        # The stock system-app gate must be gone.
        self.assert_not_contains(self.FILE, "if (!app.isSystemApp) return null")

    def test_user_app_disable_follows_uninstall_rules(self):
        text = self.text(self.FILE)
        self.assert_contains(
            self.FILE,
            "!isSystemApp -> appButtonRepository.isAllowUninstallOrArchive(context, this)")
        # Placed before the system-app safety checks, like GrapheneOS.
        start = text.index("private fun ApplicationInfo.canBeDisabled")
        user_branch = text.index("!isSystemApp ->", start)
        platform_check = text.index("isSignedWithPlatformKey -> false", start)
        self.assertLess(user_branch, platform_check)

    def test_user_app_disable_skips_the_data_loss_dialog(self):
        text = self.text(self.FILE)
        start = text.index("private fun disableButton")
        body = text[start:start + 1300]
        system_branch = body.index("if (app.isSystemApp) {")
        dialog = body.index("dialogPresenter.open()", system_branch)
        direct = body.index("packageInfoPresenter.disable()", system_branch)
        self.assertLess(system_branch, dialog)
        self.assertLess(dialog, direct)
        # The system-app confirmation dialog itself is untouched.
        self.assert_contains(
            self.FILE,
            "stringResource(R.string.app_disable_dlg_positive)",
            "R.string.app_disable_dlg_text")

    def test_enable_stays_available_for_disabled_apps(self):
        self.assert_contains(
            self.FILE,
            "else -> enableButton()",
            "packageInfoPresenter.enable()")

    def test_syntax(self):
        self.assert_balanced(self.FILE)


class TestFrameworkAllowsUserAppDisable(LenosPatchTest):
    """Pin the framework behavior the Settings change relies on.

    ``setEnabledSettings`` is the whole-package path behind
    ``setApplicationEnabledSetting``: it must keep accepting
    ``COMPONENT_ENABLED_STATE_DISABLED_USER`` for any package, with only the
    generic guards (caller permission, protected packages).
    """

    PROJECT = "frameworks/base"
    PATCHES = []
    EXTRA_FILES = ["services/core/java/com/android/server/pm/PackageManagerService.java"]

    PMS = "services/core/java/com/android/server/pm/PackageManagerService.java"

    def test_no_system_app_gate_for_disabled_user_state(self):
        text = self.text(self.PMS)
        start = text.index("private void setEnabledSettings(")
        end = text.index("private boolean setEnabledSettingInternalLocked", start)
        body = text[start:end]
        self.assertIn("COMPONENT_ENABLED_STATE_DISABLED_USER", body)
        self.assertIn("Cannot disable a protected package", body)
        self.assertNotIn("FLAG_SYSTEM", body,
                         "a system-app gate in setEnabledSettings would break "
                         "disabling user-installed apps")

    def test_disable_and_enable_roundtrip_states(self):
        # ENABLED → DISABLED_USER for any package, DEFAULT to re-enable.
        self.assert_contains(
            self.PMS,
            "setEnabled(newState, userId, callingPackage)",
            "COMPONENT_ENABLED_STATE_DISABLED_USER")


if __name__ == "__main__":
    unittest.main()
