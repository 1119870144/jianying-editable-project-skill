import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from keyframe_integrity import normalize_geometry, validate_geometry


def key(prop, points):
    return {"id": "group-" + prop, "material_id": "", "property_type": prop,
            "keyframe_list": [{"id": f"point-{prop}-{i}", "time_offset": time,
                               "values": [value], "curveType": "Line", "graphID": ""}
                              for i, (time, value) in enumerate(points)]}


def fixture(kind="photo", start=0, speed=1.0):
    source = None if kind == "text" else {"start": start, "duration": round(2_000_000 * speed)}
    segment = {"id": "synthetic-segment", "material_id": "synthetic-media",
               "target_timerange": {"start": 10_000_000, "duration": 2_000_000},
               "source_timerange": source, "speed": speed,
               "clip": {"transform": {"x": 0.25, "y": -0.2}, "scale": {"x": 0.8, "y": 0.8},
                        "rotation": 0.0, "alpha": 1.0},
               "uniform_scale": {"on": True, "value": 1.0},
               "common_keyframes": [key("KFTypePositionX", [(start, 0.25),
                                                            (start + round(2_000_000 * speed), 0.5)])]}
    return {"materials": {"videos" if kind != "text" else "texts": [{"id": "synthetic-media", "type": kind}]},
            "tracks": [{"segments": [segment]}]}


def segment(draft):
    return draft["tracks"][0]["segments"][0]


def values_at(item, time):
    """Independent reference interpolation for the synthetic linear fixtures."""
    clip = item["clip"]
    values = {"KFTypePositionX": clip["transform"]["x"], "KFTypePositionY": clip["transform"]["y"],
              "KFTypeScaleX": clip["scale"]["x"], "KFTypeScaleY": clip["scale"]["y"],
              "KFTypeRotation": clip["rotation"], "KFTypeAlpha": clip["alpha"]}
    groups = {g["property_type"]: g["keyframe_list"] for g in item["common_keyframes"]}
    for prop in values.keys() & groups.keys():
        points = groups[prop]
        left = max((p for p in points if p["time_offset"] <= time), key=lambda p: p["time_offset"], default=points[0])
        right = min((p for p in points if p["time_offset"] >= time), key=lambda p: p["time_offset"], default=points[-1])
        if left["time_offset"] == right["time_offset"]:
            values[prop] = left["values"][0]
        else:
            ratio = (time - left["time_offset"]) / (right["time_offset"] - left["time_offset"])
            values[prop] = (1 - ratio) * left["values"][0] + ratio * right["values"][0]
    if item["uniform_scale"]["on"] and "KFTypeScaleX" in groups and "KFTypeScaleY" not in groups:
        values["KFTypeScaleY"] = values["KFTypeScaleX"]
    return values


class KeyframeIntegrityTests(unittest.TestCase):
    def test_same_property_is_scoped_to_its_material_binding(self):
        draft = fixture()
        item = segment(draft)
        item["common_keyframes"] = []
        for binding in ("first-mask", "second-mask"):
            group = key("KFTypeCommonMaskPositionY", [(0, .4), (2_000_000, .6)])
            group["material_id"] = binding
            item["common_keyframes"].append(group)
        fixed, report = normalize_geometry(draft)
        self.assertEqual(fixed, draft)
        self.assertEqual(report["anchors_added"], 0)
        item["common_keyframes"].append(copy.deepcopy(item["common_keyframes"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate property"):
            validate_geometry(draft)

    def test_bound_geometry_does_not_count_as_clip_position_anchor(self):
        draft = fixture()
        bound = key("KFTypePositionY", [(0, .5)])
        bound["material_id"] = "material-effect"
        segment(draft)["common_keyframes"].append(bound)
        fixed, report = normalize_geometry(draft)
        self.assertEqual(report["anchors_added"], 3)
        groups = segment(fixed)["common_keyframes"]
        self.assertIn(bound, groups)
        self.assertEqual(next(g for g in groups if g["property_type"] == "KFTypePositionY" and not g["material_id"])
                         ["keyframe_list"][0]["values"], [-.2])
        segment(draft)["common_keyframes"] = [bound]
        fixed, report = normalize_geometry(draft)
        self.assertEqual(fixed, draft)
        self.assertEqual(report["anchors_added"], 0)

    def test_pyjy_exports_supplied_source_clock_without_offset_conversion(self):
        from pyJianYingDraft import ClipSettings, KeyframeProperty, Timerange
        from pyJianYingDraft.segment import VisualSegment

        for speed in (.5, 1., 2.):
            with self.subTest(speed=speed):
                start = 5_000_000
                source = Timerange(start, round(2_000_000 * speed))
                native = VisualSegment("synthetic-media", source, Timerange(0, 2_000_000), speed, 0., False,
                                       clip_settings=ClipSettings(transform_y=-.2))
                native.add_keyframe(KeyframeProperty.position_x, 0, .25)
                draft = fixture("video", start, speed)
                draft["tracks"][0]["segments"] = [native.export_json()]
                with self.assertRaisesRegex(ValueError, "outside source range"):
                    normalize_geometry(draft)
                native.common_keyframes = []
                native.add_keyframe(KeyframeProperty.position_x, start, .25)
                native.add_keyframe(KeyframeProperty.position_x, start + source.duration, .5)
                draft["tracks"][0]["segments"] = [native.export_json()]
                mask = key("KFTypeCommonMaskPositionY", [(start, .4), (start + source.duration, .6)])
                mask["material_id"] = "mask-binding"
                segment(draft)["common_keyframes"].append(mask)
                fixed, _ = normalize_geometry(draft)
                self.assertIn(mask, segment(fixed)["common_keyframes"])
                for group in segment(fixed)["common_keyframes"]:
                    self.assertEqual(group["keyframe_list"][0]["time_offset"], start)

    def test_synthetic_wound_structure_is_repaired_without_changing_input(self):
        draft = fixture()
        item = segment(draft)
        item["common_keyframes"].append(key("KFTypeAlpha", [(0, 0.5), (2_000_000, 1.0)]))
        mask = key("KFTypeCommonMaskPositionY", [(0, 0.4)])
        mask["material_id"] = "synthetic-mask-constant"
        item["common_keyframes"].append(mask)
        before = copy.deepcopy(draft)
        with self.assertRaisesRegex(ValueError, "partial geometry"):
            validate_geometry(draft)
        fixed, report = normalize_geometry(draft)
        self.assertEqual(draft, before)
        self.assertEqual(report["segments_normalized"], 1)
        self.assertEqual(report["anchors_added"], 3)
        groups = {g["property_type"]: g for g in segment(fixed)["common_keyframes"]}
        self.assertEqual(groups["KFTypePositionY"]["keyframe_list"][0]["values"], [-0.2])
        for old in item["common_keyframes"]:
            self.assertEqual(groups[old["property_type"]], old)
        self.assertEqual(segment(fixed)["clip"], item["clip"])
        self.assertTrue(validate_geometry(fixed)["geometry_verified"])

    def test_nonzero_source_and_speed_keep_every_frame_geometry(self):
        for speed in (0.5, 1.0, 2.0):
            with self.subTest(speed=speed):
                draft = fixture("video", 5_000_000, speed)
                old = segment(draft)
                old["uniform_scale"]["on"] = False
                old["clip"]["scale"]["y"] = 0.3
                old["common_keyframes"].append(key("KFTypeScaleY", [(5_000_000, 0.3),
                                                                                 (5_000_000 + round(2_000_000 * speed), 0.5)]))
                fixed, _ = normalize_geometry(draft)
                new = segment(fixed)
                for group in new["common_keyframes"]:
                    self.assertEqual(group["keyframe_list"][0]["time_offset"], 5_000_000)
                for frame in range(61):
                    time = 5_000_000 + frame / 30 * 1_000_000 * speed
                    self.assertEqual(values_at(old, time), values_at(new, time))
                self.assertEqual(new["source_timerange"], old["source_timerange"])
                self.assertEqual(new["uniform_scale"], old["uniform_scale"])

    def test_text_anchors_use_zero_not_target_start(self):
        fixed, _ = normalize_geometry(fixture("text"))
        for group in segment(fixed)["common_keyframes"]:
            self.assertEqual(group["keyframe_list"][0]["time_offset"], 0)

    def test_complete_xy_double_scale_icon_is_entirely_unchanged(self):
        draft = fixture()
        item = segment(draft)
        item["uniform_scale"]["on"] = False
        for prop, value in (("KFTypePositionY", -0.2), ("KFTypeScaleX", 0.8), ("KFTypeScaleY", 0.8)):
            item["common_keyframes"].append(key(prop, [(0, value), (2_000_000, value / 2)]))
        fixed, report = normalize_geometry(draft)
        self.assertEqual(fixed, draft)
        self.assertIsNot(fixed, draft)
        self.assertEqual(report["anchors_added"], 0)

    def test_alpha_only_and_static_nonzero_position_are_unchanged(self):
        for keys in ([], [key("KFTypeAlpha", [(0, 0.0), (2_000_000, 1.0)])]):
            with self.subTest(keys=bool(keys)):
                draft = fixture()
                segment(draft)["common_keyframes"] = keys
                fixed, report = normalize_geometry(draft)
                self.assertEqual(fixed, draft)
                self.assertEqual(report["anchors_added"], 0)

    def test_recursive_compound_leaves_static_wrapper_unchanged(self):
        child = fixture("video", 4_000_000, 2.0)
        draft = fixture("combination")
        segment(draft)["common_keyframes"] = []
        draft["materials"]["drafts"] = [{"id": "nested", "type": "combination", "draft": child}]
        before = copy.deepcopy(draft)
        fixed, report = normalize_geometry(draft)
        self.assertEqual(segment(fixed), segment(draft))
        self.assertEqual(draft, before)
        self.assertIn("/materials/drafts/0/draft/", report["segments"][0]["path"])
        self.assertEqual(report["segments"][0]["source_start"], 4_000_000)
        self.assertEqual(validate_geometry(fixed)["drafts"], 2)
        twice, repeated = normalize_geometry(fixed)
        self.assertEqual(twice, fixed)
        self.assertEqual(repeated["anchors_added"], 0)

    def test_partial_y_only_adds_x_without_touching_curve(self):
        draft = fixture()
        segment(draft)["common_keyframes"] = [key("KFTypePositionY", [(0, -0.2), (2_000_000, 0.4)])]
        old = copy.deepcopy(segment(draft)["common_keyframes"][0])
        fixed, _ = normalize_geometry(draft)
        self.assertEqual(segment(fixed)["common_keyframes"][0], old)
        for frame in range(61):
            self.assertEqual(values_at(segment(draft), frame / 30 * 1e6), values_at(segment(fixed), frame / 30 * 1e6))

    def test_malformed_keyframes_fail_before_normalization(self):
        cases = {
            "duplicate property": lambda s: s["common_keyframes"].append(copy.deepcopy(s["common_keyframes"][0])),
            "duplicate or unsorted": lambda s: s["common_keyframes"][0]["keyframe_list"].append(copy.deepcopy(s["common_keyframes"][0]["keyframe_list"][0])),
            "finite number": lambda s: s["common_keyframes"][0]["keyframe_list"][0].update(values=[math.nan]),
            "outside source range": lambda s: s["common_keyframes"][0]["keyframe_list"][0].update(time_offset=0),
            "invalid time range": lambda s: s["source_timerange"].update(duration=-1),
            "speed must be positive": lambda s: s.update(speed=0),
            "empty keyframe group": lambda s: s["common_keyframes"][0].update(keyframe_list=[]),
        }
        for message, change in cases.items():
            with self.subTest(message=message):
                draft = fixture("video", 5_000_000)
                change(segment(draft))
                for function in (validate_geometry, normalize_geometry):
                    with self.assertRaisesRegex(ValueError, message):
                        function(draft)

    def test_nonfinite_clip_time_and_after_end_are_rejected(self):
        for where in ("clip", "time", "end"):
            with self.subTest(where=where):
                draft = fixture()
                item = segment(draft)
                if where == "clip": item["clip"]["transform"]["y"] = math.inf
                if where == "time": item["common_keyframes"][0]["keyframe_list"][0]["time_offset"] = math.inf
                if where == "end": item["common_keyframes"][0]["keyframe_list"][-1]["time_offset"] = 2_000_001
                with self.assertRaises(ValueError):
                    normalize_geometry(draft)


if __name__ == "__main__":
    unittest.main()
