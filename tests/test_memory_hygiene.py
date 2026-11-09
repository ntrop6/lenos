"""GrapheneOS memory hygiene on lock (full compacting GC for both processes).

GrapheneOS runs a full compacting garbage collection for SystemUI and
system_server when the device is locked:

* SystemUI: ``KeyguardViewMediator.handleShowInner`` ends with
  ``System.gc(); System.runFinalization(); System.gc();`` right before the
  show wake lock is released (line-level port).
* system_server: GrapheneOS triggers it from
  ``KeyguardServiceDelegate.onShowingStateChanged``, which runs on a binder
  thread when the keyguard service reports ``showing``.

system_server runs the same three calls on the ``setLockScreenShown`` binder
thread — gated on the false→true transition and placed after the global lock
is released. This is equivalent to where GrapheneOS's callback runs (binder
thread, no WMS lock held).
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestMemoryHygieneOnLock(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0024-lenos-memory-hygiene-on-lock.patch"]

    KVM = ("packages/SystemUI/src/com/android/systemui/keyguard/"
           "KeyguardViewMediator.java")
    ATMS = ("services/core/java/com/android/server/wm/"
            "ActivityTaskManagerService.java")

    def test_systemui_gc_runs_when_keyguard_shows(self):
        text = self.text(self.KVM)
        self.assert_contains(
            self.KVM,
            "mKeyguardViewControllerLazy.get().setKeyguardGoingAwayState(false);",
            "// lenOS: full compacting garbage collection when the keyguard "
            "starts showing",
            "System.gc();\n"
            "            System.runFinalization();\n"
            "            System.gc();\n"
            "            mShowKeyguardWakeLock.release();")
        self.assertEqual(text.count("System.gc();"), 2)
        self.assertEqual(text.count("System.runFinalization();"), 1)
        # Same place as GrapheneOS: inside handleShowInner's synchronized block.
        show = text.index("private void handleShowInner")
        sync = text.index("synchronized (KeyguardViewMediator.this) {", show)
        gc = text.index("System.gc();", show)
        self.assertLess(sync, gc)

    def test_system_server_gc_is_transition_gated(self):
        text = self.text(self.ATMS)
        method = text.index("public void setLockScreenShown(boolean "
                            "keyguardShowing, boolean aodShowing) {")
        body = text[method:method + 2600]
        self.assertIn("keyguardShowingChanged = mKeyguardShown != keyguardShowing;",
                      body)
        self.assertIn("if (keyguardShowingChanged && keyguardShowing) {", body)
        self.assertIn("System.gc();\n"
                      "            System.runFinalization();\n"
                      "            System.gc();", body)
        self.assertEqual(text.count("System.gc();"), 2)
        self.assertEqual(text.count("System.runFinalization();"), 1)

    def test_system_server_gc_runs_off_the_global_lock(self):
        text = self.text(self.ATMS)
        method = text.index("public void setLockScreenShown(boolean "
                            "keyguardShowing, boolean aodShowing) {")
        body = text[method:method + 2600]
        restore = body.index("Binder.restoreCallingIdentity(ident);")
        gc = body.index("System.gc();")
        self.assertLess(restore, gc,
                        "GC must run after the mGlobalLock block is left")

    def test_syntax(self):
        for f in (self.KVM, self.ATMS):
            self.assert_java_syntax(f)


if __name__ == "__main__":
    unittest.main()
