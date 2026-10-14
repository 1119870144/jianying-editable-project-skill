"""Public bundle checks with synthetic files and observed-index-shaped evidence."""
import copy
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import draft_tool as tool
from resource_bundle import create_resource_bundle
from timeline_checks import check_timeline


class BundleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "draft"
        (self.folder / "materials").mkdir(parents=True)
        self.media = self.folder / "materials/clip.mp4"
        self.font = self.folder / "materials/font.ttf"
        self.media.write_bytes(b"synthetic existence fixture; not playable media")
        self.font.write_bytes(b"synthetic font existence fixture")
        self.draft = {"id": "timeline-id", "name": "timeline-original-name", "duration": 2_000_000,
                      "fps": 30, "canvas_config": {"width": 360, "height": 640},
                      **tool.MODES, "free_render_index_mode_on": False,
                      "materials": {"videos": [{"id": "media", "type": "video", "path": str(self.media), "duration": 2_000_000}]},
                      "tracks": [{"id": "main", "type": "mixed", "flag": 0, "segments": [self.segment()]}]}
        self.index = self.root / "home-index.json"

    def segment(self):
        return {"id": "segment", "material_id": "media", "target_timerange": {"start": 0, "duration": 2_000_000},
                "source_timerange": {"start": 0, "duration": 2_000_000}, "render_index": 0,
                "track_render_index": 0, "extra_material_refs": [], "common_keyframes": []}

    def write(self):
        tool.write_bundle(self.folder, self.draft, {})

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def separate_home_identity(self):
        self.write()
        meta = tool.read(self.folder / "draft_meta_info.json")
        meta.update(draft_id="home-id", draft_name="user-renamed-title")
        tool.save(self.folder / "draft_meta_info.json", meta)
        return {"draft_id": meta["draft_id"], "draft_name": meta["draft_name"], "draft_fold_path": str(self.folder)}

    def test_home_id_needs_matching_index_and_check_is_read_only(self):
        row = self.separate_home_identity()
        tool.save(self.index, {"all_draft_store": [row]})
        before = self.snapshot()
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root / "empty-app-data")}):
            with self.assertRaisesRegex(ValueError, "home-index evidence"):
                tool.check(self.folder)
        result = tool.check(self.folder, home_index=self.index)
        self.assertEqual((result["tracks"], result["segments"], result["native_texts"], result["compound_count"]), (1, 1, 0, 0))
        self.assertTrue(result["structure_verified"])
        self.assertTrue(result["geometry"]["geometry_verified"])
        self.assertFalse(result["rename_stable_resources_verified"])
        self.assertFalse(result["cloud_roundtrip_verified"])
        self.assertEqual(self.snapshot(), before)
        self.assertNotEqual(tool.read(self.folder / "draft_content.json")["name"], row["draft_name"])

    def test_missing_wrong_or_duplicate_home_evidence_is_rejected_without_writes(self):
        row = self.separate_home_identity()
        for issue in ("missing_file", "missing_entry", "wrong_id", "wrong_name", "wrong_path", "duplicate"):
            with self.subTest(issue=issue):
                candidate = copy.deepcopy(row)
                if issue == "wrong_id": candidate["draft_id"] = "other-home-id"
                if issue == "wrong_name": candidate["draft_name"] = "other-name"
                if issue == "wrong_path": candidate["draft_fold_path"] = str(self.root / "another-draft")
                rows = [] if issue == "missing_entry" else [candidate]
                if issue == "duplicate": rows.append(copy.deepcopy(candidate))
                tool.save(self.index, {"all_draft_store": rows})
                evidence = self.root / "missing.json" if issue == "missing_file" else self.index
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "[Hh]ome-index evidence"):
                    tool.check(self.folder, home_index=evidence)
                self.assertEqual(self.snapshot(), before)

    def test_manifest_does_not_certify_references_still_inside_renamable_project(self):
        self.write()
        manifest = create_resource_bundle(self.folder, self.root / "installed", str(uuid.uuid4()))
        tool.save(self.folder / "resource_manifest.json", manifest)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "external asset"):
            tool.check(self.folder)
        self.assertEqual(self.snapshot(), before)
        # Callers without strict mode retain the previous two-root behavior.
        check_timeline(self.draft, self.folder, manifest["media_root"])
        with self.assertRaisesRegex(ValueError, "Stable media root is required"):
            check_timeline(self.draft, self.folder, stable_media_only=True)

    def compound_with_text(self, official=False):
        path = self.root / "official-cache.ttf" if official else self.font
        if official:
            path.write_bytes(self.font.read_bytes())
        rid = "observed-font-resource" if official else ""
        text = {"id": "title", "type": "text", "font_path": str(path), "font_resource_id": rid,
                "fonts": [{"resource_id": rid, "effect_id": rid, "path": str(path)}] if official else [],
                "content": json.dumps({"text": "Synthetic title", "styles": [{"font": {"id": rid, "path": str(path)}}]})}
        child = copy.deepcopy(self.draft)
        child["id"] = "child-timeline"
        child["materials"] = {"texts": [text]}
        child["tracks"][0]["segments"][0].update(material_id="title", source_timerange=None)
        self.draft["materials"]["videos"][0]["path"] = ""
        self.draft["materials"]["drafts"] = [{"id": "compound", "type": "combination", "draft": child}]
        self.draft["tracks"][0]["segments"][0]["extra_material_refs"] = ["compound"]
        return text

    def test_public_check_validates_local_fonts_inside_compounds(self):
        text = self.compound_with_text()
        self.write()
        before = self.snapshot()
        result = tool.check(self.folder)
        self.assertEqual((result["tracks"], result["segments"], result["native_texts"], result["compound_count"]), (1, 2, 1, 1))
        self.assertEqual(result["geometry"]["drafts"], 2)
        self.assertEqual(self.snapshot(), before)
        original = copy.deepcopy(text)
        for issue in ("outer_font", "inner_font"):
            with self.subTest(issue=issue):
                text.clear()
                text.update(copy.deepcopy(original))
                missing = str(self.folder / "materials/missing.ttf")
                if issue == "outer_font":
                    text["font_path"] = missing
                else:
                    content = json.loads(text["content"])
                    content["styles"][0]["font"]["path"] = missing
                    text["content"] = json.dumps(content)
                self.write()
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "materials/drafts/compound"):
                    tool.check(self.folder)
                self.assertEqual(self.snapshot(), before)

    def test_public_check_rejects_nested_official_font_reference_drift(self):
        text = self.compound_with_text(official=True)
        self.write()
        self.assertEqual(tool.check(self.folder)["native_texts"], 1)
        original = copy.deepcopy(text)
        for issue in ("inner_id", "inner_path", "registration_id", "registration_path", "missing_cache"):
            with self.subTest(issue=issue):
                text.clear()
                text.update(copy.deepcopy(original))
                content = json.loads(text["content"])
                if issue == "inner_id": content["styles"][0]["font"]["id"] = "other-resource"
                if issue == "inner_path": content["styles"][0]["font"]["path"] = str(self.font)
                if issue == "registration_id": text["fonts"][0]["effect_id"] = "other-resource"
                if issue == "registration_path": text["fonts"][0]["path"] = str(self.font)
                if issue == "missing_cache": Path(text["font_path"]).unlink()
                text["content"] = json.dumps(content)
                self.write()
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "Official font"):
                    tool.check(self.folder)
                self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
