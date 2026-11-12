# Terminal IR backlog freshness: IDF 4.4 reuse decision (2026 11 12)

## Finding and scope
Independent QA on PR #17 notes that TerminalIr::poll() stamps decoded NEC frames at dequeue time. With a limited number of ringbuffer packets processed per receiver each poll, an old frame may acquire a fresh timestamp. A second receiver may then appear to agree with it. This is a source-level risk, not a reproduced physical failure. The dock's motion, contact and charge interlocks remain mandatory and independent.

## Verified upstream interface
ESP-IDF 4.4.3 ESP32 RMT documentation describes legacy RX via rmt_driver_install, rmt_get_ringbuf_handle, rmt_rx_start and FreeRTOS ringbuffer receives. The API exposes pulse items and their durations, not an arrival timestamp per queued frame. Therefore applying esp_timer_get_time or millis when calling xRingbufferReceive only records processing time, not reception time. Source: https://docs.espressif.com/projects/esp-idf/en/v4.4.3/esp32/api-reference/peripherals/rmt.html

The current ESP-IDF 5 RMT callback example uses rmt_rx_register_event_callbacks and is **not** directly compatible with the pinned 4.4 legacy driver: https://github.com/espressif/esp-idf/blob/master/docs/en/api-reference/peripherals/rmt.rst

Keep the existing IDF 4.4 driver and NEC parser. No new dependency, transplanted code or license obligation is proposed by this note. The upstream API documentation is a reference, not imported source.

## Smallest safe implementation to evaluate
1. Maintain separate left and right receiver state, including a monotonic last-valid-evidence timestamp, last poll time, and a bounded backlog/fault counter. Never treat NEC repeat-only symbols as new directional evidence.
2. Drain each receiver to empty with a strict finite packet budget, returning every ringbuffer item. **If the budget is exhausted while more packets remain, invalidate that receiver's directional evidence** and report backlog. Do not stamp and accept packets from a known backlog.
3. Merely draining a queue to empty does **not** establish physical arrival time for its final item. For a strong guarantee, require a bounded continuous receiver service interval, or attach a monotonic timestamp at actual RX completion using an IDF 4.4 compatible capture/ISR mechanism verified against the installed driver. Do not pretend legacy RMT ringbuffer metadata includes timestamps.
4. Until the timing guarantee is established, reject dual-receiver agreement after a poll stall longer than the freshness budget, after a ringbuffer overflow, or when either receiver has an unbounded or ambiguous backlog. Require fresh independent observations in a subsequent qualified interval.
5. Keep all docking safety interlocks and fail closed. Do not allow IR evidence alone to authorize motion or charging. Avoid using wall clock time; handle monotonic tick rollover explicitly.

## Regression contract
Use a host-injected clock and fake left/right packet queues. Verify: (a) old left packets accumulated during a poll stall never become fresh on dequeue; (b) a burst exceeding the packet budget invalidates only its receiver; (c) a new qualified pair recovers without recycling stale frames; (d) repeats, corruption and one-sided activity never satisfy agreement; (e) 32-bit timer wrap is handled; (f) all fake queue items are returned even on errors. Run native C++ tests and firmware compilation before calling it verified. A deterministic test should demonstrate the original failure first.

## November 12 source implementation after independent review

The narrow queue-age guard has now been added to **the same PR #17**, not a new IR subsystem or port to IDF 5. The legacy RMT source and existing NEC decoder remain authoritative.

* `NecBurst.h` contains a small portable `IrFrameQueueGate` for the exact IDF 4.4 limitation: establish an initial empty-queue baseline, require subsequent polls within 100 ms (32-bit wrap safe), accept at most two packets per side, and quarantine a receiver until its overflow backlog has been fully drained.
* `TerminalIr.cpp` consumes and returns at most eight RMT packets per receiver per poll, discards candidates from **both** sides if either side is late, over budget, or has an ambiguous batch, and never relabels a drained old packet as fresh. Only after both sides have a qualified time window and empty queues are their last valid classic NEC frames accepted in the existing `DualIrEvidence` cache. Receiver reinitialization clears the polling baseline.
* Portable tests in `terminal_ir_tests.cpp` now cover initial-drain, normal poll intervals, long stalls, more than two packets, exhausted budget and continued drain, invalid side, and 32-bit wrap, in addition to the existing decoder checks. The literal RMT packet queue behavior and GPIO36/39 electrical timing must still be tested with fake IDF receives and then with two actual 38 kHz demodulators.

**Verification classification:** source committed and local state-machine reasoning reviewed. GitHub Actions at head `646b2b6` still showed four jobs failing before any steps, so these new C++ test definitions are **not** a recorded passing repo test or firmware compile. No terminal docking motion or charging authorization was added; `IrPairEvidence` keeps both false.

**Limit of the guarantee:** IDF 4.4 ringbuffers still do not carry RX timestamps. The guard only bounds residence time by continuously draining the queue and by the declared maximum poll interval; it does not recover exact optical arrival time or account for an unmeasured hardware receiver's propagation delay. If WROOM sensor polling routinely exceeds 100 ms under loaded conditions, evidence stays invalid and needs timing measurement or a supported hardware callback redesign, never a relaxed guess.

## Coordination and next step
Related: docs/research/2026-11-12-terminal-ir-idf44-reuse-review.md, docs/hardware/full-feature-wiring-and-shopping.md, docs/reviews/PARALLEL_CHAT_HANDOFF.md, and PR #17's QA backlog freshness finding. Implement one isolated failing host regression for stale dequeue timestamps first. Coordinate ownership with the existing implementation loop before editing the receiver; avoid another PR.

Production guard and host regression definitions were committed after the original research pass. Native tests, firmware compilation, and physical hardware measurements still have not been recorded as passing in this research pass. Physical dual IR bearing, receiver polarity, ambient light, docking and protected charging remain unverified.
