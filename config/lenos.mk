# lenOS product configuration.
#
# Inherited from device/nothing/asteroids/lenos_asteroids.mk (see
# patches/device_nothing_asteroids/0001-add-lenos-product.patch).
#
# Branding is ro.lenos.* only. ro.build.*, the build fingerprint and the
# device identity stay stock on purpose: changing them breaks app
# compatibility, attestation and Nothing factory tooling.

# lenOS companion app ("lenOS security"). Everything else in the UI is stock
# LineageOS Settings; this app only hosts controls that Settings does not have.
PRODUCT_PACKAGES += \
    LenosSecurity

# Experimental features are opt-in at build time. The driver only applies the
# patches-experimental/ series and installs experimental/app/ when
# LENOS_EXPERIMENTAL=1; a normal 1.0 build never inherits this fragment.
ifneq ($(filter 1 true yes,$(LENOS_EXPERIMENTAL)),)
$(call inherit-product, vendor/lenos/config/lenos-experimental.mk)
endif

# Privacy overlays (enabled at boot, no user interaction required):
# * LenosFrameworksOverlay        - non-Google NTP fallback pool (framework-res)
# * LenosNetworkStackOverlay      - Cloudflare connectivity-check probes
# * LenosSettingsProviderOverlay  - hardened first-boot (Settings.Global) defaults
PRODUCT_PACKAGES += \
    LenosFrameworksOverlay \
    LenosNetworkStackOverlay \
    LenosSettingsProviderOverlay

# GrapheneOS parity: pre-installed APEXes stay uncompressed. The AOSP product
# fragment updatable_apex.mk (pulled in by full_base_telephony.mk inside
# lineage_asteroids.mk) sets PRODUCT_COMPRESSED_APEX := true; this file is
# inherited after it, so the assignment below wins. The cost is a few MiB on
# the system partition; the gain is that boot no longer has to decompress APEX
# payloads before mounting them, which removes a decompression/parsing surface
# from early boot.
PRODUCT_COMPRESSED_APEX := false

# Privileged permission allowlist for LenosSecurity. The APK is signed with
# the platform key, so most permissions are already satisfied by the signature;
# the allowlist keeps the app working (and documents the intent) if it is ever
# built without the platform certificate.
PRODUCT_COPY_FILES += \
    vendor/lenos/config/privapp-permissions-org.lenos.security.xml:$(TARGET_COPY_OUT_SYSTEM)/etc/permissions/privapp-permissions-org.lenos.security.xml

# Product properties are loaded last by init, so they override values from
# system/system_ext/vendor/odm (see system/core/init/property_service.cpp).
# Keep this list short and commented; anything user-visible belongs in the
# SettingsProvider defaults or a documented toggle instead.
PRODUCT_PRODUCT_PROPERTIES += \
    ro.lenos.version=1.0.0 \
    ro.lenos.base=lineage-24.0 \
    ro.lenos.dns=dns.quad9.net \
    # Auto-reboot-to-BFU backend: init timer (system/core/0001), armed from
    # the keyguard showing-state in frameworks/base (0003). The timeout lives
    # in Settings.Global."settings_reboot_after_timeout" (18h default via
    # android.ext.settings, frameworks/base/0006). Status string for the
    # lenOS security app.
    ro.lenos.security.auto_bfu=init \
    # Duress credential backend: LockSettingsService (frameworks/base/0005)
    # with the lenOS security app as UI. Destructive by design; entering a
    # duress credential at any prompt destroys the storage keys. Status string
    # for the app.
    ro.lenos.security.duress=framework \
    persist.traced.enable=0 \
    persist.logd.size.radio=64K \
    persist.vendor.verbose_logging_enabled=0 \
    persist.vendor.radio.adb_log_on=0 \
    persist.vendor.radio.ims_log_enabled=0 \
    persist.vendor.sys.modem.logging.enable=0 \
    persist.vendor.radio.snapshot_enabled=0 \
    persist.vendor.radio.snapshot_timer=0
