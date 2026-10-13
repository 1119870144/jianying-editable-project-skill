"""Install this skill locally, preserving an existing installation as a backup."""
import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

NAME = "jianying-editable-project"
FILES = ("SKILL.md", "README.md", "requirements.txt")
DIRECTORIES = ("agents", "references", "scripts", "examples", "tests")


def install(source, skills_root):
    source, skills_root = Path(source).resolve(), Path(skills_root).resolve()
    target = skills_root / NAME
    if target == source or source in target.parents or target in source.parents:
        raise ValueError("Source and installed skill must be separate directories")
    if not (source / "SKILL.md").is_file():
        raise FileNotFoundError(source / "SKILL.md")
    for name in FILES + DIRECTORIES:
        if not (source / name).exists():
            raise FileNotFoundError(source / name)
    skills_root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Store backups outside skills/ so automatic discovery finds one skill.
        backup = skills_root.parent / "skill-backups" / f"{NAME}-{datetime.now():%Y%m%d-%H%M%S-%f}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.resolve().parent != skills_root:
            raise ValueError("Refusing to move a symlinked or external installation")
        target.rename(backup)
        print(f"Backup: {backup}")
    target.mkdir()
    for filename in FILES:
        shutil.copy2(source / filename, target / filename)
    for dirname in DIRECTORIES:
        shutil.copytree(source / dirname, target / dirname, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Installed: {target}")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    codex = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser.add_argument("--skills-root", type=Path, default=codex / "skills")
    args = parser.parse_args()
    install(Path(__file__).resolve().parents[1], args.skills_root)
