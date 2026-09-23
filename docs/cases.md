# Video Cases

**English** | [中文](cases_zh.md) · [← Back to overview](../README.md) · [Full report](report.md)

All clips play at 3× speed. The label at the top of each panel gives the condition and the episode's outcome. Panels in the same clip start from the same initial scene. Condition names follow the [report](report.md#setup).

## Q1. Object positions known

**Raw actions vs. a fixed controller** (task 1, bowl→stove). Left: the model only picks two targets and the fixed controller moves the arm. Right: every motor action comes from the model. Both succeed; the right one finishes sooner.

<img src="../assets/gifs/video08.gif" width="720">

**Recovering from a missed grasp** (task 6, cheese→bowl). Left, coordinates given: the first grasp closes 1.5 cm above the cheese; the model reads the empty gripper, retries lower and succeeds. Right, pixel pointing: it places the cheese on the bowl rim and keeps pointing at the same pixel on every retry until it runs out of calls.

<img src="../assets/gifs/video05.gif" width="720">

**Slender objects** (task 2, wine bottle→cabinet top). Left: raw actions with coordinates. Right: raw actions with images + side view. Both succeed.

<img src="../assets/gifs/video14.gif" width="720">

**Drawers fail even with coordinates** (task 0, open middle drawer). Left: coordinates given. Right: images + side view. The gripper repeatedly descends onto the cabinet from above and never reaches the handle.

<img src="../assets/gifs/video13.gif" width="720">

**Pushing is unreliable** (task 5, push plate; both with coordinates). Left: success. Right: the plate moves but misses the target region.

<img src="../assets/gifs/video15.gif" width="720">

## Q2. Coordinates removed

**Raw actions: coordinates vs. images only** (task 8, bowl→plate). Left: grasps the rim and places the bowl on the plate. Right: closes the gripper again and again on the camera side of the bowl without touching it, until 40 calls are used.

<img src="../assets/gifs/video06.gif" width="720">

**Same comparison on task 6** (cheese→bowl). Right: the gripper lands on empty space on the camera side of the cheese.

<img src="../assets/gifs/video07.gif" width="720">

**Three ways to express a target** (task 8). Left: pixel pointing, succeeds in 2 calls. Middle: coordinates given, succeeds in 2 calls. Right: xyz estimated from images; the gripper keeps landing next to the bowl and all 6 calls are used.

<img src="../assets/gifs/video01.gif" width="720">

**Same pattern on another task** (task 4, bowl→cabinet top). Left: pixel pointing succeeds. Right: xyz from images fails.

<img src="../assets/gifs/video02.gif" width="720">

**Image center ≠ 3D center** (task 6). Left: pixel pointing at the center of the bowl opening in the image; the point back-projects onto the far inner wall and the cheese lands on the far rim, yet the model declares success. Middle: coordinates given, succeeds. Right: ground-truth baseline, succeeds. All three use the same controller.

<img src="../assets/gifs/video04.gif" width="720">

**Implicit geometry needs a hint** (task 8). Left, with hints: offsets the gripper when placing, so the bowl center lands on the plate center. Right, without hints: aims the gripper at the plate center, the bowl lands on the plate's edge, and retries don't fix it.

<img src="../assets/gifs/video03.gif" width="720">

## Q3. Adding a side view

**Images only vs. images + side view** (task 1, bowl→stove). Left: the gripper lands on the camera side of the bowl. Right: grasps the rim and places it on the stove. (The video shows the main camera in both panels.)

<img src="../assets/gifs/video09.gif" width="720">

**Same comparison on task 6** (cheese→bowl). Left fails, right succeeds.

<img src="../assets/gifs/video10.gif" width="720">

**What the side view doesn't fix: stopping short** (task 8, two episodes with side view). Left: success. Right: the bowl ends 3.3 cm from the plate center (threshold 3 cm) and the model declares success.

<img src="../assets/gifs/video11.gif" width="720">

**What the side view doesn't fix: small targets** (task 7, turn on stove). Left: coordinates given, succeeds. Middle: side view, succeeds. Right: side view, the gripper lands next to the knob.

<img src="../assets/gifs/video12.gif" width="720">
