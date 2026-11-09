"""Call recording baseline (Tier 2 #26).

LineageOS's Dialer already ships the call-recording behaviour the roadmap
wanted from GrapheneOS's Dialer: recording is enabled unconditionally (no
carrier/region gate), no recording tone is played, and files are written
through MediaStore to ``Recordings/Call recordings``. The Dialer is a
privileged, shared-certificate system app whose privapp allowlist grants
``CAPTURE_AUDIO_OUTPUT``, so the ``VOICE_CALL`` audio source works.

GrapheneOS's Dialer adds a larger auto-recording-by-contact subsystem
(preference store, contact modes, stale-contact cleanup jobs); that fork is
not part of the 1.0 series. These checks pin the baseline so upstream drift
cannot silently disable recording.
"""
from __future__ import annotations

import subprocess
import unittest
import xml.etree.ElementTree as ET

from harness import WORKSPACE

DIALER = WORKSPACE / "packages/apps/Dialer"
CONFIG = DIALER / "java/com/android/dialer/callrecord/res/values/config.xml"
SERVICE = DIALER / "java/com/android/dialer/callrecord/impl/CallRecorderService.java"
RECORDING = DIALER / "java/com/android/dialer/callrecord/CallRecording.java"


def git_show(rel: str) -> str:
    return subprocess.run(
        ["git", "-C", str(DIALER), "show", f"HEAD:{rel}"],
        check=True, capture_output=True, text=True).stdout


@unittest.skipUnless(DIALER.is_dir(), f"workspace project missing: {DIALER}")
class TestCallRecording(unittest.TestCase):
    def test_enabled_without_a_region_gate(self):
        root = ET.parse(CONFIG).getroot()
        bools = {b.get("name"): (b.text or "").strip()
                 for b in root.findall("bool")}
        self.assertEqual(bools.get("call_recording_enabled"), "true")
        body = SERVICE.read_text(encoding="utf-8")
        self.assertIn(
            "public static boolean isEnabled(Context context) {\n"
            "    return context.getResources().getBoolean(R.bool.call_recording_enabled);\n"
            "  }",
            body)

    def test_voice_call_audio_source(self):
        root = ET.parse(CONFIG).getroot()
        ints = {i.get("name"): (i.text or "").strip()
                for i in root.findall("integer")}
        # 4 == MediaRecorder.AudioSource.VOICE_CALL (uplink + downlink).
        self.assertEqual(ints.get("call_recording_audio_source"), "4")

    def test_files_go_to_the_shared_recordings_folder(self):
        body = RECORDING.read_text(encoding="utf-8")
        self.assertIn('"Recordings/Call recordings"', body)
        self.assertIn("MediaStore.Audio.Media.RELATIVE_PATH", body)

    def test_no_recording_tone(self):
        for path in (SERVICE, RECORDING):
            self.assertNotIn(
                "ToneGenerator", path.read_text(encoding="utf-8"), str(path))

    def test_privileged_dialer_can_capture_call_audio(self):
        manifest = git_show("AndroidManifest.xml")
        self.assertIn("android.permission.RECORD_AUDIO", manifest)
        self.assertIn("android.permission.CAPTURE_AUDIO_OUTPUT", manifest)
        self.assertIn("privileged: true", git_show("Android.bp"))
        whitelist = git_show("privapp_whitelist_com.android.dialer-ext.xml")
        self.assertIn(
            'name="android.permission.CAPTURE_AUDIO_OUTPUT"', whitelist)


if __name__ == "__main__":
    unittest.main()
