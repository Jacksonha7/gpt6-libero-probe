# Probing GPT-6's Robot Manipulation Abilities (LIBERO)

**English** | [中文](README_zh.md)

GPT-6 can operate a robot arm in simulation. This project breaks "manipulation" into separate abilities and measures each one on its own to find where the bottleneck is.

**Finding**: planning is fine and control is fine. The bottleneck is **judging depth from a single oblique camera**. When given object coordinates, GPT-6 outputs raw motor actions directly and succeeds in 37 of 40 episodes. With only the main camera image it succeeds 2 times, and the gripper lands on average 7.2 cm on the camera side of the object. Adding one side-view camera image raises this to 34 successes.

- Environment: LIBERO simulation (Franka arm, libero_goal suite)
- Model: `gpt-6-astra`, called through the Codex CLI
- Scale: 413 GPT-6 episodes, plus 40 ground-truth control episodes
- Code and reproduction commands: [`code/`](code/README.md)

---

## 1. What we test

To "put the bowl on the plate", a robot has to get three things right in sequence:

| Ability | Meaning | Example |
|---|---|---|
| ① Planning | What to grasp, where to put it, which part to hold | "The bowl is too wide, so grasp its rim, then place it on the plate" |
| ② 2D localization | Find that location in the image | "The bowl's right rim is at column 280, row 284" |
| ③ 3D localization | That location's metric coordinates in the real scene | "The rim is at x=−0.10, y=−0.06, z=0.94 m" |

There is also a fourth: ④ **low-level control**, i.e. outputting every motor action directly, with no controller in between.

Questions: does GPT-6 manage to control robots because it has strong 3D spatial understanding, or because it is a strong planner? And can it output actions directly, the way a VLA does?

## 2. Experimental design

### Tasks

| Task | Content | Success condition |
|---|---|---|
| 8 | Put the bowl on the plate | Strict: bowl center within 3 cm of plate center |
| 1 | Put the bowl on the stove | Loose |
| 4 | Put the bowl on top of the cabinet | Loose |
| 6 | Put the cream cheese in the bowl | Strict |

Round 4 also covers the remaining 6 libero_goal tasks (see 3.4). Each condition runs 10 episodes per task, and success is judged by the simulator.

### Round 1: GPT-6 only says "where"; a fixed controller executes (conditions A–D)

At each step, two images (a fixed third-person camera and the wrist camera) plus the instruction are sent to GPT-6. It replies with only `grasp(location)`, `place(location)` or `done`, and a fixed controller moves the arm. Up to 6 calls per episode. **The only difference between the four conditions is how GPT-6 expresses "location":**

| Condition | GPT-6 outputs | It must handle itself | Handled by the program |
|---|---|---|---|
| **A** Pixel (with hints) | Pixel coordinates in the image | ① + ② | Converts the pixel to 3D with the depth map (③) |
| **B** Pixel (no hints) | Same as A | Same as A, plus two pieces of physical common sense | Same as A |
| **C** Metric xyz (answer given) | Metric 3D coordinates; the prompt lists every object's true coordinates | Only ① | ② ③ |
| **D** Metric xyz (images only) | Metric 3D coordinates; no object coordinates given | ① + ② + ③ | Nothing |

A's prompt has two hints that B's lacks: "The bowl is wider than the gripper, so grasp its rim" and "When holding the rim, the bowl's center is offset from the gripper, so compensate when placing."

How to read the results: C succeeds → planning is fine. A succeeds but D fails → 2D localization is fine, 3D localization is not. A succeeds but B fails → missing physical common sense.

**Ground-truth control**: replacing GPT-6 with the true object positions, run through the same controller, succeeds 40/40. So every failure below can be attributed to the locations or decisions GPT-6 gives.

<img src="assets/task8_grasp_points.jpg" width="420">

*GPT-6's actual outputs for the first step of task 8 (grasping the bowl). The white dot is the true bowl center. Blue = A's pixel (right rim); green = C's coordinates (left rim); red = D's coordinates (on the table outside the bowl, 8 cm off). C and D gave word-for-word identical reasoning ("grasp the left rim of the bowl so it can be lifted onto the plate"). D knows what to do; it just doesn't know where the bowl is.*

### Round 2: GPT-6 outputs robot actions directly (conditions E, F)

No controller is used. Each call, GPT-6 outputs up to 10 steps of LIBERO's native action `[dx, dy, dz, 3 rotations, gripper]` (range −1 to 1, the same format VLAs like π₀ output), which are sent to the simulator as-is. After execution it gets new images, the end-effector displacement and position, and the gripper opening. Up to 40 calls and 450 steps per episode. The prompt states the measured controller response (about 1.3 cm per step at full scale, about 1 cm of coasting after stopping, about 10 steps to close the gripper).

| Condition | GPT-6 sees | Measures |
|---|---|---|
| **E** Direct actions (coords given) | Images + end-effector position + true object coordinates | Whether it can control |
| **F** Direct actions (images only) | Images + end-effector position | Visual localization + control; closest to a VLA |

### Round 3: can the localization problem be fixed with another view or more reasoning? (conditions G, F-high)

One change on top of F:

| Condition | Change |
|---|---|
| **G** | Adds a side-view camera image. Its line of sight is perpendicular to the main camera's, so the main camera's "near/far" becomes "left/right" in this image |
| **F-high** | Reasoning effort low → high; 4 episodes per task |

### Round 4: beyond pick-and-place

Same direct-action interface; E and G on the remaining 6 libero_goal tasks.

## 3. Results

### 3.1 Round 1: planning and 2D localization work; metric 3D coordinates do not

| Task | A Pixel + hints | B Pixel, no hints | C xyz, answer given | D xyz, images only |
|---|:-:|:-:|:-:|:-:|
| 8 bowl→plate (strict) | 9/10 | 2/10 | 10/10 | 0/10 |
| 1 bowl→stove (loose) | 10/10 | 10/10 | 10/10 | 0/10 |
| 4 bowl→cabinet top (loose) | 10/10 | 10/10 | 10/10 | 0/10 |
| 6 cheese→bowl (strict) | 1/10 | 1/10 | 10/10 | 0/10 |
| **Total** | **30/40** | **23/40** | **40/40** | **0/40** |

- **① Planning works (C 40/40).** When it knows where objects are, it decomposes the task correctly, picks the right grasp part, and computes the right placement point. After a missed grasp, it infers from "the gripper closed on nothing" that it grasped too high and retries lower.
- **② 2D localization mostly works (A 9–10/10 on tasks 8/1/4).** The exception is task 6 (1/10). It points at the center of the bowl's opening in the image, but the camera looks down at an angle, so that line of sight passes through the opening and hits the bowl's far inner wall. The resulting 3D point is about 3.5 cm beyond the true center, and the cheese lands on the rim. It points at the same pixel on every retry and never shifts toward the camera. **The center in the image ≠ the center in space.** Metric feedback lets it correct itself (C); pixel feedback does not (A).
- **③ One-shot metric 3D coordinates are unusable (D 0/40).** All 40 first grasps miss. Its estimates of the bowl's position are off by 8–25 cm and change on every retry. At the end of an episode the object is still 14–27 cm from the target on average.
- **It doesn't think of physical common sense on its own.** B matches A on the loose tasks but drops from 9/10 to 2/10 on strict task 8. It aims the gripper straight at the plate center (0.5 cm off on average) without compensating for the 5 cm offset caused by holding the rim.

**Video 1**: task 8. A succeeds / C succeeds / D keeps closing the gripper on empty space next to the bowl and fails

<img src="assets/gifs/video01.gif" width="720">

**Video 2**: task 4. A succeeds / D fails

<img src="assets/gifs/video02.gif" width="720">

**Video 3**: task 8. A compensates the offset when placing and succeeds / B aims at the plate center and the bowl lands on the plate's edge

<img src="assets/gifs/video03.gif" width="720">

**Video 4**: task 6. A drops the cheese on the far rim / C succeeds / ground-truth control succeeds

<img src="assets/gifs/video04.gif" width="720">

**Video 5**: task 6. C misses, retries lower and succeeds / A keeps pointing at the same pixel and fails

<img src="assets/gifs/video05.gif" width="720">

### 3.2 Round 2: GPT-6 can control, but can't judge near vs. far

| Task | E Direct actions, coords given | F Direct actions, images only |
|---|:-:|:-:|
| 8 bowl→plate (strict) | 7/10 | 0/10 |
| 1 bowl→stove (loose) | 10/10 | 0/10 |
| 4 bowl→cabinet top (loose) | 10/10 | 1/10 |
| 6 cheese→bowl (strict) | 10/10 | 1/10 |
| **Total** | **37/40** | **2/40** |

- **It can control (E 37/40).** When it knows the target position, its own actions carry out approach, deceleration, rim alignment, descent, closing, lifting, transport and placement, in 100–130 steps on average, fewer than round 1's fixed controller (180–225). All 3 failures are on task 8: the bowl ends up on the plate but 5.5 cm from its center (threshold 3 cm), and GPT-6 declares the task done.
- **With images only, the error has a direction (F 2/40).** In most episodes the object is never touched. The plot shows the gripper's horizontal error relative to the object at the first gripper close of each episode:

<img src="assets/first_grasp_error_en.svg" width="640">

*x-axis: error along the main camera's depth direction (+ = toward the camera); y-axis: error along the image's left-right direction (cm). 40 points per condition. F lands 7.2 cm toward the camera on average, with only 0.3 cm left-right bias. G's depth error drops to 1.6 cm, E's is 0.6 cm (on the bowl tasks, E's points split into two clusters at ±5 cm because it deliberately grasps the left or right rim).*

It can align the gripper with the object in the image plane, but it can't tell whether the gripper is directly above the object or hovering 7 cm in front of it. From the oblique main camera, the two look almost the same. It will describe the gripper as "directly above the cream cheese" when it is actually 8 cm off. Seeing a new image every 10 steps doesn't help, because the same ambiguity is in every new image.

This refines round 1's conclusion: the problem is not "3D localization" in general but **depth judgment from a single oblique camera**. Left-right localization is good. It also explains why pixel pointing works: the depth map solves exactly the depth dimension for it.

**Video 8**: task 1. A (fixed controller) / E (GPT-6 outputs every action). Both succeed; E finishes faster

<img src="assets/gifs/video08.gif" width="720">

**Video 6**: task 8. E succeeds / F keeps closing the gripper on the camera side of the bowl without touching it

<img src="assets/gifs/video06.gif" width="720">

**Video 7**: task 6. E succeeds / F lands on empty space on the camera side of the cheese

<img src="assets/gifs/video07.gif" width="720">

### 3.3 Round 3: one orthogonal view fixes it; more reasoning helps little

| Task | F images only (low) | F-high images only (high) | G images + side view | Reference: E coords given |
|---|:-:|:-:|:-:|:-:|
| 8 bowl→plate (strict) | 0/10 | 0/4 | 5/10 | 7/10 |
| 1 bowl→stove (loose) | 0/10 | 1/4 | 10/10 | 10/10 |
| 4 bowl→cabinet top (loose) | 1/10 | 0/4 | 10/10 | 10/10 |
| 6 cheese→bowl (strict) | 1/10 | 2/4 | 9/10 | 10/10 |
| **Total** | **2/40 (5%)** | **3/16 (19%)** | **34/40 (85%)** | **37/40 (93%)** |

| Error at first gripper close | Along main-camera depth | Along image left-right |
|---|:-:|:-:|
| F (low) | 7.2 cm (toward camera) | 0.3 cm |
| F-high | 3.5 cm | 2.0 cm |
| G (+ side view) | **1.6 cm** | 1.9 cm |
| E (coords given) | 0.6 cm | 2.0 cm |

- **The diagnosis holds: the bottleneck is monocular depth ambiguity.** One orthogonal view raises success from 5% to 85% and cuts depth error from 7.2 to 1.6 cm, close to the 93% achieved when coordinates are given. In other words, from images alone, outputting raw motor actions, with no coordinates or depth provided, GPT-6 completes all four tasks.
- **Higher reasoning effort helps little.** High effort reaches 19%; depth error halves but is still 3.5 cm, while reasoning tokens per call rise from about 80 to about 210. With only 16 episodes, the safe conclusion is that it is far less effective than adding a view.
- **The remaining failures concentrate on strict task 8.** 4 of G's 5 failures on task 8 put the bowl on the plate 3.2–4.1 cm from center (threshold 3 cm) and declare done. E's task-8 failures have the same cause. This is placement precision plus "not checking whether the condition is actually met", not a localization problem.

**Video 9**: task 1. F fails / G succeeds (the video shows the main camera)

<img src="assets/gifs/video09.gif" width="720">

**Video 10**: task 6. F fails / G succeeds

<img src="assets/gifs/video10.gif" width="720">

**Video 11**: task 8, two G episodes. Success / bowl 3.3 cm off the plate center while GPT-6 considers the task done

<img src="assets/gifs/video11.gif" width="720">

### 3.4 Round 4: beyond pick-and-place

| Task | Type | E coords given | G images + side view |
|---|---|:-:|:-:|
| 2 wine bottle→cabinet top | Pick-place (slender object) | 10/10 | 8/10 |
| 9 wine bottle→rack | Pick-place (slender object) | 9/10 | 7/10 |
| 7 turn on stove | Press a small knob | 10/10 | 4/10 |
| 5 push plate to front of stove | Non-prehensile push | 5/10 | 0/9 |
| 0 open middle drawer | Articulated object | 0/10 | 0/9 |
| 3 open top drawer and put bowl in | Articulated object, two stages | 0/10 | 0/9 |
| **All 10 libero_goal tasks** | | **71/100** | **53/97** |

- **Control generalizes to other pick-place and pressing tasks**: the two wine-bottle tasks and turning on the stove reach 29/30 with coordinates given. The wine-bottle tasks take only 8–9 calls and 70–85 steps.
- **Drawer opening fails completely, and it is not a localization problem**: 0 with or without coordinates. The gripper always points straight down; it repeatedly descends from above the cabinet, hits the cabinet body, lifts, moves, and descends again. It never touches the handle, and the drawer never moves in any episode. Reaching a handle on the front of the cabinet requires approaching from the side or rotating the wrist, which it never does (the prompt's "keep rotations at 0 unless needed" may also discourage this).
- **Pushing is unreliable**: only 5/10 even with coordinates. In failed episodes the plate moves but doesn't reach the target region.
- **With images only, smaller targets are harder**: turning on the stove drops from 10/10 to 4/10 because it has to hit a very small knob.

**Video 14**: task 2 (wine bottle to cabinet top). E and G both succeed

<img src="assets/gifs/video14.gif" width="720">

**Video 12**: task 7 (turn on stove). E succeeds / G succeeds / G fails, gripper lands next to the knob

<img src="assets/gifs/video12.gif" width="720">

**Video 13**: task 0 (open drawer). E and G both fail, never touching the handle

<img src="assets/gifs/video13.gif" width="720">

**Video 15**: task 5 (push plate), both E. Success / plate moves but misses the target

<img src="assets/gifs/video15.gif" width="720">

### 3.5 Summary of capability boundaries

| Ability | Result | Evidence |
|---|---|---|
| Planning (task decomposition, grasp part selection) | Yes | C 40/40 |
| 2D pointing in the image | Yes; under an oblique view it confuses "image center" with "spatial center" | A 30/40; task 6 A 1/10 |
| One-shot metric 3D coordinates | No | D 0/40 |
| Monocular depth judgment | No; lands 7.2 cm toward the camera on average | F 2/40 |
| Two-view localization | Mostly yes | G 34/40 |
| Low-level control (free-space approach, grasp, transport, place, press) | Yes | E 37/40; other pick-place/press 29/30 |
| Tasks requiring a planned approach direction (drawer handles) | No | E and G both 0 |
| Sustained-contact control (pushing) | Half | E 5/10 |
| Implicit physical geometry (bowl offset when held by rim) | Doesn't think of it; only fatal on strict tasks | Task 8: A 9/10 → B 2/10 |
| Visible chain of thought | Not available; only one or two summary headings | Tested with high effort + detailed summary |

## 4. Comparison with related work

### Galbot, *GPT 6 Astra as an Embodied Policy*

They also call GPT-6 Astra through Codex (xhigh effort, allowed to read files, run code and take notes). Inputs are head and dual-wrist RGB, joint and end-effector state, the instruction and history, with no ground-truth object coordinates. Direct mode outputs dual-arm end-effector target poses, executing 1–5 steps at a time through inverse kinematics. Hybrid mode has π0.5 propose 50 candidate steps; GPT-6 either keeps the first 1–15 or supplies 1–5 corrective steps itself.

**Their reported results**

| Finding | Numbers |
|---|---|
| Direct mode works zero-shot, near-perfect on semantic pick-place | RoboLab (single arm) 49/50; RoboDojo (bimanual long-horizon) 26% |
| On long-horizon bimanual tasks, Hybrid > Direct > π0.5 alone | 48% / 26% / 15.67%; GPT changes only 14.4% of control steps; 44.8% fewer tokens |
| Hybrid is slightly worse when the lower-level VLA isn't fine-tuned on the task | RoboLab: Direct 98%, Hybrid 92%, π0.5 36% |
| Failure modes: repeated failed grasps, container-edge collisions, difficulty turning proprioceptive state into reachable end-effector targets, etc. | Qualitative, no rates |
| No attribution: "how much each factor contributes still needs further decomposition" | — |

**What this project adds**

| Finding | Evidence |
|---|---|
| Separates planning / 2D localization / 3D localization / control and measures each, with a ground-truth control ruling out the controller | C 40/40, A 30/40, D 0/40, E 37/40, F 2/40, control 40/40 |
| With the target position known, direct 7-D actions reach 37/40 in fewer steps than a hand-written controller | Condition E |
| Visual localization error is directional: 7.2 cm along camera depth, unbiased left-right. An orthogonal view fixes it (5% → 85%); higher reasoning effort helps little (19%) | Conditions F, G, F-high |
| One-shot metric coordinates are entirely unusable | Condition D 0/40 |
| The center in the image ≠ the center in space; metric feedback enables correction, pixel feedback doesn't | Task 6: A 1/10, C 10/10 |
| Implicit physical geometry isn't anticipated | Task 8: A 9/10 → B 2/10 |
| Drawer failure is unrelated to localization, and is the same class of failure as their "container-edge collisions" and "difficulty reaching end-effector targets" | Tasks 0, 3: E and G both 0 |

**Explaining the apparent contradiction**: their images-only Direct mode scores 49/50 on RoboLab pick-place, while this project's closest condition, F, scores 2/40. Both are closed-loop, images-only, with no coordinates. Four differences remain: reasoning effort (xhigh vs. low), cameras (head + two wrist vs. one oblique main + one wrist), whether code execution and note-taking are allowed, and steps per chunk (1–5 vs. 10). Round 3 tested two of them: adding an orthogonal view took us from 5% to 85%, while higher effort only reached 19%, so **camera placement is the main factor**. Code execution and chunk length have not been tested separately.

### FluxVLA issue #121

Round 1's conclusion (GPT-6 manipulates through planning and 2D image understanding and cannot give usable metric 3D coordinates) matches the phenomenon reported in this issue. This project reproduces it quantitatively over 4 tasks and 40 episodes (condition D 0/40), and further narrows the problem down to the depth dimension.

## 5. Limitations

- Only 10 episodes per condition per task. The 0/40 vs. 40/40 gaps are reliable; individual cells in A and B vary considerably (task 8 condition B scored 6/10 and 2/10 before and after a controller change), so small per-cell differences shouldn't be over-interpreted.
- Round 1 (A–D) covers only 4 pick-place tasks; the other 6 tasks were only tested with the direct-action interface.
- In the drawer tasks, condition E is given the drawer body's center rather than the handle's coordinates (the handle has no separate name in the simulator), so E there is not strictly "given the target position".
- GPT-6 is called through Codex, so each call carries Codex's system prompt; this is not identical to the bare model via the API.
- Everything except F-high uses the lowest reasoning effort; F-high has only 4 episodes per task.
- F's depth error depends on this particular oblique main-camera placement.
- There is no comparison with previous GPT generations or open-source models, so these abilities can't be claimed as new to GPT-6.

## Repository contents

```
README.md                         This report (English)
README_zh.md                      This report (Chinese)
code/                             Experiment code; see code/README.md to reproduce
results/success_rates.csv         Success counts for every condition × task
assets/task8_grasp_points.jpg     Grasp points of three conditions on task 8
assets/first_grasp_error_en.svg   Scatter plot of error at first gripper close
assets/gifs/video01-15.gif        Comparison clips (3× speed, condition and outcome labeled at top)
```
