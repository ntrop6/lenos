"""lenOS duress credentials (frameworks/base LockSettingsService port).

Feature contract (see docs/features.md):
* Entering the duress PIN or the duress password at any credential prompt
  destroys the KeyMint storage keys + Secretkeeper secrets (user data becomes
  cryptographically inaccessible) and powers the device off. There is no way
  back.
* Only failed verifications are checked, and only typed PIN/password
  credentials: the normal lock credential can never trigger the wipe, and a
  correct credential is ignored.
* Managing the pair (set/check/delete) requires the owner credential; the
  stored form is a scrypt-stretched hash, never the credential itself.
* Ported from GrapheneOS, including the eSIM profile erasure (EuiccWipe) and
  the suppressed carrier removal notification; the eUICC-side contract is
  covered by test_duress_esim.py. The shell test hook
  (cmd lock_settings set-duress-credentials) supports on-device verification.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from harness import VENDOR, LenosPatchTest, java_syntax_errors

AIDL = "core/java/com/android/internal/widget/ILockSettings.aidl"
LPU = "core/java/com/android/internal/widget/LockPatternUtils.java"
LSS = "services/core/java/com/android/server/locksettings/LockSettingsService.java"
HELPER = "services/core/java/com/android/server/locksettings/DuressPasswordHelper.java"
CRED = "services/core/java/com/android/server/locksettings/DuressCredential.java"
CREDS = "services/core/java/com/android/server/locksettings/DuressCredentials.java"
WIPE = "services/core/java/com/android/server/locksettings/DuressWipe.java"
SHELL = "services/core/java/com/android/server/locksettings/LockSettingsShellCommand.java"
RECOVERY = "services/core/java/com/android/server/recoverysystem/RecoverySystemService.java"

APP_DIR = "app/LenosSecurity/src/org/lenos/security"


def read_vendor(rel: str) -> str:
    return (VENDOR / rel).read_text(encoding="utf-8")


class TestDuressBackend(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0005-lenos-duress-credentials.patch"]

    def test_java_still_parses(self):
        for path in (LPU, LSS, HELPER, CRED, CREDS, WIPE, SHELL, RECOVERY):
            self.assert_java_syntax(path)

    def test_aidl_exposes_the_owner_gated_api(self):
        self.assert_contains(
            AIDL,
            "void setDuressCredentials(in LockscreenCredential ownerCredential, "
            "in LockscreenCredential duressPin, in LockscreenCredential duressPassword);",
            "boolean hasDuressCredentials(in LockscreenCredential ownerCredential);",
        )

    def test_client_api_matches_the_app_contract(self):
        # The app reflects on these LockPatternUtils methods by name.
        lpu = self.text(LPU)
        for method in ("setDuressCredentials", "hasDuressCredentials",
                       "deleteDuressCredentials"):
            self.assertIn(method, lpu)
            self.assertIn(method, read_vendor(f"{APP_DIR}/LockBridge.java"))
        self.assert_contains(LPU, "LockscreenCredential.createNone()")

    def test_duress_credentials_are_at_least_4_chars_low_complexity(self):
        self.assert_contains(
            LPU,
            "public static List<PasswordValidationError> validateDuressCredential(",
            "metrics.length = 4;",
            "DevicePolicyManager.PASSWORD_COMPLEXITY_LOW",
            "import android.app.admin.PasswordValidationError;",
        )

    def test_only_failed_verifications_are_checked(self):
        self.assert_contains(
            HELPER,
            "if (res != null && res.isMatched()) {",
        )
        # The hook wraps the real verification in a finally block.
        self.assert_contains(
            LSS,
            "mDuressPasswordHelper.onVerifyCredentialResult(res, credential);",
            "doVerifyCredentialInner(credential, userId, progressCallback, flags);",
        )

    def test_only_typed_credentials_are_candidates(self):
        self.assert_contains(
            HELPER,
            "case CREDENTIAL_TYPE_PIN:",
            "case CREDENTIAL_TYPE_PASSWORD:",
            "DuressCredentials dc = DuressCredentials.maybeGet(mLockSettingsStorage);",
            "return dc != null && dc.get(credentialType).verify(mSpManager, credential);",
        )

    def test_stored_form_is_a_stretched_hash_never_the_credential(self):
        self.assert_contains(
            CRED,
            "LockPatternUtils.PIN_LENGTH_UNAVAILABLE",
            "byte[] hashedCredential = spm.stretchLskf(credential, salt);",
            "return Arrays.equals(mHashedCredential, spm.stretchLskf(credential, mSalt));",
        )
        self.assert_contains(
            CREDS,
            'LOCK_SETTINGS_STORAGE_KEY = "duress_credentials";',
            "UserHandle.USER_SYSTEM;",
            "HexEncoding.encodeToString(bos.toByteArray());",
        )

    def test_owner_credential_is_required_to_manage_the_pair(self):
        self.assert_contains(
            HELPER,
            "private void checkOwnerCredential(LockscreenCredential ownerCredential)",
            "mLockSettingsService.checkCredential(ownerCredential,",
            "throw new SecurityException(\"owner credential verification failed; \"",
        )
        self.assert_contains(
            LSS,
            "checkWritePermission();",
            "checkPasswordHavePermission();",
            "LockscreenCredential.zeroizeIfFromParcel(duressPin);",
            "LockscreenCredential.zeroizeIfFromParcel(duressPassword);",
            "throw new ParcelableException(e);",
        )

    def test_both_none_deletes_the_pair(self):
        self.assert_contains(
            HELPER,
            "if (pin.isNone() && password.isNone()) {",
            "DuressCredentials.delete(mLockSettingsStorage);",
        )

    def test_wipe_deletes_storage_keys_and_powers_off(self):
        self.assert_contains(
            WIPE,
            "RecoverySystemService.deleteSecrets();",
            "PowerManagerService.lowLevelShutdown(null);",
        )
        self.assert_contains(
            RECOVERY,
            "public static void deleteSecrets() {",
        )

    def test_wipe_includes_esim_erasure(self):
        # Same ordering as GrapheneOS: the eUICC wipe starts first, the
        # cryptographic erase never waits for it, power-off waits at most 3s.
        wipe = self.text(WIPE)
        self.assertIn("import com.android.internal.telephony.euicc.EuiccWipe;", wipe)
        self.assertIn(
            "EuiccWipe.run(context, EuiccCardManager.RESET_FLAG_IS_FOR_DURESS_WIPE)", wipe)
        self.assertIn("EuiccWipeThread.start(context);", wipe)
        self.assertIn("euiccWipeThread.await(3000);", wipe)
        self.assertLess(wipe.index("EuiccWipeThread.start(context);"),
                        wipe.index("RecoverySystemService.deleteSecrets();"))
        self.assertLess(wipe.index("RecoverySystemService.deleteSecrets();"),
                        wipe.index("euiccWipeThread.await(3000);"))
        self.assertIn("DuressWipe.run(mLockSettingsService.getContext());", self.text(HELPER))

    def test_shell_command_matches_the_grapheneos_workflow(self):
        self.assert_contains(
            SHELL,
            '"set-duress-credentials";',
            "private int handleSetDuressCredentials() {",
            '"--old":',
            '"--duress-pin":',
            '"--duress-password":',
            '"--sleep-5s-before-poweroff":',
            "mLockPatternUtils.setDuressCredentials(getOldCredential(), pin, password);",
            "DuressWipe.sleep5sBeforePoweroff = sleep5sBeforePoweroff;",
            "if (!checkCredential()) {",
        )


class TestDuressProductWiring(unittest.TestCase):
    def test_backend_status_prop_is_framework(self):
        self.assertIn("ro.lenos.security.duress=framework",
                      read_vendor("config/lenos.mk"))

    def test_app_text_lists_the_esim_erasure(self):
        for name in ("MainActivity.java", "LockBridge.java"):
            errors = java_syntax_errors(VENDOR / APP_DIR / name)
            self.assertEqual(errors, 0, f"{name}: {errors} Java parse errors")
        main = read_vendor(f"{APP_DIR}/MainActivity.java")
        self.assertIn("deletes the keystore secrets protecting storage", main)
        self.assertIn("erases stored eSIM profiles", main)
        self.assertIn("erase stored eSIM profiles", main)

    def test_app_uses_the_owner_gated_path_directly(self):
        main = read_vendor(f"{APP_DIR}/MainActivity.java")
        self.assertIn("lock.setDuress(owner, dPin, dPass);", main)
        self.assertIn("lock.hasDuress(owner)", main)
        self.assertIn("lock.deleteDuress(owner)", main)

    def test_platform_signed_app_has_no_root_shell_fallback(self):
        # The app is platform-signed and holds ACCESS_KEYGUARD_SECURE_STORAGE
        # and WRITE_SECURE_SETTINGS. A su/app_process fallback would add an
        # unnecessary root path and hide permission failures.
        for name in ("MainActivity.java", "LockBridge.java"):
            body = read_vendor(f"{APP_DIR}/{name}")
            self.assertNotIn("RootShell", body)
            self.assertNotIn('"su"', body)
            self.assertNotIn("app_process", body)
        self.assertFalse((VENDOR / APP_DIR / "RootShell.java").exists())
        self.assertFalse((VENDOR / APP_DIR / "DuressCli.java").exists())


if __name__ == "__main__":
    unittest.main()
