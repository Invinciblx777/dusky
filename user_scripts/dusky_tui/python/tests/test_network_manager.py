"""Focused network manager tests; no live connections are changed."""

from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from python.engines import network_manager as nm


class NetworkManagerTests(unittest.TestCase):
    def engine(self):
        engine = object.__new__(nm.NetworkManagerEngine)
        engine.rescan_event = threading.Event()
        engine._uplinks_cache = []
        return engine

    def test_uplink_candidates_include_local_only_and_exclude_shared_profiles(self):
        engine = self.engine()
        active = "WiFi:wifi-id:802-11-wireless:wlan0\nUSB:usb-id:802-3-ethernet:usb0\nLocal:local-id:802-3-ethernet:usb1\nAP:ap-id:802-11-wireless:wlan1\nPPP:ppp-id:ppp:ppp0\n"
        properties = {
            "wifi-id": "auto\nno\nauto\nno\n",
            "usb-id": "auto\nno\ndisabled\nno\n",
            "local-id": "auto\nyes\ndisabled\nno\n",
            "ap-id": "shared\nno\ndisabled\nno\n",
            "ppp-id": "auto\nno\ndisabled\nno\n",
        }
        gateways = {"wlan0": "192.0.2.1\n\n", "usb0": "198.51.100.1\n\n",
                    "usb1": "203.0.113.1\n\n", "wlan1": "\n\n", "ppp0": "\n\n"}

        def output(args, timeout=5):
            if args[0] == "ip":
                return '[{"dev":"ppp0"}]' if "-4" in args else '[]'
            if "--active" in args:
                return active
            if "connection" in args:
                return properties[args[-1]]
            return gateways[args[-1]]

        engine._run_cmd = output
        uplinks = engine._active_uplinks()
        self.assertEqual([item["uuid"] for item in uplinks], ["wifi-id", "usb-id", "local-id", "ppp-id"])
        self.assertEqual(uplinks[2]["ipv4_never_default"], "yes")
        self.assertEqual(uplinks[-1]["ipv4_gateway"], "on-link")

    def test_choose_switch_and_restore_original_route_settings(self):
        engine = self.engine()
        settings = {"a": ("-1", "-1", "no", "no"), "b": ("200", "300", "yes", "no")}
        engine._active_uplinks = lambda: [
            {"name": "Ethernet", "uuid": "a", "device": "eth0", "ipv4_method": "auto", "ipv6_method": "disabled", "ipv4_gateway": "192.0.2.1", "ipv6_gateway": ""},
            {"name": "USB", "uuid": "b", "device": "usb0", "ipv4_method": "auto", "ipv6_method": "disabled", "ipv4_gateway": "", "ipv6_gateway": ""},
        ]
        engine._profile_route_settings = lambda uuid: settings[uuid]
        engine._set_profile_route_settings = lambda uuid, value: (settings.__setitem__(uuid, value) or SimpleNamespace(returncode=0, stderr=""))
        engine._reapply_device = lambda device: SimpleNamespace(returncode=0, stderr="")
        engine._active_device_for_uuid = lambda uuid: {"a": "eth0", "b": "usb0"}[uuid]
        engine._default_route = lambda family: "usb0 via 198.51.100.1"

        with tempfile.TemporaryDirectory() as directory, patch.object(nm, "ROUTE_CHOICE_FILE", Path(directory) / "choice.json"):
            self.assertTrue(engine._handle_route_choice("use__a")[0])
            self.assertEqual(settings["a"], ("1", "1", "no", "no"))
            self.assertEqual(settings["b"], ("200", "300", "yes", "yes"))
            self.assertTrue(engine._handle_route_choice("use__b")[0])
            self.assertEqual(settings["a"], ("-1", "-1", "yes", "yes"))
            self.assertEqual(settings["b"], ("1", "1", "no", "no"))
            self.assertTrue(engine._handle_route_choice("automatic")[0])
            self.assertEqual(settings["a"], ("-1", "-1", "no", "no"))
            self.assertEqual(settings["b"], ("200", "300", "yes", "no"))
            self.assertFalse(nm.ROUTE_CHOICE_FILE.exists())

    def test_status_uses_one_default_route_for_profile_ip_and_gateway(self):
        engine = self.engine()
        engine._devices_cache = [
            {"device": "usb0", "connection": "Android USB"},
            {"device": "wlan0", "connection": "Home Wi-Fi"},
        ]

        def output(args, timeout=5):
            if args[:3] == ["ip", "-j", "-4"]:
                return '[{"dev":"usb0","gateway":"192.168.42.129","metric":101},' \
                       '{"dev":"wlan0","gateway":"192.168.29.1","metric":600}]'
            if args[:4] == ["ip", "-o", "-4", "addr"]:
                return "inet 192.168.42.170/24"
            return ""

        engine._run_cmd = output
        status = engine._enrich_network_status(
            {"router_ping_ms": "1", "internet_ping_ms": "1"},
            {"ssid": "Home Wi-Fi", "device": "wlan0"},
        )
        self.assertEqual((status["iface"], status["ssid"], status["ip"], status["gateway"]),
                         ("usb0", "Android USB", "192.168.42.170", "192.168.42.129"))

    def test_failed_route_switch_restores_profile_settings(self):
        engine = self.engine()
        engine._active_uplinks = lambda: [
            {"name": "Phone", "uuid": "phone", "device": "usb0", "ipv4_method": "auto", "ipv6_method": "disabled"},
            {"name": "Wi-Fi", "uuid": "wifi", "device": "wlan0", "ipv4_method": "auto", "ipv6_method": "auto"},
        ]
        settings = {"phone": ("-1", "-1", "yes", "no"), "wifi": ("600", "600", "no", "no")}
        engine._profile_route_settings = lambda uuid: settings[uuid]
        engine._active_device_for_uuid = lambda uuid: {"phone": "usb0", "wifi": "wlan0"}[uuid]
        engine._reapply_device = lambda device: SimpleNamespace(returncode=0, stderr="")

        def set_settings(uuid, value):
            if uuid == "wifi" and value[2:] == ("yes", "yes"):
                return SimpleNamespace(returncode=1, stderr="Rejected")
            settings[uuid] = value
            return SimpleNamespace(returncode=0, stderr="")

        engine._set_profile_route_settings = set_settings
        with tempfile.TemporaryDirectory() as directory, patch.object(nm, "ROUTE_CHOICE_FILE", Path(directory) / "choice.json"):
            result = engine._handle_route_choice("use__phone")
            self.assertFalse(result[0])
            self.assertIn("Rejected", result[1])
            self.assertFalse(nm.ROUTE_CHOICE_FILE.exists())
        self.assertEqual(settings["phone"], ("-1", "-1", "yes", "no"))
        self.assertEqual(settings["wifi"], ("600", "600", "no", "no"))

    def test_hotspot_uses_shared_profile_and_restores_previous_wifi(self):
        engine = self.engine()
        engine._hotspot_ssid = "OfflineLab"
        engine._hotspot_password = "testpass123"
        engine._hotspot_device = "Auto"
        engine._hotspot_devices = lambda: [{"device": "wlan0", "state": "connected", "connection": "Home", "2.4": "yes", "5": "yes"}]
        engine._prepare_hotspot_firewall = lambda device: ""
        engine._run_cmd = lambda args, timeout=5: (
            "enabled\n" if args[-2:] == ["radio", "wifi"] else
            "home-id:wlan0\n" if "--active" in args else "10.42.0.1/24\n"
        )
        profile = {"saved": False, "active": False}
        engine._hotspot_profile = lambda active_only=False: (
            {"uuid": "hotspot-id", "ssid": "OfflineLab", "password": "testpass123", "device": "wlan0"}
            if profile["saved"] and (not active_only or profile["active"]) else None
        )
        remembered = []
        engine._remember_hotspot_previous = lambda device, uuid: remembered.append((device, uuid))
        engine._hotspot_previous = lambda: {"device": "wlan0", "uuid": "home-id"}
        commands = []

        def run(args, **kwargs):
            commands.append(args)
            if args[1:3] == ["connection", "add"]:
                profile["saved"] = True
            elif args[1:3] == ["connection", "up"] and "hotspot-id" in args:
                profile["active"] = True
            elif args[1:3] == ["connection", "down"]:
                profile["active"] = False
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        with patch.object(nm.shutil, "which", return_value="/usr/bin/dnsmasq"), \
             patch.object(nm.subprocess, "run", side_effect=run):
            self.assertTrue(engine._handle_hotspot("start_hotspot_24", "true")[0])
            self.assertTrue(engine._handle_hotspot("stop_hotspot", "true")[0])

        self.assertTrue(any("ipv4.method" in command and "shared" in command for command in commands))
        self.assertIn(["nmcli", "connection", "up", "uuid", "home-id", "ifname", "wlan0"], commands)
        self.assertNotIn(["nmcli", "device", "disconnect", "wlan0"], commands)
        self.assertIn(("wlan0", "home-id"), remembered)

    def test_existing_hotspot_firewall_rules_need_no_polkit(self):
        rules = "\n".join(
            f"-A ufw-user-input -i wlan0 -p {protocol} --dport {port} -j ACCEPT"
            for port, protocol in ((67, "udp"), (53, "udp"), (53, "tcp"))
        )
        with patch.object(nm.shutil, "which", return_value="/usr/bin/ufw"), \
             patch.object(Path, "read_text", return_value=rules), \
             patch.object(nm.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(nm.NetworkManagerEngine._prepare_hotspot_firewall("wlan0"), "")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][:2], ["systemctl", "is-active"])

    def test_missing_hotspot_firewall_rules_use_one_polkit_operation(self):
        def which(name):
            return f"/usr/bin/{name}"

        with patch.object(nm.shutil, "which", side_effect=which), \
             patch.object(Path, "read_text", side_effect=OSError("unavailable")), \
             patch.object(nm.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(nm.NetworkManagerEngine._prepare_hotspot_firewall("wlan0"), "")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/pkexec", "/usr/bin/python3"])


if __name__ == "__main__":
    unittest.main()
