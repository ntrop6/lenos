"""GrapheneOS: no DHCP state reuse under per-connection MAC randomization (#14).

The Wi-Fi privacy port (`wifi/0001`) makes per-connection randomized MACs the
default, but AOSP's DHCP client still renews the lease it cached in
``IpMemoryStore`` for the same L2 network (``DhcpClient``'s
``EVENT_CONFIGURATION_OBTAINED`` → ``INIT-REBOOT`` path). The DHCP server then
sees the same requested address from a "new" device and can link the two
connections — which defeats the point of the fresh MAC.

GrapheneOS fixed this in 2021 ("prevent DHCP (IPv4) from reusing state across
connections to the same network when full MAC randomization is enabled") and
still ships the patch on branch 17, so LineageOS 24.0 (which lacks it) gets the
port here:

* when the lease from the memory store has not expired, the client checks the
  connected network's MAC randomization mode; for per-connection randomization
  (``RANDOMIZATION_ALWAYS``) it starts from DISCOVER instead of renewing;
* the check runs inside the NetworkStack process, which holds
  ``NETWORK_STACK`` — the Wi-Fi service grants that a scan-results/location
  bypass, so the configured-network lookup works without location permission;
* any failure (WifiManager missing, lookup denied, network not in the list)
  conservatively avoids reuse, which is privacy-safe but costs an extra DHCP
  exchange, never correctness.

Other randomization modes (device MAC, per-network persistent) keep the
upstream fast-renewal path unchanged.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestDhcpStateReuse(LenosPatchTest):
    PROJECT = "packages/modules/NetworkStack"
    PATCHES = ["0001-lenos-dhcp-no-state-reuse.patch"]

    DHCP = "src/android/net/dhcp/DhcpClient.java"

    def test_lease_expiry_check_also_avoids_reuse(self):
        self.assert_contains(
            self.DHCP,
            "if (currentTime >= attributes.assignedV4AddressExpiry "
            "|| shouldAvoidStateReuse()) {",
            "// Lease has expired.",
            "transitionTo(mDhcpInitState);")

    def test_randomization_always_constant(self):
        self.assert_contains(
            self.DHCP, "private static final int RANDOMIZATION_ALWAYS = 100;")

    def test_queries_the_connected_networks_mode(self):
        self.assert_contains(
            self.DHCP,
            "wifiInfo.getNetworkId()",
            "wifiManager.getConfiguredNetworks()",
            "configuration.macRandomizationSetting == RANDOMIZATION_ALWAYS")

    def test_failure_falls_back_to_avoiding_reuse(self):
        # The catch-all must end in `return true` (avoid reuse), otherwise a
        # denied lookup would silently restore the leak.
        self.assert_contains(
            self.DHCP,
            "} catch (Exception e) {",
            'loge("ConfiguredNetworks should contain Connected network id config");',
            "return true;")

    def test_wifi_imports_present(self):
        self.assert_contains(
            self.DHCP,
            "import android.net.wifi.WifiConfiguration;",
            "import android.net.wifi.WifiInfo;",
            "import android.net.wifi.WifiManager;",
            "import java.util.ArrayList;")

    def test_upstream_lease_handling_kept(self):
        # The upstream store/renew path must still exist: this patch only adds
        # a condition, it does not replace the lease bookkeeping.
        self.assert_contains(
            self.DHCP,
            "mIpMemoryStore.retrieveNetworkAttributes(mConfiguration.l2Key, listener);",
            "transitionTo(mDhcpInitRebootState);",
            "mLastAssignedIpv4Address = attributes.assignedV4Address;")

    def test_balanced(self):
        self.assert_balanced(self.DHCP)


if __name__ == "__main__":
    unittest.main()
