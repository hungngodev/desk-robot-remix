from pathlib import Path


def test_bridge_reclaims_idle_http_sessions():
    source = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    config = source.split("httpd_config_t config = HTTPD_DEFAULT_CONFIG();", 1)[1]
    config = config.split("httpd_start(&server_, &config)", 1)[0]
    assert "config.lru_purge_enable = true;" in config
    assert "config.recv_wait_timeout = 2;" in config
    assert "config.send_wait_timeout = 2;" in config


def test_malformed_json_closes_only_its_http_session():
    source = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    handle = source.split("esp_err_t Bridge::Handle(httpd_req_t* req)", 1)[1]
    reject = handle.split("const auto reject =", 1)[1].split("};", 1)[0]
    assert 'httpd_resp_set_hdr(req, "Connection", "close");' in reject
    assert "return ESP_FAIL;" in reject
    assert 'return reject(400, "embedded null");' in handle
    assert 'return reject(400, "expected one event or command field");' in handle
    assert 'return reject(400, "command must be a string");' in handle
