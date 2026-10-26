"""Retargeting solver: captured joint positions -> bone rotations.

Pure numpy; Blender data is passed in through ``RigRest`` so the maths can be
unit-tested without Blender.

Method (all in armature space):
1. Build an orthonormal frame per body segment from the captured landmarks
   (primary axis = segment direction, secondary axis = a twist reference
   such as the elbow/knee hinge axis or the left-right axis of pelvis/chest).
2. Build the *same* frame from the character's rest pose (bone heads).
3. delta = frame_now * frame_rest^T is the world-space change of that segment,
   so desired_bone_rotation = delta * rest_bone_rotation. This automatically
   absorbs bone roll, axis conventions and the object transform.
4. Walk the hierarchy parent-first and convert to local ``matrix_basis``
   rotations, then to continuous quaternions.
Positions are never copied onto bones; only directions are used, so the
character keeps its own proportions.
"""

from dataclasses import dataclass, field

import numpy as np

from . import rotations as R

# MediaPipe/BlazePose joint indices used by the solver.
NOSE, L_EAR, R_EAR = 0, 7, 8
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 11, 12, 13, 14, 15, 16
L_PINKY, R_PINKY, L_INDEX, R_INDEX = 17, 18, 19, 20
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK = 23, 24, 25, 26, 27, 28
L_FOOT, R_FOOT = 31, 32


@dataclass
class RigRest:
    names: list                 # bone names, parents always before children
    parents: np.ndarray         # (B,) parent index or -1
    rest: np.ndarray            # (B, 4, 4) bone.matrix_local (armature space)
    heads: np.ndarray           # (B, 3) armature space
    tails: np.ndarray           # (B, 3)
    mapping: dict               # canonical slot -> bone name

    def index(self, slot):
        name = self.mapping.get(slot)
        return self.names.index(name) if name in self.names else None

    def head(self, slot):
        i = self.index(slot)
        return None if i is None else self.heads[i]

    def tail(self, slot):
        i = self.index(slot)
        return None if i is None else self.tails[i]

    def rot(self, i):
        m = self.rest[i, :3, :3]
        return m / np.linalg.norm(m, axis=0, keepdims=True)


@dataclass
class SolverSettings:
    root_mode: str = "FULL"          # FULL | VERTICAL | NONE
    root_scale: float = 1.0          # extra multiplier for horizontal travel
    facing_offset_deg: float = 0.0   # extra yaw applied to the capture
    hand_weight: float = 0.7         # 0 = hands follow forearm, 1 = fully tracked
    head_pitch_offset_deg: float = 12.0  # nose sits below the ear line in a neutral pose
    neck_share: float = 0.5          # fraction of head rotation given to the neck
    spine_weights: tuple = ()        # cumulative fractions, default even split
    bend_threshold_deg: tuple = (12.0, 35.0)  # hinge axis trust ramp
    # Largest plausible twist of the upper segment implied by the hinge axis;
    # beyond it the lower segment is assumed mirrored in depth (monocular ambiguity).
    max_arm_twist_deg: float = 140.0
    max_leg_twist_deg: float = 75.0


@dataclass
class SolveResult:
    quaternions: dict = field(default_factory=dict)  # bone name -> (F, 4)
    root_bone: str = ""
    root_location: np.ndarray = None                 # (F, 3) basis location of root bone
    scale_factor: float = 1.0                        # armature units per subject metre
    diagnostics: dict = field(default_factory=dict)


def canonical_axes(rig):
    """Character's (left, up, forward) unit vectors in armature space."""
    left = R.normalize(rig.head("thigh.L") - rig.head("thigh.R"))
    top = None
    for slot in ("neck", "head", "spine2", "spine1", "spine"):
        top = rig.head(slot)
        if top is not None:
            break
    if top is None:  # fall back to shoulders
        top = 0.5 * (rig.head("upper_arm.L") + rig.head("upper_arm.R"))
    up = top - rig.head("hips")
    up = R.normalize(up - left * R.dot(up, left))
    fwd = np.cross(left, up)
    return left, up, fwd


def capture_to_armature_matrix(rig, facing_offset_deg=0.0):
    """Rotation mapping contract space (subject facing -Y, Z up) to armature space."""
    left, up, fwd = canonical_axes(rig)
    rc = np.stack([left, -fwd, up], axis=-1)
    if facing_offset_deg:
        rc = rc @ R.axis_angle_matrix([0.0, 0.0, 1.0], np.radians(facing_offset_deg))
    return rc


def _rest_points(rig):
    """Rest-pose equivalents of the landmarks the solver uses."""
    def first(*candidates):
        for c in candidates:
            if c is not None:
                return c
        return None

    p = {}
    for side, sh, el, wr, hip, knee, ank, foot, idx, pky in (
            ("L", L_SH, L_EL, L_WR, L_HIP, L_KNEE, L_ANK, L_FOOT, L_INDEX, L_PINKY),
            ("R", R_SH, R_EL, R_WR, R_HIP, R_KNEE, R_ANK, R_FOOT, R_INDEX, R_PINKY)):
        p[sh] = rig.head(f"upper_arm.{side}")
        p[el] = rig.head(f"forearm.{side}")
        p[wr] = first(rig.head(f"hand.{side}"), rig.tail(f"forearm.{side}"))
        p[hip] = rig.head(f"thigh.{side}")
        p[knee] = rig.head(f"shin.{side}")
        p[ank] = first(rig.head(f"foot.{side}"), rig.tail(f"shin.{side}"))
        p[foot] = first(rig.head(f"toe_end.{side}"), rig.tail(f"toe.{side}"), rig.tail(f"foot.{side}"))
        p[idx] = rig.head(f"index1.{side}")
        p[pky] = rig.head(f"pinky1.{side}")
    return p


def _resolve_depth(upper, lower, n_fallback, depth_axis, max_twist):
    """Monocular depth ambiguity of a hinge joint: a forearm/shin bent towards
    or away from the camera projects almost identically. When the measured
    bend implies an anatomically implausible twist of the upper segment,
    use the lower segment mirrored along the camera axis instead.
    Returns (lower, mirrored_mask)."""
    cos_meas = R.dot(R.normalize(np.cross(upper, lower)), n_fallback)
    mirrored = lower - 2.0 * R.dot(lower, depth_axis)[..., None] * depth_axis
    cos_alt = R.dot(R.normalize(np.cross(upper, mirrored)), n_fallback)
    use = (cos_meas < np.cos(max_twist)) & (cos_alt > cos_meas)
    return np.where(use[..., None], mirrored, lower), use


def _hinge(upper, lower, n_fallback, lo, hi):
    """Hinge axis of a two-segment limb, blended with a fallback when straight."""
    n_meas = np.cross(upper, lower)
    ang = np.arccos(np.clip(R.dot(R.normalize(upper), R.normalize(lower)), -1.0, 1.0))
    w = np.clip((ang - lo) / (hi - lo), 0.0, 1.0)[..., None]
    n = w * R.normalize(n_meas) + (1.0 - w) * n_fallback
    bad = np.linalg.norm(n, axis=-1) < 1e-6
    n[bad] = n_fallback[bad]
    return R.normalize(n), w[..., 0]


def deltas_to_quaternions(rig, deltas, frame_count):
    """Convert armature-space delta rotations per slot into local
    ``rotation_quaternion`` values, walking the hierarchy parent-first.

    For bone i with parent p (Blender's pose evaluation):
        pose_i = pose_p * (rest_p^-1 * rest_i) * basis_i
    so basis_i = (pose_p * rest_p^-1 * rest_i)^-1 * desired_i.
    Unmapped bones keep an identity basis and are not keyed.
    """
    eye = np.broadcast_to(np.eye(3), (frame_count, 3, 3))
    desired = {}
    for slot, d in deltas.items():
        i = rig.index(slot)
        if i is not None:
            desired[i] = d @ rig.rot(i)
    out = {}
    pose_rot = [None] * len(rig.names)
    for i, name in enumerate(rig.names):
        p = rig.parents[i]
        rest_i = rig.rot(i)
        chain = eye @ rest_i if p < 0 else pose_rot[p] @ (rig.rot(p).T @ rest_i)
        if i in desired:
            pose_rot[i] = desired[i]
            basis = R.transpose(chain) @ desired[i]
            out[name] = R.make_continuous(R.quat_from_matrix(basis))
        else:
            pose_rot[i] = chain
    return out


def solve(rig, world, root, settings=None):
    """Compute bone rotations.

    rig:   RigRest
    world: (F, 33, 3) pelvis-relative joints in contract space (metres)
    root:  (F, 3) pelvis trajectory in contract space (metres)
    """
    s = settings or SolverSettings()
    F = world.shape[0]
    rc = capture_to_armature_matrix(rig, s.facing_offset_deg)
    P = world @ rc.T                    # landmarks in armature orientation (metres)
    left, up, fwd = canonical_axes(rig)
    rp = _rest_points(rig)
    lo, hi = np.radians(s.bend_threshold_deg[0]), np.radians(s.bend_threshold_deg[1])
    depth_axis = rc[:, 1]               # camera viewing direction in armature space
    deltas = {}   # slot -> (F, 3, 3) armature-space delta rotation
    diag = {}

    def delta(primary, secondary, primary0, secondary0):
        f_now = R.frame(primary, secondary)
        f_rest = R.frame(primary0, secondary0)
        return f_now @ R.transpose(f_rest)

    # --- Pelvis and chest ---------------------------------------------------
    hip_mid, sh_mid = 0.5 * (P[:, L_HIP] + P[:, R_HIP]), 0.5 * (P[:, L_SH] + P[:, R_SH])
    hip_mid0, sh_mid0 = 0.5 * (rp[L_HIP] + rp[R_HIP]), 0.5 * (rp[L_SH] + rp[R_SH])
    d_hips = delta(P[:, L_HIP] - P[:, R_HIP], sh_mid - hip_mid,
                   rp[L_HIP] - rp[R_HIP], sh_mid0 - hip_mid0)
    d_chest = delta(P[:, L_SH] - P[:, R_SH], sh_mid - hip_mid,
                    rp[L_SH] - rp[R_SH], sh_mid0 - hip_mid0)
    deltas["hips"] = d_hips
    spines = [sl for sl in ("spine", "spine1", "spine2") if rig.index(sl) is not None]
    weights = list(s.spine_weights) or [(i + 1) / len(spines) for i in range(len(spines))]
    rel = R.transpose(d_hips) @ d_chest
    for sl, wgt in zip(spines, weights):
        deltas[sl] = d_hips @ R.fraction(rel, wgt)
    chest = deltas[spines[-1]] if spines else d_chest

    # --- Head / neck -------------------------------------------------------
    if rig.index("head") is not None:
        pitch = np.radians(s.head_pitch_offset_deg)
        fwd_head0 = np.cos(pitch) * fwd - np.sin(pitch) * up
        ear_mid = 0.5 * (P[:, L_EAR] + P[:, R_EAR])
        d_head = delta(P[:, L_EAR] - P[:, R_EAR], P[:, NOSE] - ear_mid, left, fwd_head0)
        deltas["head"] = d_head
        if rig.index("neck") is not None:
            deltas["neck"] = chest @ R.fraction(R.transpose(chest) @ d_head, s.neck_share)

    # --- Limbs --------------------------------------------------------------
    for side, sh, el, wr, idx, pky in (("L", L_SH, L_EL, L_WR, L_INDEX, L_PINKY),
                                       ("R", R_SH, R_EL, R_WR, R_INDEX, R_PINKY)):
        up0, lo0 = rp[el] - rp[sh], rp[wr] - rp[el]
        n0 = R.normalize(np.cross(up0, fwd))           # elbows flex forward from a T/A pose
        upper, lower = P[:, el] - P[:, sh], P[:, wr] - P[:, el]
        n_parent = R.apply(chest, n0)
        swing = R.rotation_between(R.apply(chest, up0), upper)
        n_fb = R.apply(swing, n_parent)
        lower, mirrored = _resolve_depth(upper, lower, n_fb, depth_axis,
                                         np.radians(s.max_arm_twist_deg))
        n, w = _hinge(upper, lower, n_fb, lo, hi)
        diag[f"elbow_trust.{side}"] = float(w.mean())
        diag[f"elbow_depth_fixed.{side}"] = int(mirrored.sum())
        deltas[f"upper_arm.{side}"] = delta(upper, n, up0, n0)
        deltas[f"forearm.{side}"] = delta(lower, n, lo0, n0)
        if rig.index(f"hand.{side}") is not None:
            d_fore = deltas[f"forearm.{side}"]
            if rp[idx] is not None and rp[pky] is not None and s.hand_weight > 0:
                palm = 0.5 * (P[:, idx] + P[:, pky]) - P[:, wr]
                palm0 = 0.5 * (rp[idx] + rp[pky]) - rp[wr]
                d_track = delta(palm, P[:, idx] - P[:, pky], palm0, rp[idx] - rp[pky])
                # Hand landmarks are not depth-corrected: let mirrored frames follow the forearm.
                hand_w = np.where(mirrored, 0.0, s.hand_weight)
                deltas[f"hand.{side}"] = d_fore @ R.fraction(R.transpose(d_fore) @ d_track,
                                                              hand_w)
            else:
                deltas[f"hand.{side}"] = d_fore

    for side, hip, knee, ank, foot in (("L", L_HIP, L_KNEE, L_ANK, L_FOOT),
                                       ("R", R_HIP, R_KNEE, R_ANK, R_FOOT)):
        th0, sh0 = rp[knee] - rp[hip], rp[ank] - rp[knee]
        n0 = R.normalize(np.cross(th0, -fwd))          # knees flex backwards
        thigh, shin = P[:, knee] - P[:, hip], P[:, ank] - P[:, knee]
        swing = R.rotation_between(R.apply(d_hips, th0), thigh)
        n_fb = R.apply(swing, R.apply(d_hips, n0))
        shin, mirrored = _resolve_depth(thigh, shin, n_fb, depth_axis,
                                        np.radians(s.max_leg_twist_deg))
        n, w = _hinge(thigh, shin, n_fb, lo, hi)
        diag[f"knee_trust.{side}"] = float(w.mean())
        diag[f"knee_depth_fixed.{side}"] = int(mirrored.sum())
        deltas[f"thigh.{side}"] = delta(thigh, n, th0, n0)
        deltas[f"shin.{side}"] = delta(shin, n, sh0, n0)
        if rig.index(f"foot.{side}") is not None and rp[foot] is not None:
            deltas[f"foot.{side}"] = delta(P[:, foot] - P[:, ank], n, rp[foot] - rp[ank], n0)

    result = SolveResult(diagnostics=diag)
    result.quaternions = deltas_to_quaternions(rig, deltas, F)

    # --- Root motion ------------------------------------------------------
    hips_i = rig.index("hips")
    result.root_bone = rig.names[hips_i]
    leg_char = (np.linalg.norm(rp[L_KNEE] - rp[L_HIP]) + np.linalg.norm(rp[L_ANK] - rp[L_KNEE])
                + np.linalg.norm(rp[R_KNEE] - rp[R_HIP]) + np.linalg.norm(rp[R_ANK] - rp[R_KNEE])) * 0.5
    leg_subj = np.median(
        np.linalg.norm(world[:, L_KNEE] - world[:, L_HIP], axis=-1)
        + np.linalg.norm(world[:, L_ANK] - world[:, L_KNEE], axis=-1)
        + np.linalg.norm(world[:, R_KNEE] - world[:, R_HIP], axis=-1)
        + np.linalg.norm(world[:, R_ANK] - world[:, R_KNEE], axis=-1)) * 0.5
    all_pts = np.concatenate([rig.heads, rig.tails])
    ground = all_pts[np.argmin(all_pts @ up)]
    hips_head0 = rig.heads[hips_i]
    h_rest = float(np.dot(up, hips_head0 - ground))
    # Scale = character hip height / subject's typical hip height. The root
    # trajectory and its height come from the same pinhole estimate, so this
    # keeps the feet on the ground when standing. Pose-model limb lengths are
    # biased (they assume an average body), so leg ratio is only a fallback.
    subj_hip = float(np.median(root[:, 2]))
    if subj_hip > 0.3:
        k = h_rest / subj_hip
    else:
        k = leg_char / max(leg_subj, 1e-6)
    result.scale_factor = float(k)
    diag["subject_leg_m"] = float(leg_subj)
    if s.root_mode != "NONE":
        horiz = np.zeros((F, 3))
        if s.root_mode == "FULL":
            horiz[:, :2] = root[:, :2] * s.root_scale
        target = (hips_head0 + (k * horiz) @ rc.T
                  + up * (k * root[:, 2:3] - h_rest))
        rest_rot = rig.rot(hips_i)
        result.root_location = (target - hips_head0) @ rest_rot   # = rest_rot^T @ v
        diag["subject_hip_height_m"] = float(np.median(root[:, 2]))
        diag["character_hip_height"] = h_rest
    return result
