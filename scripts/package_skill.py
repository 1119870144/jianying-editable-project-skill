"""Create a reproducible ZIP-compatible .skill archive from an explicit file list."""
import hashlib
import zipfile
from pathlib import Path

from install_skill import NAME, FILES, DIRECTORIES


def package(root):
    root = Path(root).resolve()
    files = [root / name for name in FILES]
    for dirname in DIRECTORIES:
        files.extend(p for p in (root / dirname).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix in (".py", ".md", ".yaml", ".json"))
    dest = root / "dist" / f"{NAME}.skill"
    dest.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            entry = zipfile.ZipInfo(f"{NAME}/{path.relative_to(root).as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    dest.with_suffix(".skill.sha256").write_text(f"{digest}  {dest.name}\n", encoding="utf-8")
    print(f"{dest}\nSHA256 {digest}\nFiles {len(files)}")
    return dest


if __name__ == "__main__":
    package(Path(__file__).resolve().parents[1])
