"""Install/rename checks with synthetic bytes; no real host draft is accessed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import draft_tool as tool
from resource_bundle import validate_resource_bundle


class InstallResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.drafts = self.root / "delivery", self.root / "host-drafts"
        (self.source / "materials/fonts").mkdir(parents=True)
        self.drafts.mkdir()
        self.media = self.source / "materials/clip.mp4"
        self.local_font = self.source / "materials/fonts/local.ttf"
        self.official_font = self.root / "official-cache.ttf"
        for path in (self.media, self.local_font, self.official_font):
            path.write_bytes(("synthetic " + path.name).encode())
        texts = [self.text("local", self.local_font), self.text("official", self.official_font, "123")]
        self.draft = {"id": "source-id", "name": "delivery", "duration": 2_000_000, "fps": 30,
                      "canvas_config": {"width": 360, "height": 640}, **tool.MODES,
                      "free_render_index_mode_on": False,
                      "materials": {"videos": [{"id": "media", "type": "video", "path": str(self.media),
                                                  "duration": 2_000_000}], "texts": texts},
                      "tracks": [{"id": f"track-{i}", "type": "mixed", "flag": 0 if i == 0 else 2,
                                  "segments": [self.segment(mid, i)]}
                                 for i, mid in enumerate(("media", "local", "official"))]}
        tool.write_bundle(self.source, self.draft, {})

    def text(self, mid, path, resource=""):
        return {"id": mid, "type": "text", "font_resource_id": resource, "font_path": str(path),
                "fonts": [{"resource_id": resource, "effect_id": resource, "path": str(path)}],
                "content": json.dumps({"text": mid, "styles": [{"font": {"id": resource, "path": str(path)}}]})}

    def segment(self, mid, index):
        return {"id": "segment-" + mid, "material_id": mid, "render_index": index, "track_render_index": index,
                "target_timerange": {"start": 0, "duration": 2_000_000},
                "source_timerange": {"start": 0, "duration": 2_000_000} if index == 0 else None,
                "extra_material_refs": [], "common_keyframes": []}

    def snapshot(self, root):
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def assert_paths(self, folder, media_root):
        draft = tool.read(folder / "draft_content.json")
        self.assertEqual(Path(draft["materials"]["videos"][0]["path"]), media_root / "clip.mp4")
        for text in draft["materials"]["texts"]:
            expected = self.official_font if text["font_resource_id"] else media_root / "fonts/local.ttf"
            paths = [text["font_path"], text["fonts"][0]["path"],
                     json.loads(text["content"])["styles"][0]["font"]["path"]]
            self.assertEqual([Path(value) for value in paths], [expected] * 3)
            self.assertTrue(expected.is_file())
        self.assertTrue((media_root / "clip.mp4").is_file())
        self.assertEqual(tool.read(folder / "delivery_snapshot.json"), draft)
        self.assertEqual(validate_resource_bundle(folder), media_root)
        self.assertTrue(tool.check(folder)["rename_stable_resources_verified"])

    def test_install_then_host_directory_rename_preserves_resources_and_source(self):
        before = self.snapshot(self.source)
        result = tool.install(self.source, self.drafts, "published")
        folder, media_root = Path(result["path"]), Path(result["media_root"])
        self.assert_paths(folder, media_root)
        renamed = folder.with_name("user-renamed")
        folder.rename(renamed)
        meta = tool.read(renamed / "draft_meta_info.json")
        meta.update(draft_name="User renamed display title", draft_fold_path=str(renamed))
        tool.save(renamed / "draft_meta_info.json", meta)
        self.assert_paths(renamed, media_root)
        self.assertEqual(self.snapshot(self.source), before)

    def test_reinstall_allocates_an_independent_uuid_and_keeps_first_install(self):
        first = tool.install(self.source, self.drafts, "first")
        folder, old_root = Path(first["path"]), Path(first["media_root"])
        before, media_before = self.snapshot(folder), self.snapshot(old_root)
        second = tool.install(folder, self.drafts, "second")
        new_folder, new_root = Path(second["path"]), Path(second["media_root"])
        self.assertNotEqual(old_root, new_root)
        self.assertNotEqual(first["new_draft_id"], second["new_draft_id"])
        self.assert_paths(new_folder, new_root)
        self.assertEqual(self.snapshot(old_root), self.snapshot(new_root))
        self.assertEqual(self.snapshot(folder), before)
        self.assertEqual(self.snapshot(old_root), media_before)

    def test_atomic_publish_exposes_only_a_complete_directory(self):
        destination = self.drafts / "atomic"
        original_rename, observed = Path.rename, []

        def publish(stage, target):
            self.assertEqual(target, destination)
            self.assertFalse(destination.exists())
            self.assertNotIn(self.drafts, stage.parents)
            draft = tool.read(stage / "draft_content.json")
            self.assertEqual(tool.read(stage / "delivery_snapshot.json"), draft)
            self.assertEqual(tool.read(stage / "Timelines" / draft["id"] / "draft_content.json"), draft)
            self.assertEqual(Path(tool.read(stage / "draft_meta_info.json")["draft_fold_path"]), destination)
            self.assertIsNotNone(validate_resource_bundle(stage))
            observed.append(stage)
            return original_rename(stage, target)

        with patch.object(Path, "rename", autospec=True, side_effect=publish):
            result = tool.install(self.source, self.drafts, "atomic")
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].exists())
        self.assert_paths(destination, Path(result["media_root"]))

    def test_encrypted_input_is_not_recreated_from_snapshot_or_overwritten(self):
        first = tool.install(self.source, self.drafts, "edited")
        folder = Path(first["path"])
        (folder / "draft_content.json").write_bytes(b"encoded user timeline")
        (folder / "draft_meta_info.json").write_bytes(b"encoded user metadata")
        before = self.snapshot(self.root)
        with self.assertRaises(ValueError):
            tool.install(folder, self.drafts, "must-not-recreate")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            tool.install(self.source, self.drafts, "edited")
        self.assertEqual(self.snapshot(self.root), before)
        self.assertFalse((self.drafts / "must-not-recreate").exists())

    def test_tampered_manifest_fails_public_check_without_repair(self):
        result = tool.install(self.source, self.drafts, "tampered")
        folder = Path(result["path"])
        manifest = tool.read(folder / "resource_manifest.json")
        manifest["files"][0]["sha256"] = "0" * 64
        tool.save(folder / "resource_manifest.json", manifest)
        before = self.snapshot(self.root)
        with self.assertRaisesRegex(ValueError, "mismatched"):
            tool.check(folder)
        self.assertEqual(self.snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
