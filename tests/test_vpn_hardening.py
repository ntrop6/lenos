"""VPN leak blocking: netd lockdown fixes, multicast firewall, NSD lockdown.

GrapheneOS-derived hardening for "Block connections without VPN" (see
docs/graphene-porting.md section 12):

* netd: the system resolver no longer marks every DNS query as protected from
  the VPN, so a lockdown device with all VPNs down can't fall back to the
  default network's DNS servers (GrapheneOS ``82da9204``).
* netd: a multicast firewall drops multicast/IGMP/MLD in, out and through
  ``tun+`` interfaces, closing the cross-profile VPN side channel while
  keeping inbound router advertisements (GrapheneOS ``dcef5ccb`` +
  ``d57ea8dc``).
* Connectivity: regular apps get no NSD connector while an always-on VPN with
  lockdown is active, because discovery traffic would bypass the tunnel
  (GrapheneOS NsdService check; helper ``android.ext.ConnectivityUtil``).
* fwb: an always-on VPN is no longer unset just because its package is
  temporarily unsupported (safe mode, disabled app); the lockdown fail-safe
  stays configured (GrapheneOS Vpn.java behaviour).

GrapheneOS's SockDiag IP-address logging fix (``40c47da2``) and the DnsResolver
``.local`` transport filter (AOSP ``a17ba5aee1``, 2022) are already present in
LineageOS 24.0, so no patch is needed for them.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestNetdVpnLeakBlocking(LenosPatchTest):
    PROJECT = "system/netd"
    PATCHES = ["0001-lenos-vpn-leak-blocking.patch"]

    NETCTRL = "server/NetworkController.cpp"
    CTRL = "server/Controllers.cpp"
    CTRL_H = "server/Controllers.h"
    FW = "server/MulticastFirewallController.cpp"
    FW_H = "server/MulticastFirewallController.h"
    TEST = "server/MulticastFirewallControllerTest.cpp"
    BP = "server/Android.bp"

    def test_dns_mark_is_derived_from_caller(self):
        self.assert_contains(
            self.NETCTRL,
            "fwmark.protectedFromVpn = canProtectLocked(uid, *netId);",
            "fwmark.permission = getPermissionForUserLocked(uid);")
        self.assert_not_contains(self.NETCTRL, "fwmark.permission = PERMISSION_SYSTEM;")

    def test_multicast_controller_is_wired(self):
        self.assert_contains(
            self.CTRL,
            "MulticastFirewallController::LOCAL_INPUT",
            "MulticastFirewallController::LOCAL_FORWARD",
            "MulticastFirewallController::LOCAL_OUTPUT",
            "multicastFirewallCtrl.setupIptablesHooks();")
        self.assert_contains(self.CTRL_H,
                             '#include "MulticastFirewallController.h"',
                             "MulticastFirewallController multicastFirewallCtrl;")

    def test_rules_cover_v4_v6_igmp_mld_and_keep_ra(self):
        self.assert_contains(
            self.FW,
            '":mfw_INPUT -"',
            '"-4 -A mfw_INPUT -i %s -d %s -j DROP"',
            '"-6 -A mfw_OUTPUT -o %s -d %s -j DROP"',
            "router-advertisement ",
            "router-solicitation ",
            "IGMP_PROTOCOL_NUMBER = 2",
            "MLDV2_MC_LISTENER_REPORT = 143")
        self.assert_contains(
            self.FW_H,
            "class MulticastFirewallController",
            "static const char* LOCAL_INPUT;")

    def test_unit_tests_and_build_registration(self):
        self.assert_contains(
            self.BP,
            '"MulticastFirewallController.cpp"',
            '"MulticastFirewallControllerTest.cpp"')
        self.assert_contains(
            self.TEST,
            "TEST_F(MulticastFirewallControllerTest, TestFirewall)",
            "router-advertisement -j RETURN")
        self.assert_contains(
            "server/ControllersTest.cpp",
            '":mfw_INPUT -\\n"',
            '":mfw_FORWARD -\\n"',
            '":mfw_OUTPUT -\\n"')

    def test_balanced_cpp(self):
        self.assert_balanced(self.FW)
        self.assert_balanced(self.FW_H)


class TestNsdLockdown(LenosPatchTest):
    PROJECT = "packages/modules/Connectivity"
    PATCHES = ["0001-lenos-nsd-lockdown.patch"]

    NSD = "service-t/src/com/android/server/NsdService.java"

    def test_regular_apps_are_refused_under_lockdown(self):
        self.assert_contains(
            self.NSD,
            "android.ext.ConnectivityUtil.isRegularAppWithLockdownVpnEnabled(mContext, uid)",
            "is under VPN lockdown, returning null",
            "return null;")

    def test_system_apps_stay_allowed(self):
        # The exemption lives in the shared helper; NsdService documents it.
        self.assert_contains(
            self.NSD,
            "apps keep access, otherwise system discovery would break")

    def test_syntax(self):
        self.assert_java_syntax(self.NSD)


class TestConnectivityUtil(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0017-lenos-connectivity-util.patch"]

    UTIL = "core/java/android/ext/ConnectivityUtil.java"
    API = "core/api/module-lib-current.txt"

    def test_helper_contract(self):
        self.assert_contains(
            self.UTIL,
            "package android.ext;",
            "@SystemApi(client = SystemApi.Client.MODULE_LIBRARIES)",
            "Settings.Secure.ALWAYS_ON_VPN_LOCKDOWN",
            "return lockdownVpnEnabled == 1 && !isSystem(context, uid);",
            "ApplicationInfo appInfo = pm.getApplicationInfoAsUser(packageName, 0, userId);",
            "appInfo.isSystemApp()")

    def test_module_lib_api_declared(self):
        self.assert_contains(
            self.API,
            "package android.ext {",
            "public class ConnectivityUtil {",
            "isRegularAppWithLockdownVpnEnabled(@NonNull android.content.Context, int);",
            "isSystem(@NonNull android.content.Context, int);")

    def test_syntax(self):
        self.assert_java_syntax(self.UTIL)


class TestAlwaysOnVpnSurvival(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0018-lenos-vpn-always-on-survival.patch"]

    VPN = "services/core/java/com/android/server/connectivity/Vpn.java"

    def test_unsupported_package_keeps_the_setting(self):
        self.assert_contains(
            self.VPN,
            "isAlwaysOnPackageSupported returned false for ",
            "return false;")
        body = self.text(self.VPN)
        # The stock auto-unset must be gone from startAlwaysOnVpn().
        start = body.index("public boolean startAlwaysOnVpn()")
        next_method = body.find("\n    public ", start + 10)
        region = body[start:next_method if next_method != -1 else len(body)]
        self.assertNotIn("setAlwaysOnPackage(null, false, null)", region)

    def test_syntax(self):
        self.assert_java_syntax(self.VPN)


if __name__ == "__main__":
    unittest.main()
