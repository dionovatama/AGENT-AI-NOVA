"""
Test parser murni untuk linux.network_info dan linux.process_status.

Tidak memerlukan koneksi SSH/VM — fungsi parsing dipisah dari executor
sehingga bisa diuji langsung dengan data contoh (termasuk output asli
dari VM lab Tuan).
"""

from app.tools.linux import _is_self_measurement, _parse_interfaces


class TestParseInterfaces:
    def test_parses_tuans_actual_vm_output(self):
        """Data ini persis dari output 'ip addr' VM lab Tuan (VM-TEST)."""
        raw = (
            "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000\n"
            "    inet 127.0.0.1/8 scope host lo\n"
            "       valid_lft forever preferred_lft forever\n"
            "2: enp0s3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000\n"
            "    inet 10.0.2.15/24 brd 10.0.2.255 scope global dynamic enp0s3\n"
            "       valid_lft 86390sec preferred_lft 86390sec\n"
            "3: enp0s8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000\n"
            "    inet 192.168.1.10/24 brd 192.168.1.255 scope global dynamic enp0s8\n"
            "       valid_lft 86395sec preferred_lft 86395sec\n"
        )

        result = _parse_interfaces(raw)

        assert len(result) == 3
        assert result[0].name == "lo"
        assert result[0].ip == "127.0.0.1/8"
        assert result[0].state == "UNKNOWN"

        assert result[1].name == "enp0s3"
        assert result[1].ip == "10.0.2.15/24"
        assert result[1].state == "UP"

        assert result[2].name == "enp0s8"
        assert result[2].ip == "192.168.1.10/24"
        assert result[2].state == "UP"

    def test_interface_down_without_ip_still_captured(self):
        """Interface yang DOWN dan belum dapat IP (seperti enp0s8 sebelum diaktifkan)."""
        raw = (
            "3: enp0s8: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN group default qlen 1000\n"
        )

        result = _parse_interfaces(raw)

        assert len(result) == 1
        assert result[0].name == "enp0s8"
        assert result[0].ip is None
        assert result[0].state == "DOWN"

    def test_empty_input_returns_empty_list(self):
        assert _parse_interfaces("") == []

    def test_interface_name_with_at_suffix_preserved(self):
        """Interface virtual seperti veth pair: 'eth0@if5'."""
        raw = "4: eth0@if5: <BROADCAST,MULTICAST,UP> mtu 1500 state UP\n    inet 172.17.0.2/16 scope global eth0\n"

        result = _parse_interfaces(raw)

        assert result[0].name == "eth0@if5"
        assert result[0].ip == "172.17.0.2/16"


class TestProcessSelfMeasurementFilter:
    def test_detects_ps_aux_command_variants(self):
        assert _is_self_measurement("ps aux --sort=-%cpu") is True
        assert _is_self_measurement("PS AUX --sort=-%cpu") is True  # case-insensitive
        assert _is_self_measurement("/bin/ps aux") is True

    def test_normal_commands_not_flagged(self):
        assert _is_self_measurement("/usr/sbin/sshd -D") is False
        assert _is_self_measurement("postgres: checkpointer") is False
        assert _is_self_measurement("python3 -m uvicorn app.main:app") is False
