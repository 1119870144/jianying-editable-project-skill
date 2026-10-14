"""Immutable resource bundles outside renameable Jianying project directories."""
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath
from uuid import UUID


def _resource_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("resource_id must be a canonical UUID string")
    return value


def _inside(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Resource path escapes its root: {path}")
    return resolved


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(value):
    if (not isinstance(value, str) or value in ("", ".") or "\\" in value or ":" in value
            or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
            or PurePosixPath(value).as_posix() != value):
        raise ValueError(f"Invalid relative resource path: {value}")
    return Path(value)


def _files(root):
    for path in sorted(root.rglob("*")):
        resolved = _inside(path, root)
        if path.is_dir():
            if resolved != path:
                raise ValueError(f"Linked material directories are unsupported: {path}")
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"Resource is not a regular file: {path}")


def create_resource_bundle(source_folder, draft_root, resource_id):
    """Copy materials to a new UUID directory; return a manifest for the caller.

    All sources are checked before creating the bundle. Existing bundles are
    never replaced; failed copies remain for inspection, with no cleanup delete.
    """
    resource_id = _resource_id(resource_id)
    source, draft_root = Path(source_folder).resolve(), Path(draft_root).resolve()
    materials = _inside(source / "materials", source)
    media_root = draft_root / ".codex-media" / resource_id
    _inside(media_root.parent, draft_root)
    if media_root.parent.resolve() != media_root.parent:
        raise ValueError("Resource anchor must not be a link")
    _inside(media_root, media_root.parent.resolve())
    if media_root.is_relative_to(source) or source.is_relative_to(media_root):
        raise ValueError("Source project and resource destination must not contain each other")
    if media_root.exists() or media_root.is_symlink():
        raise FileExistsError(f"Resource bundle already exists: {media_root}")
    if not materials.is_dir():
        raise ValueError(f"Missing materials directory: {materials}")
    files = []
    for path in _files(materials):
        relative = path.relative_to(materials).as_posix()
        _relative(relative)
        files.append({"path": relative, "size": path.stat().st_size, "sha256": _hash(path)})
    media_root.mkdir(parents=True)
    for item in files:
        target = media_root / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with (materials / item["path"]).open("rb") as source_stream, target.open("xb") as output:
            shutil.copyfileobj(source_stream, output)
        if target.stat().st_size != item["size"] or _hash(target) != item["sha256"]:
            raise ValueError(f"Resource changed during copy: {item['path']}")
    return {"schema_version": 1, "resource_id": resource_id,
            "media_root": str(media_root), "files": files}


def validate_resource_bundle(folder):
    """Return the verified stable root, or None for projects without a manifest.

    Both the stable resources and the project's materials backup must match the
    manifest. This function is read only and does not repair or delete anything.
    """
    folder = Path(folder).resolve()
    manifest_path = _inside(folder / "resource_manifest.json", folder)
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported resource manifest schema")
    resource_id = _resource_id(manifest.get("resource_id"))
    value = manifest.get("media_root")
    if not isinstance(value, str):
        raise ValueError("Manifest media_root must be an absolute path")
    media_root = Path(value)
    if (not media_root.is_absolute() or media_root.parent.name != ".codex-media"
            or media_root.name != resource_id or ".." in media_root.parts):
        raise ValueError("Manifest root must be .codex-media/<resource_id>")
    anchor = media_root.parent
    _inside(anchor, anchor.parent.resolve())
    if anchor.resolve() != anchor or media_root.resolve() != media_root:
        raise ValueError("Resource anchor must not be a link")
    media_root = _inside(media_root, anchor.resolve())
    backup = _inside(folder / "materials", folder)
    if (not media_root.is_dir() or not backup.is_dir() or media_root.is_relative_to(folder)
            or folder.is_relative_to(media_root)):
        raise ValueError("Stable root must exist outside the project; materials backup is required")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("Manifest files must be a list")
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Invalid resource file entry")
        relative = _relative(item.get("path"))
        if relative in seen:
            raise ValueError(f"Duplicate resource path: {relative}")
        seen.add(relative)
        if (type(item.get("size")) is not int or item["size"] < 0
                or not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64):
            raise ValueError(f"Invalid resource hash or size: {relative}")
        for root in (media_root, backup):
            path = _inside(root / relative, root)
            if (not path.is_file() or path.stat().st_size != item["size"]
                    or _hash(path) != item["sha256"]):
                raise ValueError(f"Missing or mismatched resource: {path}")
    for root in (media_root, backup):
        if {path.relative_to(root) for path in _files(root)} != seen:
            raise ValueError(f"Resource manifest file coverage mismatch: {root}")
    return media_root
