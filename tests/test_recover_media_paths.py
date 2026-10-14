import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from recover_media_paths import recover_media_paths


class MediaRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.current, self.legacy = self.root / "renamed", self.root / "old-name"
        (self.current / "materials").mkdir(parents=True)
        self.snapshot = self.root / "snapshot.json"
        self.media = {"clip.mp4": b"synthetic video", "nested/font.ttf": b"synthetic font",
                      "image.png": b"synthetic image", "music.wav": b"synthetic audio"}
        for name, content in self.media.items():
            path = self.current / "materials" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        font = str(self.legacy / "materials/nested/font.ttf")
        self.draft = {"tracks": [], "materials": {
            "videos": [{"path": str(self.legacy / "materials/clip.mp4")},
                       {"path": str(self.legacy / "materials/image.png")}],
            "audios": [{"path": str(self.legacy / "materials/music.wav")}],
            "texts": [{"font_path": font, "fonts": [{"path": font}],
                       "content": json.dumps({"styles": [{"font": {"path": font}}]})}]}}
        self.save()
        (self.current / "draft_content.json").write_bytes(b"encoded-current-draft")
        (self.current / "draft_meta_info.json").write_bytes(b"encoded-current-meta")

    def save(self):
        self.snapshot.write_text(json.dumps(self.draft), encoding="utf-8")

    def run_recovery(self, **kwargs):
        return recover_media_paths(self.snapshot, self.current, self.legacy, **kwargs)

    def test_default_dry_run_has_hashes_and_no_legacy_writes(self):
        report = self.root / "reports/dry-run.json"
        result = self.run_recovery(report=report)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["matched_count"], 4)
        self.assertEqual(result["copied_count"], 0)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(result["copy_bytes"], sum(map(len, self.media.values())))
        self.assertEqual(json.loads(report.read_text()), result)
        for item in result["files"]:
            self.assertEqual(item["sha256"], hashlib.sha256(Path(item["source"]).read_bytes()).hexdigest())

    def test_apply_is_idempotent_and_never_writes_project_json(self):
        before = {p.relative_to(self.current): p.read_bytes() for p in self.current.rglob("*") if p.is_file()}
        result = self.run_recovery(apply=True)
        self.assertEqual(result["copied_count"], 4)
        self.assertEqual(self.run_recovery(apply=True)["existing_count"], 4)
        self.assertEqual(self.run_recovery(apply=True)["copied_count"], 0)
        for name, content in self.media.items():
            self.assertEqual((self.legacy / "materials" / name).read_bytes(), content)
        self.assertFalse(list(self.legacy.rglob("*.json")))
        after = {p.relative_to(self.current): p.read_bytes() for p in self.current.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_late_source_aborts_before_any_copy(self):
        (self.current / "materials/nested/font.ttf").unlink()
        with self.assertRaisesRegex(ValueError, "Missing source"):
            self.run_recovery(apply=True)
        self.assertFalse(self.legacy.exists())

    def test_different_existing_file_aborts_before_any_copy(self):
        target = self.legacy / "materials/music.wav"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"user file")
        with self.assertRaisesRegex(ValueError, "overwrite different"):
            self.run_recovery(apply=True)
        self.assertEqual(target.read_bytes(), b"user file")
        self.assertFalse((self.legacy / "materials/clip.mp4").exists())

    def test_nested_rich_fonts_are_found_and_non_material_values_ignored(self):
        font = str(self.legacy / "materials/nested/font.ttf")
        self.draft = {"tracks": [{"path": str(self.legacy / "materials/not-a-resource.png")}],
                      "materials": {"drafts": [{"draft": {"materials": {"texts": [
                          {"content": json.dumps({"styles": [{"font": {"path": font}}]})}]}}}],
                                    "videos": [{"path": str(self.root / "external/missing.png")}]}}
        self.save()
        result = self.run_recovery(apply=True)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual((self.legacy / "materials/nested/font.ttf").read_bytes(), b"synthetic font")

    def test_parent_traversal_and_protected_material_paths_rejected(self):
        for tail in ("../draft_content.json", "draft_content.json", "Timelines/asset.png"):
            with self.subTest(tail=tail):
                self.draft["materials"]["videos"].append({"path": str(self.legacy / "materials" / tail)})
                self.save()
                with self.assertRaises(ValueError):
                    self.run_recovery(apply=True)
                self.assertFalse(self.legacy.exists())
                self.draft["materials"]["videos"].pop()

    def test_symlink_escape_on_source_or_target_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "asset.png").write_bytes(b"outside")
        for project in (self.current, self.legacy):
            link = project / "materials/escape"
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                if os.name != "nt":
                    self.skipTest(f"Directory symlinks unavailable: {exc}")
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                               check=True, capture_output=True)
            self.draft["materials"]["videos"].append({"path": str(self.legacy / "materials/escape/asset.png")})
            self.save()
            with self.assertRaisesRegex(ValueError, "escapes"):
                self.run_recovery(apply=True)
            self.assertFalse((self.legacy / "materials/clip.mp4").exists())
            link.rmdir() if os.name == "nt" and not link.is_symlink() else link.unlink()
            self.draft["materials"]["videos"].pop()

    def test_plaintext_distinct_project_and_report_guards(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            recover_media_paths(self.snapshot, self.current, self.current, apply=True)
        existing = self.root / "index.json"
        existing.write_bytes(b"user index")
        for report in (self.snapshot, self.current / "draft_content.json", self.legacy / "report.json",
                       self.root / "root_meta_info.json", self.root / "Timelines/report.json", existing):
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.run_recovery(apply=True, report=report)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(existing.read_bytes(), b"user index")
        self.snapshot.write_bytes(b"encoded snapshot")
        with self.assertRaisesRegex(ValueError, "plaintext"):
            self.run_recovery(apply=True)

    def test_cli_defaults_to_dry_run(self):
        script = Path(__file__).resolve().parents[1] / "scripts/recover_media_paths.py"
        output = subprocess.check_output([sys.executable, str(script), str(self.snapshot),
                                          str(self.current), str(self.legacy)], text=True, encoding="utf-8")
        self.assertTrue(json.loads(output)["dry_run"])
        self.assertFalse(self.legacy.exists())


if __name__ == "__main__":
    unittest.main()
