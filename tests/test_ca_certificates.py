"""System trust store: distrusted CAs removed (see docs/features.md).

Feature contract (GrapheneOS-faithful port, commit ``14ad6bb`` of
``platform_system_ca-certificates``, June 2025):

* The system CA store ships without the Chunghwa Telecom roots (``HiPKI Root
  CA - G1`` and ``ePKI Root Certification Authority``) and the NetLock
  ``Arany (Class Gold)`` root — the same three files GrapheneOS deletes,
  following Google's 2025 Chrome root-store distrust announcement.
* The files are plain members of the ``Android.bp`` ``files/*`` glob, so the
  removal is a pure file deletion: no build-file or index edits are needed.
* The lineOS 24.0 tree still ships all three files, so this patch is a real
  behavior change, not upstream drift catching up.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest

REMOVED = (
    "files/53a1b57a.0",   # Chunghwa Telecom HiPKI Root CA - G1
    "files/60afe812.0",   # NetLock Arany (Class Gold)
    "files/9d6523ce.0",   # Chunghwa Telecom ePKI Root Certification Authority
)


class TestDistrustedCaRemoval(LenosPatchTest):
    PROJECT = "system/ca-certificates"
    PATCHES = ["0001-lenos-remove-distrusted-cas.patch"]
    EXTRA_FILES = ["Android.bp", "files/01419da9.0"]

    def test_distrusted_cas_are_gone(self):
        for rel in REMOVED:
            self.assertFalse(
                (self.sandbox / rel).exists(),
                f"{rel} is still in the system trust store")

    def test_other_cas_untouched(self):
        # Sample of an unrelated CA that must survive the patch.
        self.assertTrue((self.sandbox / "files/01419da9.0").is_file())

    def test_trust_store_glob_unchanged(self):
        self.assert_contains("Android.bp", '"files/*"')


if __name__ == "__main__":
    unittest.main()
