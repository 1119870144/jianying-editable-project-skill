import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from timeline_checks import check_timeline


class TimelineChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "draft"
        (self.folder / "materials").mkdir(parents=True)
        self.media = self.folder / "materials/clip.mp4"
        self.font = self.folder / "materials/font.ttf"
        self.media.write_bytes(b"synthetic existence fixture")
        self.font.write_bytes(b"synthetic font existence fixture")
        self.draft = self.timeline()

    def timeline(self):
        return {"duration": 2_000_000, "fps": 30, "canvas_config": {"width": 360, "height": 640},
                "materials": {"videos": [{"id": "media", "type": "video", "path": str(self.media), "duration": 2_000_000}]},
                "tracks": [{"id": "main", "type": "mixed", "flag": 0, "segments": [self.segment()]}]}

    def segment(self):
        return {"id": "segment", "material_id": "media", "target_timerange": {"start": 0, "duration": 2_000_000},
                "source_timerange": {"start": 0, "duration": 2_000_000}, "render_index": 0,
                "track_render_index": 0, "extra_material_refs": [], "common_keyframes": []}

    def compound(self, child=None):
        self.draft["materials"]["drafts"] = [{"id": "compound", "type": "combination", "draft": child or self.timeline()}]
        self.draft["materials"]["videos"][0]["path"] = ""
        self.draft["tracks"][0]["segments"][0]["extra_material_refs"] = ["compound"]
        return self.draft["materials"]["drafts"][0]["draft"]

    def text(self, path=None, official=False):
        path = str(path or self.font)
        rid = "font-resource" if official else ""
        return {"id": "text", "type": "text", "font_path": path, "font_resource_id": rid,
                "fonts": [{"resource_id": rid, "effect_id": rid, "path": path}] if official else [],
                "content": json.dumps({"text": "Title", "styles": [{"font": {"id": rid, "path": path}}]})}

    def check(self):
        return check_timeline(self.draft, self.folder)

    def test_recursive_counts_scoped_ids_and_input_unchanged(self):
        child = self.compound()
        child["materials"]["texts"] = [self.text()]
        grandchild = copy.deepcopy(child)
        child["materials"]["drafts"] = [{"id": "compound", "type": "combination", "draft": grandchild}]
        child["materials"]["videos"][0]["path"] = ""
        child["tracks"][0]["segments"][0]["extra_material_refs"] = ["compound"]
        before = copy.deepcopy(self.draft)
        report = self.check()
        self.assertEqual((report["tracks"], report["segments"], report["native_texts"], report["compound_count"]), (1, 3, 2, 2))
        self.assertEqual(self.draft, before)
        self.assertFalse(report["app_export_verified"])

    def test_nested_missing_media_font_references_and_empty_main_fail(self):
        original = copy.deepcopy(self.draft)
        for issue in ("media", "outer_font", "inner_font", "reference", "main"):
            with self.subTest(issue=issue):
                self.draft = copy.deepcopy(original)
                child = self.compound()
                child["materials"]["texts"] = [self.text()]
                if issue == "media": child["materials"]["videos"][0]["path"] = str(self.folder / "materials/missing.mp4")
                if issue == "outer_font": child["materials"]["texts"][0]["font_path"] = str(self.folder / "materials/missing.ttf")
                if issue == "inner_font": child["materials"]["texts"][0]["content"] = self.text(self.folder / "materials/missing.ttf")["content"]
                if issue == "reference": child["tracks"][0]["segments"][0]["extra_material_refs"] = ["absent"]
                if issue == "main": child["tracks"][0]["segments"] = []
                before = copy.deepcopy(self.draft)
                with self.assertRaisesRegex(ValueError, "materials/drafts/compound"):
                    self.check()
                self.assertEqual(self.draft, before)

    def test_compound_wrapper_rejects_transform_trim_speed_and_animation(self):
        self.compound()
        original = copy.deepcopy(self.draft)
        for issue in ("position", "scale", "rotation", "alpha", "flip", "trim", "speed", "speed_material", "uniform", "keys", "keyrefs", "mask", "crop", "primary_path", "direct_combination", "duration", "two_children", "missing_child", "fps", "canvas"):
            with self.subTest(issue=issue):
                self.draft = copy.deepcopy(original)
                seg = self.draft["tracks"][0]["segments"][0]
                material = self.draft["materials"]["videos"][0]
                child = self.draft["materials"]["drafts"][0]["draft"]
                clips = {"position": {"transform": {"y": .1}}, "scale": {"scale": {"x": 2}}, "rotation": {"rotation": 15},
                         "alpha": {"alpha": .8}, "flip": {"flip": {"horizontal": True}}}
                if issue in clips: seg["clip"] = clips[issue]
                if issue == "trim": seg["source_timerange"]["start"] = 1
                if issue == "speed": seg["speed"] = 2
                if issue == "speed_material":
                    self.draft["materials"]["speeds"] = [{"id": "speed", "type": "speed", "speed": 2}]
                    seg["extra_material_refs"].append("speed")
                if issue == "uniform": seg["uniform_scale"] = {"value": 2}
                if issue == "keys": seg["common_keyframes"] = [{"property_type": "KFTypeAlpha"}]
                if issue == "keyrefs": seg["keyframe_refs"] = ["curve"]
                if issue == "mask":
                    self.draft["materials"]["common_mask"] = [{"id": "mask", "type": "mask", "constant_material_id": "binding"}]
                    seg["extra_material_refs"].append("mask")
                if issue == "crop": material["crop"] = {"upper_left_x": .1}
                if issue == "primary_path": material["path"] = str(self.media)
                if issue == "direct_combination": seg["material_id"] = "compound"
                if issue == "duration": material["duration"] = 1_000_000
                if issue == "two_children":
                    self.draft["materials"]["drafts"].append({"id": "other", "type": "combination", "draft": self.timeline()})
                    seg["extra_material_refs"].append("other")
                if issue == "missing_child": seg["extra_material_refs"] = []
                if issue == "fps": child["fps"] = 24
                if issue == "canvas": child["canvas_config"]["height"] = 800
                with self.assertRaises(ValueError): self.check()

    def test_mask_binds_constant_id_of_referenced_mask_only(self):
        seg = self.draft["tracks"][0]["segments"][0]
        mask = {"id": "raw-mask-id", "type": "mask", "constant_material_id": "binding-id"}
        self.draft["materials"]["common_mask"] = [mask]
        seg["extra_material_refs"] = [mask["id"]]
        seg["common_keyframes"] = [{"property_type": "KFTypeCommonMaskPositionY", "material_id": "binding-id"}]
        self.check()
        original = copy.deepcopy(self.draft)
        for issue in ("raw_id", "absent", "not_referenced", "duplicate_refs", "ambiguous"):
            with self.subTest(issue=issue):
                self.draft = copy.deepcopy(original)
                seg = self.draft["tracks"][0]["segments"][0]
                if issue == "raw_id": seg["common_keyframes"][0]["material_id"] = "raw-mask-id"
                if issue == "absent": seg["common_keyframes"][0]["material_id"] = "other"
                if issue == "not_referenced": seg["extra_material_refs"] = []
                if issue == "duplicate_refs": seg["extra_material_refs"].append("raw-mask-id")
                if issue == "ambiguous":
                    self.draft["materials"]["common_mask"].append({**mask, "id": "other-mask"})
                    seg["extra_material_refs"].append("other-mask")
                with self.assertRaises(ValueError): self.check()

    def test_file_boundaries_and_explicit_external_root(self):
        external = self.folder.parent / "assets"
        external.mkdir()
        media = external / "clip.mp4"
        media.write_bytes(b"synthetic")
        self.draft["materials"]["videos"][0]["path"] = str(media)
        with self.assertRaisesRegex(ValueError, "external asset"): self.check()
        check_timeline(self.draft, self.folder, allowed_media_root=external)
        with self.assertRaises(ValueError): check_timeline(self.draft, self.folder, allowed_media_root=external / "sub")
        self.draft["materials"]["videos"][0]["path"] = str(self.folder / "clip.mp4")
        (self.folder / "clip.mp4").write_bytes(b"wrong directory")
        with self.assertRaisesRegex(ValueError, "external asset"): self.check()

    def test_official_font_cache_requires_matching_inner_outer_registration(self):
        cache = self.folder.parent / "cache.ttf"
        cache.write_bytes(b"synthetic official font")
        self.draft["materials"]["texts"] = [self.text(cache, official=True)]
        self.check()
        original = copy.deepcopy(self.draft)
        for issue in ("inner_id", "inner_path", "registry_id", "registry_path", "missing_cache"):
            with self.subTest(issue=issue):
                self.draft = copy.deepcopy(original)
                text = self.draft["materials"]["texts"][0]
                content = json.loads(text["content"])
                if issue == "inner_id": content["styles"][0]["font"]["id"] = "other"
                if issue == "inner_path": content["styles"][0]["font"]["path"] = str(self.font)
                if issue == "registry_id": text["fonts"][0]["effect_id"] = "other"
                if issue == "registry_path": text["fonts"][0]["path"] = str(self.font)
                if issue == "missing_cache": cache.unlink()
                text["content"] = json.dumps(content)
                with self.assertRaises(ValueError): self.check()

    def test_scope_duplicates_indices_overlap_and_source_overflow(self):
        original = copy.deepcopy(self.draft)
        for issue in ("material_id", "track_id", "segment_id", "overlap", "indices", "frame", "source", "target", "main", "typed", "nonfinite"):
            with self.subTest(issue=issue):
                self.draft = copy.deepcopy(original)
                seg = self.draft["tracks"][0]["segments"][0]
                if issue == "material_id": self.draft["materials"]["videos"].append(copy.deepcopy(self.draft["materials"]["videos"][0]))
                if issue == "track_id": self.draft["tracks"].append({"id": "main", "type": "mixed", "flag": 2, "segments": []})
                if issue in ("segment_id", "overlap"):
                    self.draft["tracks"][0]["segments"].append({**copy.deepcopy(seg), "id": "segment" if issue == "segment_id" else "other"})
                if issue == "indices": seg["track_render_index"] = 1
                if issue == "frame": seg["target_timerange"]["duration"] -= 2000
                if issue == "source": seg["source_timerange"]["start"] = 2000
                if issue == "target": seg["target_timerange"]["duration"] += 1_000_000
                if issue == "main": self.draft["tracks"][0]["flag"] = 2
                if issue == "typed": self.draft["tracks"][0]["type"] = "video"
                if issue == "nonfinite": self.draft["fps"] = float("nan")
                with self.assertRaises(ValueError): self.check()


if __name__ == "__main__":
    unittest.main()
