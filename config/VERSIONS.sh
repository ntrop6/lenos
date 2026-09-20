# lenOS pinned external tooling and prebuilts.
# Every artifact downloaded by build/lenos.sh is verified against the
# sha256 recorded here. Bump a pin ONLY after verifying the new artifact
# yourself; never let the build resolve "latest" on its own.

readonly LENOS_VERSION="1.0.0"

readonly LINEAGE_BRANCH="lineage-23.2"
readonly DEVICE_CODENAME="asteroids"
readonly AOSP_TAG="android-16.0.0_r4"

# avbroot: OTA re-signing / custom-key AVB / init_boot LKM injection support.
readonly AVBROOT_VERSION="3.34.1"
readonly AVBROOT_ASSET="avbroot-${AVBROOT_VERSION}-x86_64-unknown-linux-gnu.zip"
readonly AVBROOT_URL="https://github.com/chenxiaolong/avbroot/releases/download/v${AVBROOT_VERSION}/${AVBROOT_ASSET}"
readonly AVBROOT_SHA256="b1740ebf92d503cf2e81ca443afa4b615fb97ec365e170b71791ed72d9e559f8"

# ReSukiSU: KernelSU-family root. The manager APK embeds the GKI kernelsu.ko
# LKM for the pinned KMI inside lib/arm64-v8a/libksud.so; ksud boot-patch
# inserts it into init_boot's ramdisk (phone-assisted, see README).
readonly RESUKISU_VERSION="4.2.0-rc2"
readonly RESUKISU_BUILD="35144"
readonly RESUKISU_KMI="android15-6.6"
readonly RESUKISU_APK_NAME="ReSukiSU_v${RESUKISU_VERSION}_${RESUKISU_BUILD}-arm64-v8a-release.apk"
readonly RESUKISU_APK_URL="https://github.com/ReSukiSU/ReSukiSU/releases/download/${RESUKISU_VERSION}/${RESUKISU_APK_NAME}"
readonly RESUKISU_APK_SHA256="4d8c3fcca5f40d3250ad312cb2a755facb9bbcfc2a1317050f76615381b5994b"

# Optional OEM unlock on boot module (safety net while iterating; remove it
# before final relock if you want the bootloader to stay locked across boots).
readonly OEM_UNLOCK_VERSION="1.4"
readonly OEM_UNLOCK_ASSET="OEMUnlockOnBoot-${OEM_UNLOCK_VERSION}-release.zip"
readonly OEM_UNLOCK_URL="https://github.com/chenxiaolong/OEMUnlockOnBoot/releases/download/v${OEM_UNLOCK_VERSION}/${OEM_UNLOCK_ASSET}"
readonly OEM_UNLOCK_SHA256="052db77e35c5e0e352dce0a7dc8c67f6344d32977f34a992636a32f20df39e6d"

# Cromite browser, arm64, presigned system app. GPLv3; keep the source tag
# reference in NOTICE when bumping.
readonly CROMITE_TAG="v153.0.8010.37-11507ac1061b5ea227806f5e84db5a57df6ccf6a"
readonly CROMITE_APK_NAME="arm64_ChromePublic.apk"
readonly CROMITE_URL="https://github.com/uazo/cromite/releases/download/${CROMITE_TAG}/${CROMITE_APK_NAME}"
readonly CROMITE_SHA256="9db12af1af021f42b4371e76d0e9fe476a7085bbbbc76bc410a538d028bf6071"
