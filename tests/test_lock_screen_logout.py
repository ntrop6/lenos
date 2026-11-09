"""GrapheneOS: the lock screen end session (logout) button is disabled (#18).

The lock screen shows an "End session" button for the current user when logout
is allowed (the secondary-user case). It needs no authentication: anyone
holding the locked device can terminate the session and close every app.
GrapheneOS disables the button with a short-circuited guard in
``KeyguardIndicationController.updateLockScreenLogoutView()`` and keeps the
builder below it (it still compiles, it is just never shown).

LineageOS 24.0 ships the AOSP behavior. GrapheneOS's branch-17 file differs
from AOSP only in that guard (the surrounding logout wiring — the
``isPolicyManagerLogoutEnabled`` callback and the rotate-text controller — is
untouched), so the port is the GrapheneOS short-circuit verbatim.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestLockScreenLogout(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0028-lenos-disable-lock-screen-logout.patch"]

    CONTROLLER = (
        "packages/SystemUI/src/com/android/systemui/statusbar/"
        "KeyguardIndicationController.java")

    def test_logout_guard_is_short_circuited(self):
        self.assert_contains(
            self.CONTROLLER,
            "if (false && mUserLogoutInteractor.isPolicyManagerLogoutEnabled().getValue()) {")

    def test_no_live_logout_guard_left(self):
        self.assert_not_contains(
            self.CONTROLLER,
            "\n        if (mUserLogoutInteractor.isPolicyManagerLogoutEnabled().getValue()) {")

    def test_logout_flow_is_kept_but_unreachable(self):
        # The disabled branch still carries the button: the port disables the
        # UI, it does not rewrite the logout flow (same as GrapheneOS).
        self.assert_contains(
            self.CONTROLLER,
            "com.android.internal.R.string.global_action_logout",
            "mUserLogoutInteractor.logOut();",
            "mRotateTextViewController.hideIndication(INDICATION_TYPE_LOGOUT);")

    def test_comment_names_the_reason(self):
        self.assert_contains(
            self.CONTROLLER,
            "GrapheneOS disables the lock screen end session button",
            "without the user's credentials")

    def test_balanced(self):
        self.assert_balanced(self.CONTROLLER)


if __name__ == "__main__":
    unittest.main()
