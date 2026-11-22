# Desk Robot Remix

Build one expressive desk pet, then make four more with the same hardware and
different personalities and removable costumes. Each robot uses a camera, an
OLED face, speech, tracks and a lifting claw. A shared Mac handles the AI.

## Start here

**Before any permanent build:** Read the [complete day-zero project scope](README.md#full-final-project-contract-and-scope), the [forward-only build sequence](PLAN.md), and the [prebuild contradictions](decision-log.md). Those include **all required proactive voice/vision/peer behaviors** and the original sensor/game research from day one; the seven stages below are the physical integration shorthand, not a reduction of the target.

| I want to… | Open |
| --- | --- |
| See the build order and what is ready | [Project plan](PLAN.md) and [full linear sequence](PLAN.md#complete-linear-build-and-permanent-verification-stages) |
| Continue work across parallel chats or coding agents | [Repository agent instructions](../AGENTS.md) and [cross-chat engineering handoff](reviews/PARALLEL_CHAT_HANDOFF.md) |
| Check the cross-layer wiring and event registry regression contract | [Integration contract tests](../code/tests/test_integration_contracts.py), [live GitHub Actions runs](https://github.com/hungngodev/desk-robot-remix/actions/workflows/host-verification.yml) and [historical November 11 runner incident](reviews/CI_RUNNER_PRESTEP_TRIAGE_2026_11_11.md) |
| Research natural proactive social robot behavior | [Reachy Mini source and proactive interaction papers](reviews/REACHY_MINI_PROACTIVE_REUSE_2026_11_11.md) |
| Check useful features in closed PRs before rewriting them | [Actual closed PR patch reconciliation](reviews/CLOSED_PR_RECONCILIATION.md) |
| Find every requested idea and link | [200 feature entries](source-map.md#original-html-feature-and-sensor-idea-register) and [131 original HTML URLs](source-map.md#complete-original-html-research-link-index) and [original file followup](research/2026-11-10-original-html-link-and-hardware-audit.md) |
| Check the hard behavior and proactive requirements | [System contract](product-definition.md) and [acceptance A1–A12](records/verification.md) |
| See the exact proposed code and firmware changes | [Implementation file map](PLAN.md) and [source reuse decisions](research/2026-11-03-active-pet-sources.md) |
| See actual reused open source implementations and new tests | [November 10 open source integration pass](research/2026-11-10-active-open-source-reuse-pass.md) |
| Check the only current five-pet shopping quantities | [Generated owned and buy lists](hardware/complete-shopping-checklist.md), [generated full fleet CSV](hardware/fleet-components.csv) and [sole physical-gated machine plan](hardware/full-feature-plan.json). The detailed wiring page and old one-pet pages are reference material, not purchase authority |
| Check reported stock and historical prototype quote | [Owned inventory](hardware/fleet-inventory.json) and [historical prototype BOM](hardware/bom.json) |
| Start the first physical check | [Gripper fit and bench guide](guides/first-gripper-test.md) |
| Find current firmware build commands without enabling motion | [Current XIAO Sense and WROOM build guide](guides/build.md) |

**Purchasing safeguard:** `code/scripts/procurement_release.py` now blocks fleet release if any of the 42 selected pet/dock roles or seven shared room station roles is omitted or reduced below the current design minimum, even if the remaining components have receipts. The regression test uses simulated approval data, not measured parts. Cheap generic VL53L0X GY-530 is the selected ranging candidate, not a verified breakout or approval to buy forty sensors. No new Adafruit hardware is authorized.

**Reproducible wiring export:** Run `python3 code/scripts/emit_wiring_manifest.py` from the repo root for the current WROOM, XIAO, motor phase and all sixteen sensor mux-lane connections, verified against the source GPIO symbols. The generated output intentionally refuses to act as a final battery/charger schematic. Its source and tests are [the harness generator](../code/scripts/emit_wiring_manifest.py) and [contract tests](../code/tests/test_assembly_harness.py). Real electrical and mechanical acceptance remains open.

**Next step.** First settle the day-zero architecture, part variant, final fit and full delivered cost gates, then check one MG90S servo in the saved gripper before printing the whole robot. Keep robot motion disabled during fit work.

**Historical source snapshot (November 16, 2026; not live verification).** On that date, integrated sensor, five-pet audio,
vision and autonomous social source work belonged to the single draft
[PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17). The code then
contained four low-cost generic VL53L0X floor channels, one front clearance channel and
three additional read-only directions; MPU6050/BerryIMU options, touch/gesture,
FSR, rotary angle, climate, battery, optical paw and a bounded PN532 toy tag
reader. Physical sensor events could request the existing camera asynchronously,
and an explicitly consented two-pet dialogue used the same one-speaker owner.
See the [full source versus physical sensor matrix](hardware/full-feature-wiring-and-shopping.md#current-sensor-source-and-behavior-closure-matrix),
[actual open-source incorporation audit](ATTRIBUTION.md#what-is-actually-reused-versus-locally-implemented-november-12-audit)
and [multimodal social/camera data path](guides/multimodal-voice-video-orchestration.md#november-12-source-truthful-natural-social-behavior-and-active-camera-triggers).

**Not assembled or certified.** CI must be assessed at the exact PR head,
not by extrapolating an older green run or the historical November 11 runner
incident. Open the [live host verification workflow](https://github.com/hungngodev/desk-robot-remix/actions/workflows/host-verification.yml)
and inspect each job and its tested SHA. The [verification record](records/verification.md)
separates source checks from physical acceptance. A passed host job cannot
qualify live XIAO microphone/Opus interruption, concurrent camera performance,
power and charging protection, dual IR dock behavior, measured lift and grip
force, a fitted printable assembly, or five physical robots. The original
**$50 delivered** first-unit cap has not been demonstrated against a complete,
current, delivered quote. Keep bulk purchases, loaded robot movement and
powered charging on HOLD until their independent physical gates pass.

## Reference

| Topic | Where it lives |
| --- | --- |
| Appearance, behavior and pass criteria | [Product definition](product-definition.md) |
| Electronics and software setup | [Wiring](hardware/wiring.md) · [Firmware build](guides/build.md) · [Mac setup](guides/local-ai.md) |
| Try the software-only demo | [Fleet demo](guides/five-robots.md#software-available-now) |
| Model files and fit studies | [CAD guide](cad/README.md) |
| Decisions, sources and evidence | [Decision log](decision-log.md) · [Source map](source-map.md) · [Test records](records/verification.md) · [Attribution](ATTRIBUTION.md) |

## Where to put updates

Update the plan for build order, the parts list for inventory and shopping,
and the product definition for behavior and pass criteria. Record the reason
for a change in the decision log and link to the page that owns the details.
Older quotes stay in the [hardware archive](hardware/archive/).

The [verification record](records/verification.md) summarizes past checks and
links to the [physical trial sheet](records/physical-trials.csv). Open these
when recording a bench test or reviewing evidence. The automated checks are
with the [implementation](../code/).


---

## Full final project contract and scope

*Integrated from the user-requested full feature documentation review on 2026-11-09. This section is planning and source evidence only unless a measured result is linked.*


**Status: proposed design contract, not a verified assembled robot.**
Reviewed 2026-11-09 against the user supplied 41-section `ESP32 Deskpet Ideas.html`, its 2026-11-09 engineering report, the 56 Markdown files in the original repository, the existing audit branch, published reuse sources and current software. This is the **entry point for the complete project**, including the research-era feature library, without silently dropping ideas.

## How this blueprint changes the approach

The aim is **one linear integration path to the final desired robot**. Do not first build a different cheap robot, replace the controller, remove its gripper, swap its audio platform or redesign the chassis halfway through to add an essential behavior. Lock the final hardware allocation, mounting envelopes, expansion points, source choices, safety boundary and acceptance tests *before printing and shopping*. Then build and prove the selected subsystems in dependency order. Tests and temporary stand fixtures are not alternative robots or backward steps.

**Important engineering limitation:** no amount of up-front analysis guarantees zero fit revisions. The source case is explicitly unprinted, real sensor/supply variants are not confirmed, and the delivered `$50` cap conflicts with several proposed purchases. Resolve those unknowns with reversible coupons/bench setups before any irreversible assembly. A requirement is never quietly downgraded to make a budget or demo pass.

Read in this order:

1. [Complete target and non-negotiable behaviors](product-definition.md): who owns speech, observations, autonomous action, safety and power, with actual hardware pin maps.
2. [Forward-only build sequence](PLAN.md): every task and gate from inventory to five peers; full-feature interfaces exist at the start, not retrofitted.
3. [Feature, sensor and research traceability](source-map.md): includes the HTML's current project and eight detailed engineering topics, the later historical Xiaozhi-era research library, experimental waves, unusual sensors, games, peripherals and software-only pet ideas. No idea disappears because it is not in the first purchase basket.
4. [Open source reuse decision register](research/2026-11-03-active-pet-sources.md): exact repositories, representative files and licenses, plus a copy/port/compare/reject rule. The existing [source map](source-map.md), [twelve video audit](research/2026-11-03-video-audit.md), [guide audit](research/2026-11-03-guide-audit.md), [active behavior research](research/2026-11-03-active-pet-sources.md) and [Sense/RIO source inspection](research/2026-11-03-sense-realtime-reuse.md) remain authoritative evidence.
5. [Acceptance and evidence ledger](records/verification.md): includes canonical A1–A12, full user experience cases, future feature verification and reasons a green CI job cannot certify a desk-safe robot.
6. [HTML quantitative proposals](research/2026-11-03-active-pet-sources.md): preserve exact numerical/tuning suggestions from live sections 8–15, clearly distinguish candidate values from real measured or mandatory A1–A12 thresholds.
7. [Concrete repository file implementation plan](PLAN.md): existing modules to retain, new adapters to add, exact test cases and upstream seam for each capability.
8. [Prebuild decisions and conflicts](decision-log.md): decisions that must be settled once, early, instead of forcing a rebuild later.

## Preserve the sources, including contradictory historical ideas

The actual uploaded HTML has **41 `section` elements, 44 `h2` headings, 316 `h3` headings and 231 expandable `details` blocks**. Its active project overview and detailed Power, Drive, Cliff, Touch, Audio, Head, Mac and Proactive topics precede the historical Xiaozhi-era research library. Old Xiaozhi mod packs, older pin maps, early two-sensor cliff concepts, former battery and motor choices, previous budget estimates and the interactive sensor-to-emotion simulator are **research**, not safe construction instructions. The new plan maps the ideas forward but does not reauthorize outdated wiring or unsafe reversal. The original 1.1 MB HTML remains the source artifact: the repo did not contain its bytes when this documentation was authored. Do not claim an exhaustively verified web link corpus, assembled CAD or physical tests from this text.

Source priority when instructions disagree:

1. **User-confirmed end experience:** complete proactive, visually grounded, interruptible, local-first five-robot companions; safe pickup of real keys and wrapped candy; source-first reuse; full set of considered sensor/feature ideas.
2. **Safety, electrical and licensing reality:** manufacturer documentation, actual pin use and fault policies; no unsafe direct copy from a tutorial.
3. [Canonical product brief](product-definition.md) and [decision log](decision-log.md) for accepted goals. This blueprint expands coverage and requires explicit reconciliation where changed choices are proposed.
4. Reproducible code and physical evidence. A compiling sketch, simulation or video does not establish measured performance.
5. HTML topic-level prescriptions are **candidates** until compatible with 1–4; exact tuning, prices and sensor availability require proof.

## Scope and cost are two different decisions

The target end state and expansion support are designed **at day zero**. A physical core within the existing **$50 delivered** cap, including the reported **$18.87** Sense listing, cannot be declared feasible while the proposed power, sensors, wiring and other module prices remain unknown. Simply adding the HTML's proposed **$34** power and the reported Sense price gives **$52.87** before the sensor and audio basket; adding its **$19.38** core basket yields **$72.25** if all are distinct (overlaps not yet reconciled). Never label a null price as zero or count uncertain inventory as owned. Do not cut a mandatory feature to conceal that conflict. Record a final delivered cart and obtain an explicit cap/scope decision **before** spending.

Experimental ideas whose hardware cannot all coexist on the tiny first robot remain **preserved, interface-budgeted, classified and testable**. They do not become required purchases, verified capabilities or secretly omitted requirements. The expanded sensor platform may require a different funded configuration; do not force all experimental modules onto the original small body.

## Development policy

* **Remix first.** Search working licensed projects, inspect source and demo, pin revisions, reuse a whole subsystem or small file where suitable, and record why a new adapter is unavoidable. Prefer Xiaozhi/RIO for voice, Google camera event patterns, Reachy/Stackchan/Xiaozhi Desk Robot for behavior, SMARS/Bluino/Cozmars for mechanical forms. Preserve original source, copyright and third-party license scope.
* **No throwaway foundational rewrites.** Keep purchased XIAO ESP32S3 Sense as head; owned WROOM as body; local Mac as shared coordinator. Do not add a Pi/Pico/Uno, buy a different controller, or swap the 28BYJ platform merely to enable a later planned feature without an explicit design-change approval.
* **All requirements represented from the first design day.** Reserve event schema, identity, memory, speaker lease, cancel/flush, opt-in vision, operator motion authority, sensor bus and mechanical/service clearances before building one unit. Features enter operation when their tests pass.
* **Safety stays local.** A model never gains motor credentials. No automatic blind reverse on a cliff or stale sensor; hard stop outranks mood, camera, peer requests and LLM outputs.
* **Respect state.** Each requirement, candidate and test is tagged `REQUIRED`, `PLANNED`, `OPTIONAL`, `REFERENCE ONLY`, `REJECTED FOR SAFETY`, `SOURCE CHECKED`, `CODE TESTED` or `PHYSICALLY PASSED`. Those labels cannot be conflated. The original requirements A1–A12 remain in force.
* **No silent supersession.** If later research proves a part incompatible or obsolete, document the exact replacement/interface/price/test before implementation; preserve the older research and reasoning. No automatic fleet procurement.
* **Stop with evidence when blocked.** A failed fit coupon, electrical rating, license conflict, cost cap or measured acceptance gate is an unresolved decision. Do not publish a pretend complete assembly guide.

## Current checkpoint, not future claims

Previous GitHub Actions verification on the audit branch passed 116 Python/head host tests plus four subtests, 23 body C++ tests with sanitizers, lint and both WROOM firmware profiles. Actual Sense audio AEC, full live Mac vision/voice integration, pet scheduler, per-robot persistent memory, real cliff sampling, charged power, pickup and assembled fleet remain **not physically verified**. The new plan changes **requirements and documentation**, not motor behavior or fabricated test records.

Related review: [prior engineering audit](research/2026-11-09-html-verification.md) and [GitHub PR #1](https://github.com/hungngodev/desk-robot-remix/pull/1). This branch includes those changes as its base; it is intended as the consolidated review path.
