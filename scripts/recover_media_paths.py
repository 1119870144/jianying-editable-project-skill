"""Restore missing legacy materials from a renamed project; never rewrite drafts."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


PROTECTED = {"draft_content.json", "draft_meta_info.json", "draft_info.json",
             "root_meta_info.json", "project.json"}


def _paths(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("path", "font_path") and isinstance(child, str) and child:
                yield child
            if key == "content" and isinstance(child, str):
                try:
                    child = json.loads(child)
                except json.JSONDecodeError:
                    continue
            yield from _paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _paths(child)


def _inside(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes materials directory: {path}")
    return resolved


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def recover_media_paths(snapshot, current_project, legacy_project, apply=False, report=None):
    """Preflight every source/hash before copying only absent legacy resources.

    The plaintext snapshot is evidence only. Current draft/meta, timelines and
    indexes remain untouched, including encoded drafts. Report output must be
    outside both project directories and must not replace the snapshot.
    """
    snapshot = Path(snapshot).resolve()
    current, legacy = Path(current_project).resolve(), Path(legacy_project).resolve()
    if current == legacy or current.is_relative_to(legacy) or legacy.is_relative_to(current):
        raise ValueError("Current and legacy projects must be distinct, non-nested directories")
    if not current.is_dir() or (legacy.exists() and not legacy.is_dir()):
        raise ValueError("Invalid current or legacy project directory")
    try:
        draft = json.loads(snapshot.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Snapshot must be a plaintext draft JSON") from exc
    if not isinstance(draft, dict) or not isinstance(draft.get("materials"), dict) or not isinstance(draft.get("tracks"), list):
        raise ValueError("Snapshot must contain draft materials and tracks")
    report_path = Path(report).resolve() if report is not None else None
    if report_path and (report_path == snapshot or report_path.is_relative_to(current)
                        or report_path.is_relative_to(legacy) or report_path.name.casefold() in PROTECTED
                        or "timelines" in (p.casefold() for p in report_path.parts) or report_path.exists()):
        raise ValueError("Report must not overwrite a snapshot, project, timeline or index")
    old_base, new_base = legacy / "materials", current / "materials"
    old_resolved, new_resolved = _inside(old_base, legacy), _inside(new_base, current)
    plan = {}
    for value in _paths(draft["materials"]):
        path = Path(value.replace("\\", "/"))
        if ".." in path.parts:
            raise ValueError(f"Parent traversal in material path: {value}")
        if not path.is_absolute() or not path.is_relative_to(old_base):
            continue
        relative = path.relative_to(old_base)
        if path.name.casefold() in PROTECTED or "timelines" in (p.casefold() for p in relative.parts):
            raise ValueError(f"Refusing to restore an engineering JSON/index as media: {path}")
        source = _inside(new_base / relative, new_resolved)
        target = _inside(old_base / relative, old_resolved)
        if not source.is_file():
            raise ValueError(f"Missing source material: {source}")
        digest, size = _digest(source), source.stat().st_size
        if target.exists() and (not target.is_file() or _digest(target) != digest):
            raise ValueError(f"Refusing to overwrite different legacy material: {target}")
        plan[target] = {"source": str(source), "target": str(target), "sha256": digest,
                        "bytes": size, "status": "existing" if target.exists() else "missing"}
    files = list(plan.values())
    missing = [item for item in files if item["status"] == "missing"]
    if apply:
        for item in missing:
            source, target = Path(item["source"]), Path(item["target"])
            _inside(source, new_resolved)
            _inside(target, old_resolved)
            target.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                with target.open("xb") as output:
                    created = True
                    with source.open("rb") as input_stream:
                        shutil.copyfileobj(input_stream, output)
                if _digest(target) != item["sha256"]:
                    raise ValueError(f"Source changed while copying: {source}")
            except Exception:
                if created:
                    target.unlink()
                raise
            item["status"] = "copied"
    result = {"dry_run": not apply, "matched_count": len(files), "missing_count": len(missing),
              "existing_count": len(files) - len(missing), "copied_count": len(missing) if apply else 0,
              "total_bytes": sum(item["bytes"] for item in files),
              "copy_bytes": sum(item["bytes"] for item in missing), "files": files}
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="Plaintext draft snapshot; read only")
    parser.add_argument("current_project")
    parser.add_argument("legacy_project")
    parser.add_argument("--apply", action="store_true", help="Copy missing resources after full preflight")
    parser.add_argument("--report", help="Optional new JSON report outside both projects")
    args = parser.parse_args()
    result = recover_media_paths(args.snapshot, args.current_project, args.legacy_project, args.apply, args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
