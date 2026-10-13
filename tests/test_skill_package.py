import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import install_skill
import package_skill


class SkillPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        for filename in install_skill.FILES:
            (self.source / filename).write_text("test", encoding="utf-8")
        for dirname in install_skill.DIRECTORIES:
            (self.source / dirname).mkdir()
            (self.source / dirname / "example.md").write_text("test", encoding="utf-8")

    def test_install_preserves_old_files_outside_discovery(self):
        root = self.base / "codex/skills"
        with contextlib.redirect_stdout(io.StringIO()):
            target = install_skill.install(self.source, root)
            (target / "local-only.txt").write_text("keep me", encoding="utf-8")
            install_skill.install(self.source, root)
        backup = list((root.parent / "skill-backups").iterdir())
        self.assertEqual(len(backup), 1)
        self.assertEqual((backup[0] / "local-only.txt").read_text(), "keep me")
        self.assertEqual([p.name for p in root.iterdir()], [install_skill.NAME])
        self.assertTrue((target / "SKILL.md").is_file())

    def test_archive_excludes_work_and_cache_and_is_reproducible(self):
        (self.source / "work").mkdir()
        (self.source / "work/private.mp4").write_bytes(b"private fixture")
        (self.source / "scripts/__pycache__").mkdir()
        (self.source / "scripts/__pycache__/a.pyc").write_bytes(b"cache")
        with contextlib.redirect_stdout(io.StringIO()):
            archive = package_skill.package(self.source)
            first = archive.read_bytes()
            package_skill.package(self.source)
        self.assertEqual(first, archive.read_bytes())
        with zipfile.ZipFile(archive) as zipped:
            self.assertIn("jianying-editable-project/SKILL.md", zipped.namelist())
            self.assertFalse(any("private.mp4" in n or "__pycache__" in n for n in zipped.namelist()))


if __name__ == "__main__":
    unittest.main()
