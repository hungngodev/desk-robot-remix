# Desk Robot Remix

Build one expressive desk pet, then make four more with the same hardware and
different personalities and removable costumes. Each robot uses a camera, an
OLED face, speech, tracks and a lifting claw. A shared Mac handles the AI.

## Start here

**Before any permanent build:** Read the [complete day-zero blueprint](blueprint/README.md), the [forward-only build sequence](blueprint/linear-build.md), and the [prebuild contradictions](blueprint/decisions-before-hardware.md). Those include **all required proactive voice/vision/peer behaviors** and the original sensor/game research from day one; the seven stages below are the physical integration shorthand, not a reduction of the target.

| I want to… | Open |
| --- | --- |
| See the build order and what is ready | [Project plan](PLAN.md) and [full linear sequence](blueprint/linear-build.md) |
| Find every requested idea and link | [200 feature entries](blueprint/feature-register.md) and [131 original HTML URLs](blueprint/original-html-link-index.md) |
| Check the hard behavior and proactive requirements | [System contract](blueprint/system-contract.md) and [acceptance A1–A12](blueprint/acceptance.md) |
| Check what I own and what I still need | [Parts and shopping list](hardware/parts.md) |
| Start the first physical check | [Gripper fit and bench guide](guides/first-gripper-test.md) |

**Next step.** First settle the day-zero architecture, part variant, final fit and full delivered cost gates, then check one MG90S servo in the saved gripper before printing the whole robot. Keep robot motion disabled during fit work.

**Current status.** The head and body firmware compile, and the fleet demo
runs with simulated inputs. Robot one still needs assembly, working floor
sensors and physical tests. The prototype cap is **$50 delivered**, including
money already spent. A complete delivered quote is still open.

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
