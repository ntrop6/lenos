"""GrapheneOS: user-revocable sensors permission (OTHER_SENSORS).

Tier 2 feature. It plugs into the "special runtime permissions" (SRT)
framework introduced with the network permission (``fwb/0025``):

* ``android.permission.OTHER_SENSORS`` is a ``dangerous`` permission in its
  own ``android.permission-group.OTHER_SENSORS`` group ("Sensors").
* Every sensor that has no other required permission (accelerometer, gyro,
  compass, ...) is tagged with ``OTHER_SENSORS`` at the ``Sensor`` object
  level (``libs/sensor/Sensor.cpp``); the sensor service then denies access
  for app UIDs that do not hold it (``SensorService::canAccessSensor``).
* As an SRT it is granted by default on install unless the
  ``AUTO_GRANT_OTHER_SENSORS_PERMISSION`` ExtSettings setting (default on) is
  turned off, in which case the user grants it manually. App updates never
  re-grant a revoked permission (the ``isNewlyInstalledInUserId`` gate from
  the network port).
* Denied accesses post a rate-limited "X tried to access sensors"
  notification with a "Don't show again" action (sets USER_SET and suppresses
  the notification for that app).
* System processes (UID < AID_APP_START, e.g. the closed-source gpsd daemon)
  keep their access. Apps targeting pre-Q that used the step counter without
  ACTIVITY_RECOGNITION get OTHER_SENSORS enforced instead.

The SRT registry and the PermissionController mapping live in the owning
network-permission patches (``fwb/0025`` / ``Permission/0002``); this module
tests the sensors-specific enforcement and the notification stack.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestSensorsPermissionFramework(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = [
        "0025-lenos-network-permission.patch",
        "0026-lenos-sensors-permission.patch",
    ]

    MANIFEST = "core/res/AndroidManifest.xml"
    STRINGS = "core/res/res/values/strings.xml"
    SRPU = "services/core/java/com/android/server/pm/permission/SpecialRuntimePermUtils.java"
    PMN = "services/core/java/com/android/server/pm/PackageManagerNative.java"
    NOTIF = ("services/core/java/com/android/server/ext/"
             "MissingSpecialRuntimePermissionNotification.java")
    RECEIVER = "services/core/java/com/android/server/ext/IntentReceiver.java"
    SSE = "services/core/java/com/android/server/ext/SseUtils.java"
    CHANNELS = "core/java/com/android/internal/notification/SystemNotificationChannels.java"
    PROTO = "proto/src/system_messages.proto"

    def test_manifest_declares_the_sensors_permission(self):
        self.assert_contains(
            self.MANIFEST,
            '<permission-group android:name="android.permission-group.OTHER_SENSORS"',
            'android:icon="@drawable/perm_group_location"',
            'android:label="@string/permgrouplab_otherSensors"',
            'android:description="@string/permgroupdesc_otherSensors"',
            'android:priority="1000"',
            '<permission android:name="android.permission.OTHER_SENSORS"',
            'android:permissionGroup="android.permission-group.UNDEFINED"',
            'android:protectionLevel="dangerous" />')
        self.assert_xml(self.MANIFEST)

    def test_strings(self):
        self.assert_contains(
            self.STRINGS,
            '<string name="permgrouplab_otherSensors">Sensors</string>',
            '<string name="permgroupdesc_otherSensors">'
            'access sensor data about orientation, movement, etc.</string>',
            'name="permlab_otherSensors"',
            'name="permdesc_otherSensors"',
            '<string name="notification_channel_missing_permission">'
            'Missing permission</string>',
            '<string name="missing_sensors_permission_title">'
            '%1$s tried to access sensors</string>',
            '<string name="missing_sensors_permission_message">'
            'Tap to ask for permission.</string>',
            '<string name="notification_action_dont_show_again">'
            'Don\u2019t show again</string>')
        self.assert_xml(self.STRINGS)

    def test_srt_registry_and_auto_grant(self):
        self.assert_contains(
            self.SRPU,
            "Manifest.permission.OTHER_SENSORS,",
            "ExtSettings.AUTO_GRANT_OTHER_SENSORS_PERMISSION.get(ctx, userIdForSettings)",
            "um.getProfileParentId(userId)")
        text = self.text(self.SRPU)
        start = text.index("specialRuntimePermissions = new ArraySet<>")
        block = text[start:text.index("});", start)]
        self.assertIn("Manifest.permission.INTERNET,", block)
        self.assertIn("Manifest.permission.OTHER_SENSORS,", block)
        # Sensors have no bind-time compatibility mode: only INTERNET sets a
        # flag in the bind-args computation.
        flags_body = text[text.index("public static int getFlags"):
                          text.index("private static boolean shouldEnableInternetCompat")]
        self.assertIn("case Manifest.permission.INTERNET:", flags_body)
        self.assertNotIn("OTHER_SENSORS", flags_body)

    def test_denied_op_reaches_system_server(self):
        self.assert_contains(
            self.PMN,
            "public void onDeniedSpecialRuntimePermissionOp(String permissionName, int uid,",
            "if (Binder.getCallingUid() != android.os.Process.SYSTEM_UID) {",
            "throw new SecurityException();",
            ".maybeShow(mPm.mContext, permissionName, uid, packageName);")

    def test_notification_is_rate_limited_and_respects_dont_show_again(self):
        self.assert_contains(
            self.NOTIF,
            "private static final ArrayMap<String, SparseLongArray> lastShownTracker",
            "if (prevTs != 0 && (timestamp - prevTs) < 30_000L) {",
            "if ((permFlags & PackageManager.FLAG_PERMISSION_USER_SET) != 0) {",
            "SystemMessage.NOTE_MISSING_PERMISSION_OTHER_SENSORS",
            "R.string.missing_sensors_permission_message",
            "PackageManager.ACTION_REQUEST_PERMISSIONS_FOR_OTHER",
            "R.string.notification_action_dont_show_again",
            ".updatePermissionFlags(packageName, permissionName, flag, flag, user);",
            ".cancelAsUser(null, notifIdForPermission(permissionName), user);")
        self.assert_java_syntax(self.NOTIF)

    def test_notification_helpers(self):
        self.assert_contains(
            self.RECEIVER,
            "ctx.registerReceiver(instance, filter, null,",
            "Context.RECEIVER_NOT_EXPORTED);",
            "public PendingIntent getPendingIntent(@Nullable Bundle args) {",
            "i.setIdentifier(Long.toString(id));")
        self.assert_contains(
            self.SSE,
            "public static void addNotifAction(",
            "dst.addAction(nb.build());")
        self.assert_java_syntax(self.RECEIVER)
        self.assert_java_syntax(self.SSE)

    def test_notification_channel(self):
        self.assert_contains(
            self.CHANNELS,
            'public static final String MISSING_PERMISSION = "MISSING_PERMISSION";',
            "context.getString(R.string.notification_channel_missing_permission)",
            "missingPermissionChannel.setBlockable(true);")

    def test_proto_id(self):
        text = self.text(self.PROTO)
        self.assertIn("NOTE_MISSING_PERMISSION_OTHER_SENSORS = 500;", text)
        self.assertLess(text.index("NOTE_MISSING_PERMISSION_OTHER_SENSORS = 500;"),
                        text.index("// ADD_NEW_IDS_ABOVE_THIS_LINE"))

    def test_java_syntax(self):
        for rel in (self.PMN, self.CHANNELS, self.SRPU):
            self.assert_java_syntax(rel)


class TestSensorsPermissionNative(LenosPatchTest):
    PROJECT = "frameworks/native"
    PATCHES = ["0001-lenos-sensors-permission.patch"]

    SENSOR = "libs/sensor/Sensor.cpp"
    SERVICE = "services/sensorservice/SensorService.cpp"

    def test_permissionless_sensors_require_other_sensors(self):
        text = self.text(self.SENSOR)
        start = text.index(
            "Sensor::Sensor(struct sensor_t const& hwSensor, const uuid_t& uuid,")
        body = text[start:start + 1500]
        self.assertIn('mRequiredPermission = "android.permission.OTHER_SENSORS";', body)
        # Set right after the uuid, i.e. for every HAL sensor that does not
        # declare a more specific permission.
        self.assertLess(body.index("mUuid = uuid;"),
                        body.index('mRequiredPermission = "android.permission.OTHER_SENSORS";'))

    def test_sensor_service_enforces_the_permission(self):
        self.assert_contains(
            self.SERVICE,
            "bool protectedByOtherSensorsPerm = false;",
            'if (sensor.getRequiredPermission() == "android.permission.OTHER_SENSORS") {',
            "if (IPCThreadState::self()->getCallingUid() < AID_APP_START) {",
            "// The lack of this check led to crashes of the closed-source gpsd daemon.",
            "__ANDROID_API_P__",
            'const String16 requiredPermission("android.permission.OTHER_SENSORS");',
            "protectedByOtherSensorsPerm = true;",
            "canAccess = checkPermission(requiredPermission,")

    def test_denied_access_notifies_system_server(self):
        self.assert_contains(
            self.SERVICE,
            'defaultServiceManager()->getService(String16("package_native"))',
            "interface_cast<content::pm::IPackageManagerNative>(binder)",
            "AutoCallerClear acc;",
            "packageManager->onDeniedSpecialRuntimePermissionOp(",
            'String16("android.permission.OTHER_SENSORS"),',
            "callingUid, opPackageName);")

    def test_syntax(self):
        self.assert_balanced(self.SERVICE)
        self.assert_balanced(self.SENSOR)


class TestSensorsPermissionAidl(LenosPatchTest):
    """A17 moved IPackageManagerNative.aidl from frameworks/native to frameworks/base."""

    PROJECT = "frameworks/base"
    PATCHES = ["0029-lenos-native-permission-aidl.patch"]

    AIDL = "native/android/aidl/android/content/pm/IPackageManagerNative.aidl"

    def test_aidl_method(self):
        self.assert_contains(
            self.AIDL,
            "oneway void onDeniedSpecialRuntimePermissionOp(in String permissionName, int uid,")


class TestSensorsPermissionUiMapping(LenosPatchTest):
    PROJECT = "packages/modules/Permission"
    PATCHES = ["0002-lenos-network-permission.patch"]

    MAPPING = ("PermissionController/src/com/android/permissioncontroller/permission/utils/"
               "PermissionMapping.kt")

    def test_sensors_group_mapping(self):
        self.assert_contains(
            self.MAPPING,
            "PLATFORM_PERMISSIONS[Manifest.permission.OTHER_SENSORS] =",
            "SPECIAL_RUNTIME_PERMISSIONS[Manifest.permission.OTHER_SENSORS] =",
            "Manifest.permission_group.OTHER_SENSORS")

    def test_syntax(self):
        self.assert_balanced(self.MAPPING)


if __name__ == "__main__":
    unittest.main()
