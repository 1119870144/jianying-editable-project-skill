import copy
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
        self.draft["materials"]["videos"][0]["path"] = str(self.folder / "missing.mp4")
        self.write()
        with self.assertRaisesRegex(ValueError, "asset"): tool.check(self.folder)

    def test_mirror_mismatch(self):
        self.write()
        mirror = self.folder / "Timelines/draft-id/draft_content.json"
        mirror.write_text("{}")
        with self.assertRaisesRegex(ValueError, "mirror"): tool.check(self.folder)

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
