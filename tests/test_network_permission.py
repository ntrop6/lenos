"""GrapheneOS: the network (INTERNET) permission is a runtime permission.

Tier 1 feature #1 of the lenOS roadmap: port GrapheneOS's "special runtime
permissions" (SRT) framework and use it to make ``android.permission.INTERNET``
revocable by the user, without breaking apps that were written for stock
Android (where INTERNET could not be revoked):

* INTERNET is declared as ``dangerous|instant`` and is *granted by default*
  (auto-granted at install, and to pre-installed system apps on evaluation).
* When the user revokes it, the app keeps running in "internet compat" mode:
  the OS pretends that the network is down (ConnectivityManager/DownloadManager
  return empty results, NSD gets a stubbed connector) and the app's own
  ``checkPermission(INTERNET)`` self-checks are spoofed as granted, so badly
  written apps do not crash with SecurityException.
* The kernel-level block is AOSP's existing netd BPF per-UID socket filtering,
  driven by ``PermissionMonitor`` — no extra plumbing is needed.

The tests pin the patch contents (framework, Connectivity module, permission UI)
and the framework invariants the feature relies on.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestNetworkPermissionFramework(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0025-lenos-network-permission.patch"]

    MANIFEST = "core/res/AndroidManifest.xml"
    STRINGS = "core/res/res/values/strings.xml"
    SRT = "core/java/android/content/pm/SrtPermissions.java"
    APU = "core/java/android/content/pm/AppPermissionUtils.java"
    SPRU = "core/java/android/content/pm/SpecialRuntimePermAppUtils.java"
    BIND = "core/java/android/app/AppBindArgs.java"
    PM = "core/java/android/permission/PermissionManager.java"
    DM = "core/java/android/app/DownloadManager.java"
    AT = "core/java/android/app/ActivityThread.java"
    AIDL = "core/java/android/app/IApplicationThread.aidl"
    AMS = "services/core/java/com/android/server/am/ActivityManagerService.java"
    NATW = "services/core/java/com/android/server/am/NativeApplicationThreadWrapper.java"
    SRPU = "services/core/java/com/android/server/pm/permission/SpecialRuntimePermUtils.java"
    PMH = "services/core/java/com/android/server/ext/PackageManagerHooks.java"
    PMSI = "services/core/java/com/android/server/pm/permission/PermissionManagerServiceInternal.java"
    IPH = "services/core/java/com/android/server/pm/InstallPackageHelper.java"
    POLICY = ("services/permission/java/com/android/server/permission/access/permission/"
              "AppIdPermissionPolicy.kt")
    SERVICE = ("services/permission/java/com/android/server/permission/access/permission/"
               "PermissionService.kt")
    API = "core/api/system-current.txt"

    def test_internet_is_a_runtime_permission(self):
        text = self.text(self.MANIFEST)
        start = text.index('android:name="android.permission.INTERNET"')
        decl = text[start:start + 400]
        self.assertIn('android:protectionLevel="dangerous|instant"', decl)
        # GrapheneOS keeps the permission out of the framework group and
        # presents it as "Network" via PermissionMapping instead.
        self.assertIn('android:permissionGroup="android.permission-group.UNDEFINED"', decl)
        # The NETWORK group is declared and has its string resources.
        self.assert_contains(
            self.MANIFEST,
            '<permission-group android:name="android.permission-group.NETWORK"',
            'android:icon="@drawable/perm_group_network"')
        self.assert_contains(
            self.STRINGS,
            '<string name="permgrouplab_network">Network</string>',
            '<string name="permgroupdesc_network">access the network</string>')

    def test_srt_flags_and_spoofing(self):
        self.assert_contains(
            self.SRT,
            "public static final int FLAG_INTERNET_COMPAT_ENABLED = 1;",
            "SpecialRuntimePermAppUtils.enableInternetCompat();",
            "case Manifest.permission.INTERNET:",
            "return SpecialRuntimePermAppUtils.isInternetCompatEnabled();")
        self.assert_contains(
            self.SPRU,
            "public static boolean isInternetCompatEnabled() {",
            "public static void enableInternetCompat() {")
        # AppPermissionUtils is the framework-wide entry point.
        self.assert_contains(self.APU, "return SrtPermissions.shouldSpoofSelfCheck(permName);")

    def test_both_permission_self_check_sites_are_spoofed(self):
        text = self.text(self.PM)
        # checkPermissionUncached(a) and checkPackageNamePermissionUncached(b).
        self.assertEqual(text.count("AppPermissionUtils.shouldSpoofSelfCheck("), 2)
        self.assertIn("res = PERMISSION_GRANTED;", text)
        self.assertIn("uid == android.os.Process.myUid()", text)
        self.assertIn("pkgName.equals(ActivityThread.currentPackageName())", text)

    def test_download_manager_returns_empty_results(self):
        text = self.text(self.DM)
        self.assertEqual(text.count("SpecialRuntimePermAppUtils.isInternetCompatEnabled()"), 4)
        # The row-id based APIs return invalid ids; the query returns no rows.
        self.assertIn("return new MatrixCursor(projection);", text)
        self.assertIn("// invalid id (DownloadProvider uses SQLite and returns a row id)", text)

    def test_app_bind_args_carry_the_flags_to_the_app_process(self):
        self.assert_contains(
            self.BIND,
            'String KEY_FLAGS_ARRAY = "flagsArr";',
            "int FLAGS_IDX_SPECIAL_RUNTIME_PERMISSIONS = 0;",
            "int FLAGS_ARRAY_LEN = 10;")
        self.assert_contains(
            self.AIDL,
            "void bindApplication(in Bundle extraArgs, in String packageName, in ApplicationInfo info,")
        self.assert_contains(
            self.AT,
            "Bundle extraArgs;",
            "data.extraArgs = extraArgs;",
            "int[] flagsArr = extraArgs.getIntArray(AppBindArgs.KEY_FLAGS_ARRAY);",
            "SrtPermissions.setFlags(")
        self.assert_contains(
            self.AMS,
            "Bundle extraArgs = PackageManagerHooks.getExtraAppBindArgs(mContext,",
            "mPackageManagerInt, appInfo.packageName, app.getApplicationUid(), pid);",
            "thread.bindApplication(",
            "extraArgs,")
        self.assert_contains(self.NATW, "Bundle extraArgs,")

    def test_server_side_flag_computation(self):
        self.assert_contains(
            self.PMH,
            "flagsArr[AppBindArgs.FLAGS_IDX_SPECIAL_RUNTIME_PERMISSIONS] =",
            "SpecialRuntimePermUtils.getFlags(pkg, pkgState, userId);",
            "b.putIntArray(AppBindArgs.KEY_FLAGS_ARRAY, flagsArr);")
        self.assert_contains(
            self.SRPU,
            "private static final ArraySet<String> specialRuntimePermissions = new ArraySet<>(new String[] {",
            "Manifest.permission.INTERNET,",
            "return true;",
            "case Manifest.permission.INTERNET:",
            "flags |= SrtPermissions.FLAG_INTERNET_COMPAT_ENABLED;",
            "if (pkgState.isSystem() || pkgState.isUpdatedSystemApp()) {",
            'String key = Manifest.permission.INTERNET + ".mode";',
            'if ("runtime".equals(metadata.getString(key))) {',
            "Manifest.permission.INTERNET, VirtualDeviceManager.PERSISTENT_DEVICE_ID_DEFAULT,",
            "userId) != PackageManager.PERMISSION_GRANTED;")
        # The SRT registry is shared with the sensors permission (fwb/0026):
        # it is declared here so the sensors patch only adds its enforcement.
        text = self.text(self.SRPU)
        start = text.index("specialRuntimePermissions = new ArraySet<>")
        block = text[start:text.index("});", start)]
        self.assertIn("Manifest.permission.INTERNET,", block)
        self.assertIn("Manifest.permission.OTHER_SENSORS,", block)

    def test_auto_grant_only_on_new_install(self):
        # The framework carries "newly installed in user" through the install
        # params so an app update never re-grants a revoked permission.
        self.assert_contains(
            self.PMSI,
            "public boolean isNewlyInstalledInUserId(int userId) {",
            "return mNewlyInstalledInUserIds.get(userId, false);",
            "public void setNewlyInstalledInUserId(int userId) {")
        text = self.text(self.IPH)
        self.assertEqual(text.count("setNewlyInstalledInUserId("), 3)  # 1 def + 2 call sites
        self.assertIn("permissionParamsBuilder.setNewlyInstalledInUserId(userId);", text)
        self.assert_contains(
            self.SERVICE,
            "if (params.isNewlyInstalledInUserId(userId)) {",
            "SpecialRuntimePermUtils.getAll().forEach { perm ->",
            "PackageInstaller.SessionParams.PERMISSION_STATE_GRANTED,")
        # The auto-granted permission can not re-appear through a legacy code
        # path: pre-M runtime handling and legacy review skip SRT permissions.
        self.assert_contains(
            self.SERVICE,
            "androidPackage.targetSdkVersion < Build.VERSION_CODES.M",
            "&& !isSpecialRuntimePermission(permissionName)")
        self.assert_contains(
            self.POLICY,
            "if (isSpecialRuntimePermission(permissionName)) {",
            "return@forEach",
            "if (isImplicitSpecialRuntimeSplit(androidPackage, permissionName)) {",
            "targetSdkVersion < Build.VERSION_CODES.M && !isSpecialRuntimePermission(permissionName)",
            "if (!newFlags.hasBits(PermissionFlags.USER_SET)",
            "if (isSpecialRuntimePermission(sourcePermissionName)) {",
            "newFlags = newFlags or PermissionFlags.RUNTIME_GRANTED")

    def test_system_app_permission_survives_boot(self):
        # Pre-installed system apps are never "newly installed": the policy
        # grants them the SRT permission on evaluation unless the user chose.
        text = self.text(self.POLICY)
        start = text.index("!newFlags.hasBits(PermissionFlags.USER_SET)")
        grant = text[start:start + 300]
        self.assertIn("requestingPackageStates.anyIndexed { _, it -> it.isSystem }", grant)
        self.assertIn("newFlags = newFlags or PermissionFlags.RUNTIME_GRANTED", grant)

    def test_system_api_surface(self):
        self.assert_contains(
            self.API,
            "public class SpecialRuntimePermAppUtils {",
            "method public static boolean isInternetCompatEnabled();")

    def test_java_syntax(self):
        for rel in (self.SRT, self.APU, self.SPRU, self.BIND, self.PM, self.DM,
                    self.AT, self.AMS, self.NATW, self.SRPU, self.PMH, self.PMSI, self.IPH):
            self.assert_java_syntax(rel)

    def test_xml(self):
        for rel in (self.MANIFEST, self.STRINGS):
            self.assert_xml(rel)

    def test_kotlin_balance(self):
        self.assert_balanced(self.POLICY)
        self.assert_balanced(self.SERVICE)


class TestNetworkPermissionConnectivity(LenosPatchTest):
    PROJECT = "packages/modules/Connectivity"
    PATCHES = ["0002-lenos-network-permission.patch"]

    CM = "framework/src/android/net/ConnectivityManager.java"
    NSD = "framework-t/src/android/net/nsd/NsdManager.java"

    def test_connectivity_manager_gates(self):
        text = self.text(self.CM)
        self.assertEqual(text.count("SpecialRuntimePermAppUtils.isInternetCompatEnabled()"), 32)
        self.assert_contains(
            self.CM,
            "import android.content.pm.SpecialRuntimePermAppUtils;")
        # Spot-check representative gates and their "network is down" answers.
        for method, ret in (
            ("public NetworkInfo getActiveNetworkInfo() {", "return null;"),
            ("public Network getActiveNetwork() {", "return null;"),
            ("public Network[] getAllNetworks() {", "return new Network[0];"),
            ("public NetworkCapabilities getNetworkCapabilities(@Nullable Network network) {",
             "return null;"),
            ("public String[] getTetherableIfaces() {", "return new String[0];"),
            ("public boolean isActiveNetworkMetered() {", "return false;"),
            ("public void registerDefaultNetworkCallback(@NonNull NetworkCallback networkCallback) {",
             "return;"),
            ("public void reportNetworkConnectivity(@Nullable Network network, boolean hasConnectivity) {",
             "return;"),
        ):
            start = text.index(method)
            body = text[start:start + 400]
            self.assertIn("SpecialRuntimePermAppUtils.isInternetCompatEnabled()", body, method)
            self.assertIn(ret, body, method)

    def test_nsd_is_stubbed_in_compat_mode(self):
        text = self.text(self.NSD)
        self.assertIn("if (android.content.pm.SpecialRuntimePermAppUtils.isInternetCompatEnabled()) {",
                      text)
        self.assertIn("// INsdManager#connect() enforces INTERNET permission", text)
        self.assertIn("mService = createStubbedINsdServiceConnector();", text)
        # The stub must satisfy the A17 INsdServiceConnector interface,
        # including the methods added since A16.
        self.assert_contains(
            self.NSD,
            "static class NsdServiceConnectorStub implements INsdServiceConnector {",
            "callback.onRegisterServiceFailed(listenerKey, FAILURE_INTERNAL_ERROR);",
            "callback.onDiscoverServicesFailed(listenerKey, FAILURE_INTERNAL_ERROR);",
            "callback.onResolveServiceFailed(listenerKey, FAILURE_INTERNAL_ERROR);",
            "callback.onServiceInfoCallbackRegistrationFailed(listenerKey, FAILURE_INTERNAL_ERROR);",
            "@Override public void registerServiceInfoCallbackWithRequest(int listenerKey,",
            "@Override public void injectOffloadEngineResponse(NsdServiceInfo serviceInfo,",
            "@Override public void checkPermissionForService(String serviceName, String serviceType,",
            "resultReceiver.send(SERVICE_PERMISSION_DENIED, null);",
            "@Override public android.os.IBinder asBinder() { return null; }")

    def test_java_syntax(self):
        self.assert_java_syntax(self.CM)
        self.assert_java_syntax(self.NSD)


class TestNetworkPermissionUi(LenosPatchTest):
    PROJECT = "packages/modules/Permission"
    PATCHES = ["0002-lenos-network-permission.patch"]

    MAPPING = ("PermissionController/src/com/android/permissioncontroller/permission/utils/"
               "PermissionMapping.kt")
    KU = ("PermissionController/src/com/android/permissioncontroller/permission/utils/"
          "KotlinUtils.kt")
    PERM = ("PermissionController/src/com/android/permissioncontroller/permission/model/"
            "Permission.java")
    GROUP = ("PermissionController/src/com/android/permissioncontroller/permission/model/"
             "AppPermissionGroup.java")
    USAGE = ("PermissionController/src/com/android/permissioncontroller/permission/ui/model/"
             "v31/PermissionUsageControlPreferenceUtils.kt")
    HIB = ("PermissionController/src/com/android/permissioncontroller/permission/data/"
           "HibernationSettingStateLiveData.kt")
    AUTO = ("PermissionController/src/com/android/permissioncontroller/permission/service/"
            "AutoRevokePermissions.kt")

    def test_mapping_presents_internet_as_network_group(self):
        self.assert_contains(
            self.MAPPING,
            "SPECIAL_RUNTIME_PERMISSIONS[Manifest.permission.INTERNET] =",
            "PLATFORM_PERMISSIONS[Manifest.permission.INTERNET] = Manifest.permission_group.NETWORK",
            "fun isSpecialRuntimePermission(permission: String): Boolean {",
            "fun isSpecialRuntimePermissionGroup(permissionGroup: String): Boolean {")

    def test_permission_treated_as_granted_in_compat_mode(self):
        self.assert_contains(
            self.PERM,
            "&& (!isReviewRequired() || isSpecialRuntimePermission(mName));")
        text = self.text(self.GROUP)
        self.assertEqual(
            text.count("|| isSpecialRuntimePermission(permission.getName()))"), 2)
        text = self.text(self.KU)
        self.assertEqual(text.count("|| isSpecialRuntimePermission(perm.name)"), 2)

    def test_usage_and_hibernation_screens(self):
        self.assert_contains(
            self.USAGE,
            "if (count == 0 && !PermissionMapping.isSpecialRuntimePermissionGroup(groupName)) {",
            "if (PermissionMapping.isSpecialRuntimePermissionGroup(groupName)) {")
        self.assert_contains(
            self.HIB,
            "!isSpecialRuntimePermissionGroup(groupName)",
            "import "
            "com.android.permissioncontroller.permission.utils.PermissionMapping.isSpecialRuntimePermissionGroup")
        self.assert_contains(
            self.AUTO,
            "!PermissionMapping.isSpecialRuntimePermissionGroup(groupName)")

    def test_java_syntax(self):
        self.assert_java_syntax(self.PERM)
        self.assert_java_syntax(self.GROUP)

    def test_kotlin_balance(self):
        for rel in (self.MAPPING, self.KU, self.USAGE, self.HIB, self.AUTO):
            self.assert_balanced(rel)


if __name__ == "__main__":
    unittest.main()
