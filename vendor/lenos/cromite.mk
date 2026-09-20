# Cromite, presigned prebuilt (GPL-3.0; see NOTICE for the pinned source
# tag). The integrator fetches and sha256-verifies the APK into
# vendor/lenos/prebuilt/Cromite.apk before the build.
ifneq (,$(wildcard vendor/lenos/prebuilt/Cromite.apk))
PRODUCT_PACKAGES += \
    Cromite
else
$(warning "vendor/lenos/prebuilt/Cromite.apk is missing; run tools/fetch-cromite.sh or accept a browserless build")
endif
