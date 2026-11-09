# Flashing and locking

This is not a general flashing guide. It records the rules that apply to this
device build. If you are not already comfortable with `fastboot`, recovery, and
verified boot, stop here.

Nothing in this repository flashes, wipes, or locks a phone. The helper script
prints a flash plan and, for a root build, a reference-only lock gate list. It
refuses to run the final flash or lock steps, and it never prints a lock
sequence; for a rootless build it refuses even to print the gate list.

## Before flashing

- Build the whole OTA and verify its checksum yourself. Do not use a zip from
  someone else.
- Keep the signing keys off the repository and in at least two separate offline
  places. A build whose keys exist in only one place is not recoverable.
- Back up anything you cannot lose. Unlocking or relocking the bootloader wipes
  user data.
- Make sure the phone can already boot something, and know how you would
  recover it if the new image does not boot.
- Use the complete OTA. Do not flash partitions one at a time and do not
  hand-write `android-info.txt`.
- Do not re-sign bootloader, modem, or other firmware images from the OTA.
- Do not use `--disable-verity` or `--disable-verification` as a workaround.

If the build host and the phone are different machines, copy the zip, its
checksum, the extracted fastboot plan, and the public AVB key to the machine
that will flash. Keep the private keys on the build host.

## Build checks

Before you flash, confirm the package matches the build you intended to make:

```bash
sha256sum lenos-asteroids-rootless.zip
cat lenos-asteroids-rootless.zip.sha256
```

For a root build, use the matching name:

```bash
sha256sum lenos-asteroids-bakasu.zip     # or ...-kernelsu.zip
cat lenos-asteroids-bakasu.zip.sha256
```

The extracted plan must contain a real `android-info.txt` and the correct
product. Do not invent either one. A root build is still a complete OTA; never
flash its `init_boot.img` by itself or reuse it with another build.

After the first boot, still unlocked, check at least:

```bash
adb shell getprop ro.lenos.version
adb shell getprop ro.boot.veritymode        # enforcing
adb shell getprop ro.boot.vbmeta.digest
```

The digest must match the image you verified. If it does not, do not lock.

## Locking (unsupported)

Locking is unsupported and can leave the phone in a state you cannot unlock.
The steps below are a reference record for an owner who independently chooses to
take that risk; the helper will not run them. Do not lock unless all of these
are true:

- the image you just built has booted, still unlocked;
- `ro.boot.veritymode` reports `enforcing`;
- the verified-boot digest matches this build;
- OEM unlocking is enabled and you know how to get back to fastboot;
- the AVB and OTA private keys exist in at least two offline places;
- the inactive slot is complete and not marked unbootable;
- you accept that a failed boot after locking may be unrecoverable.

Do not lock a test-key build. Do not lock a build you have not booted. Locking
wipes `/data` and may remove the unlock path if the image then fails.

A root build does not make locking supported. The OTA can carry a correctly
re-signed AVB chain, but this repository does not install or verify
OEMUnlockOnBoot or another boot-failure recovery guard. If root is installed,
read [`root.md`](root.md) first and still treat locking as unsupported.

If you independently accept those risks, the reference sequence is:

```bash
# REFERENCE ONLY — the helper does not run or support this sequence.
adb reboot bootloader
fastboot getvar unlocked                 # must be yes
fastboot erase avb_custom_key
fastboot flash avb_custom_key /path/to/avb_pkmd.bin
# size 0 reported by some Nothing bootloaders is normal
fastboot reboot                          # confirm it still boots, still unlocked
adb reboot bootloader
fastboot flashing lock                   # confirm on device; wipes /data
```

A yellow custom-key warning after locking is expected. Keep OEM unlocking
enabled after that. Never sideload an unpatched or differently signed OTA.

## Updates

Prefer the full OTA from recovery or the normal system updater, signed with the
same OTA key as the installed build. Do not sideload an old or differently
signed image. Do not reuse a boot image from a different build.

If the phone will not boot, stop and use your recovery plan instead of
experimenting with individual partitions.
