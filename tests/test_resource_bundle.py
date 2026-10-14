import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from resource_bundle import create_resource_bundle, validate_resource_bundle


RESOURCE_ID = "32d9e773-0df3-4f5f-b1cf-05308481dd69"


class ResourceBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.drafts = self.root / "drafts"
        self.project = self.drafts / "original-name"
        (self.project / "materials/fonts").mkdir(parents=True)
        self.files = {"video.mp4": b"synthetic video", "fonts/type.ttf": b"synthetic font"}
        for name, content in self.files.items():
            (self.project / "materials" / name).write_bytes(content)
        (self.project / "draft_content.json").write_bytes(b"encoded draft unchanged")
        self.media_root = self.drafts / ".codex-media" / RESOURCE_ID

    def create(self):
        return create_resource_bundle(self.project, self.drafts, RESOURCE_ID)

    def write_manifest(self, manifest):
        (self.project / "resource_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def link_directory(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if os.name != "nt":
                self.skipTest(f"Directory symlinks unavailable: {exc}")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           check=True, capture_output=True)

    def test_creation_and_project_rename_keep_same_verified_anchor(self):
        manifest = self.create()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["resource_id"], RESOURCE_ID)
        self.assertEqual(Path(manifest["media_root"]), self.media_root)
        self.assertFalse((self.project / "resource_manifest.json").exists())
        for item in manifest["files"]:
            content = self.files[item["path"]]
            self.assertEqual(item["size"], len(content))
            self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual((self.media_root / item["path"]).read_bytes(), content)
        self.write_manifest(manifest)
        self.assertEqual(validate_resource_bundle(self.project), self.media_root)
        renamed = self.project.with_name("renamed-by-user")
        self.project.rename(renamed)
        self.assertEqual(validate_resource_bundle(renamed), self.media_root)
        self.assertEqual((renamed / "draft_content.json").read_bytes(), b"encoded draft unchanged")

    def test_absent_manifest_preserves_legacy_compatibility(self):
        self.assertIsNone(validate_resource_bundle(self.project))

    def test_existing_bundle_never_overwritten(self):
        self.create()
        target = self.media_root / "video.mp4"
        target.write_bytes(b"user asset")
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(target.read_bytes(), b"user asset")

    def test_hash_and_size_mismatch_and_missing_backup_rejected(self):
        manifest = self.create()
        self.write_manifest(manifest)
        stable = self.media_root / "video.mp4"
        stable.write_bytes(b"X" * len(self.files["video.mp4"]))
        with self.assertRaisesRegex(ValueError, "mismatched"):
            validate_resource_bundle(self.project)
        stable.write_bytes(self.files["video.mp4"])
        backup = self.project / "materials/video.mp4"
        backup.write_bytes(b"short")
        with self.assertRaisesRegex(ValueError, "mismatched"):
            validate_resource_bundle(self.project)
        backup.unlink()
        with self.assertRaisesRegex(ValueError, "mismatched"):
            validate_resource_bundle(self.project)

    def test_manifest_paths_roots_and_duplicates_are_rejected(self):
        original = self.create()
        for path in ("../outside", "/absolute", "C:/absolute", "fonts/../../outside", "fonts\\type.ttf"):
            manifest = copy.deepcopy(original)
            manifest["files"][0]["path"] = path
            self.write_manifest(manifest)
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_resource_bundle(self.project)
        for root in (self.drafts / "elsewhere" / RESOURCE_ID, self.media_root.with_name("not-a-uuid")):
            manifest = dict(original, media_root=str(root))
            self.write_manifest(manifest)
            with self.subTest(root=root), self.assertRaises(ValueError):
                validate_resource_bundle(self.project)
        original["files"].append(original["files"][0])
        self.write_manifest(original)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_resource_bundle(self.project)

    def test_ancestor_destinations_and_invalid_uuid_rejected_before_copy(self):
        for draft_root in (self.project, self.project / "materials"):
            with self.subTest(draft_root=draft_root), self.assertRaises(ValueError):
                create_resource_bundle(self.project, draft_root, RESOURCE_ID)
        with self.assertRaises(ValueError):
            create_resource_bundle(self.project, self.drafts, "../unsafe")
        self.assertFalse(self.media_root.exists())

    def test_source_symlink_escape_rejected_before_bundle_creation(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "asset.png").write_bytes(b"outside")
        self.link_directory(self.project / "materials/escape", outside)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.create()
        self.assertFalse(self.media_root.exists())

    def test_validator_rejects_escaped_stable_file_and_backup(self):
        manifest = self.create()
        for root in (self.media_root, self.project / "materials"):
            outside = self.root / ("external-" + root.name)
            outside.mkdir()
            (outside / "video.mp4").write_bytes(self.files["video.mp4"])
            self.link_directory(root / "escape", outside)
            changed = copy.deepcopy(manifest)
            changed["files"][1]["path"] = "escape/video.mp4"
            self.write_manifest(changed)
            with self.subTest(root=root), self.assertRaisesRegex(ValueError, "escapes"):
                validate_resource_bundle(self.project)
            link = root / "escape"
            link.rmdir() if os.name == "nt" and not link.is_symlink() else link.unlink()
            link.mkdir()
            (link / "video.mp4").write_bytes(self.files["video.mp4"])

    def test_linked_bundle_anchor_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.link_directory(self.drafts / ".codex-media", outside)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.create()
        self.write_manifest({"schema_version": 1, "resource_id": RESOURCE_ID,
                             "media_root": str(self.media_root), "files": []})
        with self.assertRaisesRegex(ValueError, "escapes"):
            validate_resource_bundle(self.project)
        self.assertFalse((outside / RESOURCE_ID).exists())

    def test_manifest_cannot_omit_existing_files_or_ignore_added_files(self):
        original = self.create()
        for entries in ([], original["files"][:-1]):
            self.write_manifest(dict(original, files=entries))
            with self.subTest(entries=entries), self.assertRaisesRegex(ValueError, "coverage"):
                validate_resource_bundle(self.project)
        self.write_manifest(original)
        for root in (self.media_root, self.project / "materials"):
            extra = root / "unlisted.png"
            extra.write_bytes(b"unverified extra")
            with self.subTest(root=root), self.assertRaisesRegex(ValueError, "coverage"):
                validate_resource_bundle(self.project)
            extra.unlink()


if __name__ == "__main__":
    unittest.main()
