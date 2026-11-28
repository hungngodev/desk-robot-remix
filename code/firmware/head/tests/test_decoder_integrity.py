"""Native fault injection for the shared generated Opus decoder setter."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
UPSTREAM = HEAD.parents[1] / "upstream/xiaozhi-esp32/main/audio/audio_service.cc"


@pytest.mark.skipif(not UPSTREAM.is_file(), reason="Pinned upstream fixture unavailable")
def test_generated_decoder_recovers_without_destroying_active_decoder(tmp_path):
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++ compiler required"
    spec = importlib.util.spec_from_file_location("decoder_overlay", HEAD / "install_overlay.py")
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    source = overlay.patch_decoder_integrity(UPSTREAM.read_text())
    setter = "void AudioService::SetDecodeSampleRate(" + source.split(
        "void AudioService::SetDecodeSampleRate(", 1
    )[1].split("void AudioService::PushTaskToEncodeQueue(", 1)[0]
    harness = r"""
#include <cassert>
#include <mutex>
template <typename... Args> void Log(Args&&...) {}
#define ESP_LOGE(tag, ...) Log(__VA_ARGS__)
#define ESP_LOGI(tag, ...) Log(__VA_ARGS__)
#define ESP_AUDIO_MONO 1
struct esp_opus_dec_cfg_t { int rate; int duration; };
struct esp_ae_rate_cvt_cfg_t { int input; int output; };
#define OPUS_DEC_CFG(rate, duration) esp_opus_dec_cfg_t{rate, duration}
#define RATE_CVT_CFG(input, output, channels) esp_ae_rate_cvt_cfg_t{input, output}
int opens = 0, closes = 0, converter_opens = 0;
bool fail_open = false, fail_converter = false;
int first = 1, second = 2, converter = 3;
int esp_opus_dec_open(esp_opus_dec_cfg_t*, unsigned long, void** out) {
    ++opens;
    *out = fail_open ? nullptr : &second;
    return fail_open ? -1 : 0;
}
void esp_opus_dec_close(void*) { ++closes; }
int esp_ae_rate_cvt_open(esp_ae_rate_cvt_cfg_t*, void** out) {
    ++converter_opens;
    *out = fail_converter ? nullptr : &converter;
    return fail_converter ? -1 : 0;
}
void esp_ae_rate_cvt_close(void*) {}
struct Codec { int output_sample_rate() { return 24000; } };
struct Board {
    static Board& GetInstance() { static Board b; return b; }
    Codec* GetAudioCodec() { static Codec c; return &c; }
};
struct AudioService {
    void* opus_decoder_ = &first;
    void* output_resampler_ = nullptr;
    int decoder_sample_rate_ = 24000;
    int decoder_duration_ms_ = 60;
    int decoder_frame_size_ = 1440;
    std::mutex decoder_mutex_;
    void SetDecodeSampleRate(int, int);
};
"""
    main = r"""
int main() {
    AudioService s;
    s.SetDecodeSampleRate(32000, 60);
    s.SetDecodeSampleRate(24000, 30);
    assert(opens == 0 && closes == 0 && s.opus_decoder_ == &first);
    fail_open = true;
    s.SetDecodeSampleRate(16000, 60);
    assert(opens == 1 && closes == 0 && s.opus_decoder_ == &first);
    assert(s.decoder_sample_rate_ == 24000);
    fail_open = false;
    fail_converter = true;
    s.SetDecodeSampleRate(16000, 60);
    assert(opens == 2 && closes == 1 && s.opus_decoder_ == &second);
    assert(s.decoder_sample_rate_ == 16000 && !s.output_resampler_);
    fail_converter = false;
    s.SetDecodeSampleRate(16000, 60);
    assert(opens == 2 && converter_opens == 2 && s.output_resampler_ == &converter);
}
"""
    probe = tmp_path / "decoder_integrity.cc"
    executable = tmp_path / "decoder_integrity"
    probe.write_text(harness + setter + main)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(probe), "-o", str(executable)],
        check=True,
    )
    subprocess.run([str(executable)], check=True)
