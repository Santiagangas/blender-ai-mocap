from ai_mocap.rig.mapping import MIXAMO, REQUIRED, auto_map, split_side, strip_prefix


def test_mixamo_with_and_without_namespace():
    for prefix in ("mixamorig:", "mixamorig9:", ""):
        names = [prefix + n for n in MIXAMO.values()]
        mapping, report = auto_map(names)
        assert report["ok"] and report["is_mixamo"]
        assert mapping["upper_arm.L"] == prefix + "LeftArm"
        assert mapping["shin.R"] == prefix + "RightLeg"


def test_rigify_style_names():
    names = ["hips", "spine", "chest", "neck", "head",
             "upper_arm.L", "forearm.L", "hand.L", "upper_arm.R", "forearm.R", "hand.R",
             "thigh.L", "shin.L", "foot.L", "thigh.R", "shin.R", "foot.R"]
    mapping, report = auto_map(names)
    assert report["ok"], report
    assert mapping["thigh.L"] == "thigh.L" and mapping["forearm.R"] == "forearm.R"


def test_unreal_style_names():
    names = ["pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head",
             "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l",
             "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r",
             "thigh_l", "calf_l", "foot_l", "ball_l", "thigh_r", "calf_r", "foot_r", "ball_r"]
    mapping, report = auto_map(names)
    assert report["ok"], report
    assert mapping["hips"] == "pelvis"
    assert mapping["shin.L"] == "calf_l"
    assert mapping["shoulder.R"] == "clavicle_r"


def test_unrecognised_rig_reports_missing_required():
    mapping, report = auto_map(["Bone", "Bone.001", "Bone.002"])
    assert not report["ok"]
    assert set(report["missing_required"]) == set(REQUIRED)


def test_side_parsing():
    assert split_side("mixamorig:LeftForeArm") == ("L", "forearm")
    assert split_side("upper_arm.R") == ("R", "upperarm")
    assert split_side("L_Thigh") == ("L", "thigh")
    assert strip_prefix("mixamorig12:Hips") == "Hips"
