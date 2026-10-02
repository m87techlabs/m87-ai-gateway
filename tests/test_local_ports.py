import pytest

from m87_gateway.local_server import DEFAULT_GATEWAY_PORT, bind_listener


def test_official_gateway_port():
    assert DEFAULT_GATEWAY_PORT == 8087


def test_fallback_skips_busy_ports_and_keeps_listener_reserved():
    with bind_listener("127.0.0.1", 0) as first:
        start = first.getsockname()[1]
        if start > 65335:
            pytest.skip("Ephemeral port too high for two fallback steps")
        try:
            second = bind_listener("127.0.0.1", start + 100)
        except OSError:
            pytest.skip("Test fallback port is occupied")
        with second, bind_listener("127.0.0.1", start, fallback_step=100) as selected:
            assert selected.getsockname()[1] == start + 200
            with pytest.raises(OSError):
                bind_listener("127.0.0.1", start + 200)


def test_exact_port_collision_does_not_fall_back():
    with bind_listener("127.0.0.1", 0) as occupied:
        with pytest.raises(OSError):
            bind_listener("127.0.0.1", occupied.getsockname()[1])


def test_fallback_exhaustion_closes_sockets():
    with bind_listener("127.0.0.1", 0) as occupied:
        with pytest.raises(OSError, match="No available port"):
            bind_listener("127.0.0.1", occupied.getsockname()[1], fallback_step=65536)
