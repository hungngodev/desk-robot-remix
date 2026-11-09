# Desk Robot Remix: day zero full feature blueprint

**Status: proposed design contract, not a verified assembled robot.**
Reviewed 2026-11-09 against the user supplied 23-section `ESP32 Deskpet Ideas.html`, its 2026-11-09 engineering report, the 56 Markdown files in the original repository, the existing audit branch, published reuse sources and current software. This is the **entry point for the complete project**, including the research-era feature library, without silently dropping ideas.

## How this blueprint changes the approach

The aim is **one linear integration path to the final desired robot**. Do not first build a different cheap robot, replace the controller, remove its gripper, swap its audio platform or redesign the chassis halfway through to add an essential behavior. Lock the final hardware allocation, mounting envelopes, expansion points, source choices, safety boundary and acceptance tests *before printing and shopping*. Then build and prove the selected subsystems in dependency order. Tests and temporary stand fixtures are not alternative robots or backward steps.

**Important engineering limitation:** no amount of up-front analysis guarantees zero fit revisions. The source case is explicitly unprinted, real sensor/supply variants are not confirmed, and the delivered `$50` cap conflicts with several proposed purchases. Resolve those unknowns with reversible coupons/bench setups before any irreversible assembly. A requirement is never quietly downgraded to make a budget or demo pass.

Read in this order:

1. [Complete target and non-negotiable behaviors](system-contract.md): who owns speech, observations, autonomous action, safety and power, with actual hardware pin maps.
2. [Forward-only build sequence](linear-build.md): every task and gate from inventory to five peers; full-feature interfaces exist at the start, not retrofitted.
3. [Feature, sensor and research traceability](feature-register.md): includes the HTML's live sections 1–16, historical sections 17–23, experimental waves, unusual sensors, games, peripherals and software-only pet ideas. No idea disappears because it is not in the first purchase basket.
4. [Open source reuse decision register](reuse-register.md): exact repositories, representative files and licenses, plus a copy/port/compare/reject rule. The existing [source map](../source-map.md), [twelve video audit](../research/2026-11-03-video-audit.md), [guide audit](../research/2026-11-03-guide-audit.md), [active behavior research](../research/2026-11-03-active-pet-sources.md) and [Sense/RIO source inspection](../research/2026-11-03-sense-realtime-reuse.md) remain authoritative evidence.
5. [Acceptance and evidence ledger](acceptance.md): includes canonical A1–A12, full user experience cases, future feature verification and reasons a green CI job cannot certify a desk-safe robot.
6. [HTML quantitative proposals](html-quantitative-proposals.md): preserve exact numerical/tuning suggestions from live sections 8–15, clearly distinguish candidate values from real measured or mandatory A1–A12 thresholds.
7. [Concrete repository file implementation plan](implementation-file-plan.md): existing modules to retain, new adapters to add, exact test cases and upstream seam for each capability.
8. [Prebuild decisions and conflicts](decisions-before-hardware.md): decisions that must be settled once, early, instead of forcing a rebuild later.

## Preserve the sources, including contradictory historical ideas

The HTML has a **live plan in sections 1–16** and a **research archive in sections 17–23**. Old Xiaozhi mod packs, older pin maps, early two-sensor cliff concepts, former battery and motor choices, previous budget estimates and the interactive sensor-to-emotion simulator are **research**, not safe construction instructions. The new plan maps the ideas forward but does not reauthorize outdated wiring or unsafe reversal. The original 1.1 MB HTML remains the source artifact: the repo did not contain its bytes when this documentation was authored. Do not claim an exhaustively verified web link corpus, assembled CAD or physical tests from this text.

Source priority when instructions disagree:

1. **User-confirmed end experience:** complete proactive, visually grounded, interruptible, local-first five-robot companions; safe pickup of real keys and wrapped candy; source-first reuse; full set of considered sensor/feature ideas.
2. **Safety, electrical and licensing reality:** manufacturer documentation, actual pin use and fault policies; no unsafe direct copy from a tutorial.
3. [Canonical product brief](../product-definition.md) and [decision log](../decision-log.md) for accepted goals. This blueprint expands coverage and requires explicit reconciliation where changed choices are proposed.
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

Related review: [prior engineering audit](../research/2026-11-09-html-verification.md) and [GitHub PR #1](https://github.com/hungngodev/desk-robot-remix/pull/1). This branch includes those changes as its base; it is intended as the consolidated review path.
