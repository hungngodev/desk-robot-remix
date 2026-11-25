from pathlib import Path


def test_bridge_reclaims_idle_http_sessions():
    source = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    config = source.split("httpd_config_t config = HTTPD_DEFAULT_CONFIG();", 1)[1]
    config = config.split("httpd_start(&server_, &config)", 1)[0]
    assert "config.lru_purge_enable = true;" in config
    assert "config.recv_wait_timeout = 2;" in config
    assert "config.send_wait_timeout = 2;" in config
