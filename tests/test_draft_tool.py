import copy
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import draft_tool as tool


class DraftChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "draft"
        (self.folder / "materials").mkdir(parents=True)
        self.media = self.folder / "materials/clip.mp4"
        self.media.write_bytes(b"validator fixture; not a playable video")
        self.draft = {"id": "draft-id", "name": "fixture", "duration": 2_000_000, "fps": 30,
            **tool.MODES, "free_render_index_mode_on": False,
            "materials": {"videos": [{"id": "media", "type": "video", "path": str(self.media), "duration": 2_000_000}]},
            "tracks": [{"id": "main", "name": "main", "type": "mixed", "flag": 0,
                "segments": [{"id": "seg", "material_id": "media", "target_timerange": {"start": 0, "duration": 2_000_000},
                    "source_timerange": {"start": 0, "duration": 2_000_000}, "render_index": 0, "track_render_index": 0,
                    "extra_material_refs": []}]}, {"id": "overlay", "type": "mixed", "flag": 2, "segments": []}]}

    def write(self):
        tool.write_bundle(self.folder, self.draft, {})

    def test_valid_bundle(self):
        self.write()
        self.assertTrue(tool.check(self.folder)["structure_verified"])

    def test_regressions_fail(self):
        for issue in ("two_mains", "typed", "empty_main", "missing_ref", "source_overrun", "overlap", "render"):
            with self.subTest(issue=issue):
                original = copy.deepcopy(self.draft)
                main = self.draft["tracks"][0]
                seg = main["segments"][0]
                if issue == "two_mains": self.draft["tracks"][1]["flag"] = 0
                if issue == "typed": main["type"] = "video"
                if issue == "empty_main": main["segments"] = []
                if issue == "missing_ref": seg["extra_material_refs"] = ["absent"]
                if issue == "source_overrun": seg["source_timerange"]["start"] = 1_000_000
                if issue == "overlap": main["segments"].append({**copy.deepcopy(seg), "id": "other"})
                if issue == "render": seg["track_render_index"] = 2
                self.write()
                with self.assertRaises(ValueError): tool.check(self.folder)
                self.draft = original

    def test_missing_or_external_asset(self):
        self.write()
        self.media.unlink()
        with self.assertRaisesRegex(ValueError, "asset"): tool.check(self.folder)

    def test_mirror_mismatch(self):
        self.write()
        mirror = self.folder / "Timelines/draft-id/draft_content.json"
        mirror.write_text("{}")
        with self.assertRaisesRegex(ValueError, "mirror"): tool.check(self.folder)

    def test_official_font_references_survive_install_and_reject_drift(self):
        cached = self.folder.parent / "official.ttf"
        cached.write_bytes(b"font validator fixture")
        text = {"id": "text", "type": "text", "font_resource_id": "123", "font_path": str(cached),
                "fonts": [{"resource_id": "123", "effect_id": "123", "path": str(cached)}],
                "content": json.dumps({"text": "Title", "styles": [{"font": {"id": "123", "path": str(cached)}}]})}
        self.draft["materials"]["texts"] = [text]
        self.write()
        result = tool.install(self.folder, self.folder.parent, "official-installed")
        self.assertTrue(result["structure_verified"])
        original = copy.deepcopy(text)
        for issue in ("inner_id", "inner_path", "registry_id", "missing_cache"):
            with self.subTest(issue=issue):
                text = copy.deepcopy(original)
                content = json.loads(text["content"])
                if issue == "inner_id": content["styles"][0]["font"]["id"] = "wrong"
                if issue == "inner_path": content["styles"][0]["font"]["path"] = str(self.media)
                if issue == "registry_id": text["fonts"][0]["resource_id"] = "wrong"
                if issue == "missing_cache": cached.unlink()
                text["content"] = json.dumps(content)
                self.draft["materials"]["texts"] = [text]
                self.write()
                with self.assertRaisesRegex(ValueError, "Official font"): tool.check(self.folder)

    def test_build_aligns_verified_official_font_and_rejects_substitution(self):
        font, cached = self.folder / "font.ttf", self.folder.parent / "cache.ttf"
        font.write_bytes(b"identical font fixture")
        cached.write_bytes(font.read_bytes())
        manifest = {"width": 360, "height": 640, "font": str(font),
                    "font_resource": {"id": "123", "path": str(cached), "title": "Fixture"},
                    "tracks": [{"type": "mixed", "clips": [{"kind": "text", "text": "Title", "start": 0, "end": 1}]}]}
        path, output = self.folder / "manifest.json", self.folder.parent / "built"
        tool.save(path, manifest)
        self.assertTrue(tool.build(path, output)["structure_verified"])
        text = tool.read(output / "draft_content.json")["materials"]["texts"][0]
        self.assertEqual(text["font_path"], str(cached))
        self.assertEqual(json.loads(text["content"])["styles"][0]["font"]["id"], "123")
        self.assertTrue(list((output / "materials").glob("*.ttf")))
        cached.write_bytes(b"different font")
        with self.assertRaisesRegex(ValueError, "identity"):
            tool.build(path, self.folder.parent / "rejected")

    def test_builder_uses_source_clock_and_completes_partial_geometry(self):
        # A real PNG keeps this regression independent of ffmpeg installations.
        png = self.folder / "pixel.png"
        png.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG3sAAAAASUVORK5CYII="))
        manifest = {"width": 360, "height": 640, "tracks": [{"type": "mixed", "role": "person", "clips": [
            {"kind": "image", "path": str(png), "start": 2, "end": 3, "source_start": 5,
             "clip": {"transform_y": -0.2}, "keyframes": [
                 {"property": "position_x", "time": 0, "value": -0.2},
                 {"property": "position_x", "time": 0.5, "value": 0}]}]}]}
        path, output = self.folder / "manifest.json", self.folder.parent / "trimmed"
        tool.save(path, manifest)
        self.assertTrue(tool.build(path, output, compact=True)["geometry"]["geometry_verified"])
        track = tool.read(output / "draft_content.json")["tracks"][0]
        self.assertEqual(track["name"], "人物")
        self.assertNotIn("role", track)
        groups = {g["property_type"]: g["keyframe_list"] for g in track["segments"][0]["common_keyframes"]}
        self.assertEqual([k["time_offset"] for k in groups["KFTypePositionX"]], [5_000_000, 5_500_000])
        self.assertEqual(groups["KFTypePositionY"][0]["values"], [-0.2])
        self.assertEqual(groups["KFTypePositionY"][0]["time_offset"], 5_000_000)

    def test_install_keeps_source_and_rejects_overwrite(self):
        self.write()
        before = (self.folder / "draft_content.json").read_bytes()
        result = tool.install(self.folder, self.folder.parent, "installed")
        self.assertNotEqual(result["new_draft_id"], self.draft["id"])
        self.assertEqual(before, (self.folder / "draft_content.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            tool.install(self.folder, self.folder.parent, "installed")
        with self.assertRaises(ValueError): tool.install(self.folder, self.folder.parent, "../escape")

    def test_rich_text_font_migration_and_path_boundaries(self):
        source, dest = Path("C:/draft"), Path("D:/new")
        rich = json.dumps({"text": "title", "styles": [{"font": {"path": str(source / "font.ttf")}}]})
        result = json.loads(tool.relocate(rich, source, dest))
        self.assertEqual(result["styles"][0]["font"]["path"], str(dest / "font.ttf"))
        self.assertEqual(tool.relocate("C:/draft-other/a.mp4", source, dest), "C:/draft-other/a.mp4")

    def test_frame_rounding_uses_endpoints(self):
        self.assertEqual(tool.interval(1/30, 2/30, 30), {"start": 33333, "duration": 33334})
        with self.assertRaises(ValueError): tool.interval(0, 0.001, 30)
        with self.assertRaises(ValueError): tool.interval(float("nan"), 1, 30)

    def test_srt_keeps_multiline_and_rejects_invalid(self):
        path = self.folder / "captions.srt"
        path.write_text("1\n00:00:00,000 --> 00:00:01,000\nFirst\nSecond\n", encoding="utf-8")
        self.assertEqual(tool.srt_cues(path)[0]["text"], "First\nSecond")
        path.write_text("1\n00:99:00,000 --> 00:00:01,000\nBad\n", encoding="utf-8")
        with self.assertRaises(ValueError): tool.srt_cues(path)

    def test_compact_preserves_overlap_order_and_audio(self):
        tracks = []
        for i, (a, b) in enumerate(((0, 8), (0, 2), (2, 4), (1, 3), (5, 7))):
            tracks.append({"id": str(i), "type": "mixed", "segments": [{"id": str(i), "target_timerange": tool.interval(a, b, 30)}]})
        audio = {"id": "audio", "type": "audio", "segments": []}
        after = tool.compact_tracks(tracks + [audio])
        self.assertIs(after[-1], audio)
        positions = {s["id"]: i for i, t in enumerate(after) for s in t["segments"]}
        for i, a in enumerate(tracks):
            for b in tracks[i+1:]:
                if tool.overlaps(a["segments"][0], b["segments"][0]):
                    self.assertLess(positions[a["id"]], positions[b["id"]])
        self.assertEqual(positions["1"], positions["2"])


if __name__ == "__main__":
    unittest.main()
