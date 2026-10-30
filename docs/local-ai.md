# Local AI setup

The coordinator and simulator are installed/tested. Ollama is installed on this
M1 Max/64 GB Mac, but **no LLM, speech or vision weights were downloaded**, and
the full AI server has not been launched. The steps below use existing projects
and keep their larger dependencies isolated. No paid API is required.

## Conversation stack

1. Start Ollama and run `ollama pull qwen3:8b`. Confirm with `ollama list`.
   [Ollama Qwen3](https://ollama.com/library/qwen3).
2. Run an existing [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) CPU
   installation on localhost:8880, following its current macOS/native or Docker
   instructions. Its endpoint must return WAV from `/v1/audio/speech` and support
   `af_heart` and `am_adam`. Native setup on this Mac has not been verified; do not
   assume a CUDA container works on Apple Silicon.
3. The server overlay is prepared at `laptop/server/build/xiaozhi`. To create it
   from scratch, run:

```sh
python3 laptop/server/install_overlay.py --upstream upstream/xiaozhi-esp32-server --output laptop/server/build/xiaozhi
uv venv .tools/speech-env --python 3.11
uv pip install --python .tools/speech-env/bin/python -r laptop/server/build/xiaozhi/main/xiaozhi-server/requirements.txt
```

The pinned upstream asks for torch 2.2.2/numpy 1.26.4. Do not mix these with the
coordinator's environment. Installation has not been run here; report dependency
errors explicitly before changing pins. Upstream also requires FFmpeg and Opus
libraries. Follow its [deployment guide](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/docs/Deployment.md)
for macOS dependencies and SenseVoiceSmall `model.pt` placement. Existing model
configuration/tokenizer files are present; model weights are not.

4. Run `uv run python laptop/server/configure.py --server-ip MAC_LAN_IP`, replacing
   the address with the Mac's reachable LAN IPv4. It writes private
   `data/.config.yaml` once with a generated authentication secret and the local
   FunASR/SenseVoice, Ollama and Kokoro providers. Credential values are hidden.
   The ignored file is never overwritten. Follow the pinned server's authentication
   and OTA guide when connecting the head.
5. Copy `config/robots.example.toml` to `config/local.toml`. Enter the real head
   IP and its Xiaozhi `device-id` from its boot/server connection. Keep movement
   disabled until stand tests and measured calibration pass.
6. Generate `config/local.env` once with `uv run desk-robot secrets`. Head token
   values must match each head's private firmware build. The operator and model
   tool tokens are distinct. Do not paste credentials into committed config.

Start the speech server with its own Python:

```sh
.tools/speech-env/bin/python laptop/server/run_server.py --config config/local.toml
```

The wrapper loads local credentials and maps robot IDs to actual Xiaozhi device
IDs. The adapter binds its private speech control to 127.0.0.1:8766. Xiaozhi's
device WebSocket/OTA services need to be reachable on the trusted LAN. Keep these
services off the public Internet.

## Vision and coordinator

Install the optional detector in the coordinator environment:

```sh
uv sync --extra dev --extra vision
```

Download the official `yolov8s-worldv2.pt` weights through
[Ultralytics YOLO-World instructions](https://docs.ultralytics.com/models/yolo-world/)
and place them in `models/` (or set `vision_weights` to a different local file).
The code deliberately requires a real local file; it does not silently download
one during a movement job. Review the model/code licensing before redistributing
or commercializing the project. No physical detection accuracy is established.

Start the coordinator:

```sh
uv run desk-robot --config config/local.toml serve
```

Local API documentation is at localhost:8765/docs. Use the operator token for
manual enable/move, the separate tool token for the Xiaozhi pickup/stop/job
functions. Tools cannot enable movement themselves. Ordinary head camera
explanations remain upstream functionality; the separate detector supplies
experimental pickup geometry.

The server adapter uses existing WAV-to-Opus conversion and head playback. It
reports successful **transmission**, not proof that sound physically played.
During a bounded two-to-five-robot conversation it suppresses microphone/listen input,
routes transcripts digitally and allows one speaker at a time. The mute lease
expires after 305 seconds if the coordinator disappears. Normal speech resumes
when the session exits. Device-specific physical audio and echo tests remain.
