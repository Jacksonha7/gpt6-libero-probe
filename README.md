# Where Does a General Multimodal Model Break Down in Robot Manipulation?

**English** | [中文](README_zh.md)

A reproducible probe on the LIBERO simulator that separates what a general-purpose multimodal model can and cannot do when it controls a robot arm. The model under study is GPT-6 (`gpt-6-astra`, called through the Codex CLI); the harness works with any model that takes images and returns structured text.

📄 [Full report](docs/report.md) · 🎬 [All video cases](docs/cases.md) · 🛠 [Reproduce](code/README.md) · 📊 [Raw success counts](results/success_rates.csv)

## Research question

When a multimodal model controls a robot arm, which step limits it: deciding what to do, locating things in space, or producing the motor commands?

## Key results

Four pick-and-place tasks, 10 episodes each. In every row the model outputs 7-D end-effector delta actions, which go straight to the simulator's end-effector controller, bypassing any hand-written grasp/place routine. It always sees the main camera, the wrist camera and the end-effector position.

| What else the model is given | Success |
|---|:-:|
| Ground-truth object coordinates | **37/40** |
| Nothing else | **2/40** |
| One side-view camera image | **34/40** |
| Nothing else, but high reasoning effort (4 episodes per task) | 3/16 |

## Findings

**1. When object positions are known, can it complete the task?**
For pick-and-place and pressing, yes: given ground-truth object coordinates, it plans the grasp and produces workable actions on 7 of the 10 libero_goal tasks. It still fails at opening drawers and is unreliable at pushing.

**2. When object coordinates are removed, where does it fail?**
At depth along the main camera's line of sight. With the main and wrist cameras, the gripper closes on average 7.2 cm from the object on the camera side, while the average left-right offset stays under 1 cm. Letting a depth map convert its pixel choices into 3D recovers most tasks; asking it to state metric coordinates recovers none.

**3. What does adding a camera view fix, and what does it not?**
A side view perpendicular to the main camera removes most of the depth error, which a higher reasoning effort does not. It does not fix drawers, pushing, very small targets, or the habit of declaring success when a placement is 3–4 cm off.

## One case

Same scene, same model, no object coordinates. Left: main + wrist camera; the gripper closes on empty space in front of the bowl. Right: plus one side-view image; it grasps the rim and places the bowl on the stove.

<img src="assets/gifs/video09.gif" width="720">

## Capability boundaries (within the tested tasks)

| Ability | Observed | Evidence |
|---|---|---|
| Choosing grasp part and placement from known coordinates | Reliable on 4 pick-place tasks | 40/40 |
| Delta-action control toward known targets (approach, grasp, carry, place, press) | Reliable | 37/40 on 4 tasks; 29/30 on 3 more |
| Pointing at objects in the image | Reliable, except when the image center of an opening differs from its 3D center | 30/40; 1/10 on the bowl-center task |
| Depth with the main + wrist cameras | Fails; biased toward the main camera | 2/40, 7.2 cm error |
| Depth with an added orthogonal side view | Mostly works | 34/40, 1.6 cm error |
| Stating metric 3D coordinates from images | Fails | 0/40 |
| Approaching from the side (drawer handles) | Fails, with or without coordinates | 0/20, 0/18 |
| Non-prehensile pushing | Unreliable | 5/10 with coordinates |
| Anticipating implicit geometry (object offset when held by its rim) | Not without a hint; matters only for tight tolerances | 9/10 → 2/10 |

Scope: LIBERO simulation, 10 libero_goal tasks, 10 episodes per condition per task, lowest reasoning effort unless stated, one camera layout, one model. See [limitations](docs/report.md#limitations).

## Reproduce

```bash
cd code
export LIBERO_ROOT=/path/to/LIBERO PY=/path/to/venv/bin/python
source env.sh
bash run_condition.sh oracle 8 2               # checks the primitive controller, no model calls
bash run_condition.sh act_vision_side 1 10     # condition, task id, episodes
$PY analyze.py act_vision_side
```

Needs a GPU node for MuJoCo EGL rendering and a logged-in Codex CLI. [`code/conditions.tsv`](code/conditions.tsv) lists every condition, its arguments and the success counts reported here; see [`code/README.md`](code/README.md) for which configurations are historical and which are reconstructed.

## Related work

Galbot's *GPT 6 Astra as an Embodied Policy* reports 49/50 zero-shot on RoboLab pick-and-place with head and dual-wrist cameras. Our main + wrist result (2/40) and side-view result (34/40) suggest camera layout is the main reason for the gap; see the [comparison](docs/report.md#comparison-with-related-work).
