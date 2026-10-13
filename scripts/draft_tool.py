"""Build, validate and install NEW single-timeline Jianying drafts. Python 3.10+."""
import argparse
import copy
import json
import math
import re
import shutil
import time
import uuid
from pathlib import Path


MODES = {"render_index_track_mode_on": True, "mixed_track_mode_on": True}


def uid():
    return str(uuid.uuid4()).upper()


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Unreadable JSON: {path}. Do not substitute an older draft.") from exc


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe_name(name):
    require(bool(name) and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            and name not in {".", ".."} and not name.endswith((" ", "."))
            and not re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I),
            "Name must be a single valid directory name")
    return name


def interval(start, end, fps):
    require(all(math.isfinite(float(v)) for v in (start, end, fps)) and fps > 0 and float(start) >= 0,
            "Times and FPS must be finite; FPS must be positive")
    a, b = (round(round(float(v) * fps) / fps * 1_000_000) for v in (start, end))
    require(a >= 0 and b > a, "Range must contain at least one frame")
    return {"start": a, "duration": b - a}


def srt_cues(path):
    cues = []
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        require(len(lines) >= 2, "Invalid SRT block")
        match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})", lines[0].strip())
        require(match is not None, "Invalid SRT timestamp (positioning extensions unsupported)")
        n = list(map(int, match.groups()))
        require(all(n[i] < 60 for i in (1, 2, 5, 6)), "Invalid SRT minutes/seconds")
        stamp = lambda i: n[i] * 3600 + n[i+1] * 60 + n[i+2] + n[i+3] / 1000
        cues.append({"kind": "text", "start": stamp(0), "end": stamp(4), "text": "\n".join(lines[1:])})
    return cues


def overlaps(a, b):
    a, b = a["target_timerange"], b["target_timerange"]
    return max(a.get("start", 0), b.get("start", 0)) < min(a.get("start", 0) + a["duration"], b.get("start", 0) + b["duration"])


def compact_tracks(tracks):
    """For newly built tracks only; preserve every concurrent visual z-order."""
    placed, lanes = [], []
    for track in tracks:
        if track["type"] == "audio":
            continue
        for segment in track["segments"]:
            lane = max((z + 1 for other, z in placed if overlaps(segment, other)), default=0)
            while len(lanes) <= lane:
                lanes.append({"id": uid(), "type": "mixed", "name": f"Visual {len(lanes)+1}", "is_default_name": False, "segments": []})
            lanes[lane]["segments"].append(segment)
            placed.append((segment, lane))
    for lane in lanes:
        lane["segments"].sort(key=lambda s: s["target_timerange"]["start"])
    return lanes + [t for t in tracks if t["type"] == "audio"]


def write_bundle(folder, draft, meta):
    now = int(time.time() * 1_000_000)
    save(folder / "draft_content.json", draft)
    save(folder / "Timelines" / draft["id"] / "draft_content.json", draft)
    save(folder / "Timelines/project.json", {
        "id": draft["id"], "main_timeline_id": draft["id"], "version": 0,
        "create_time": now, "update_time": now,
        "config": {**MODES, "color_space": 0, "hdr_vivid": False, "use_float_render": False},
        "timelines": [{"id": draft["id"], "name": draft["name"], "create_time": now,
                       "update_time": now, "is_marked_delete": False}]})
    meta.update(draft_id=draft["id"], draft_name=draft["name"], draft_fold_path=str(folder),
                draft_root_path=str(folder.parent), draft_cover="", tm_duration=draft["duration"],
                tm_draft_create=now, tm_draft_modified=now)
    save(folder / "draft_meta_info.json", meta)


def build(manifest_path, output, compact=False):
    import pyJianYingDraft as jy

    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    require(not output.exists(), f"Refusing to overwrite: {output}")
    safe_name(output.name)
    manifest = read(manifest_path)
    fps = manifest.get("fps", 30)
    require(isinstance(fps, int) and 1 <= fps <= 120, "This builder supports integer FPS 1..120")
    width, height = manifest["width"], manifest["height"]
    require(all(isinstance(n, int) and n > 0 for n in (width, height)), "Invalid canvas size")
    tracks = copy.deepcopy(manifest["tracks"])
    for track in tracks:
        if track.get("srt"):
            track.setdefault("clips", []).extend(srt_cues(manifest_path.parent / track["srt"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    script = jy.DraftFolder(str(output.parent)).create_draft(output.name, width, height, fps, maintrack_adsorb=False)
    copied, fonts, known_speeds, exported_tracks = {}, {}, {}, []

    def asset(value):
        src = (manifest_path.parent / value).resolve()
        require(src.is_file(), f"Missing input: {src}")
        if src not in copied:
            dst = output / "materials" / f"{len(copied)+1:04d}_{src.name}"
            dst.parent.mkdir(exist_ok=True)
            shutil.copy2(src, dst)
            copied[src] = dst
        return str(copied[src])

    for lane_index, track in enumerate(tracks):
        kind = track.get("type", "mixed")
        require(kind in ("mixed", "audio"), "Tracks must be mixed or audio")
        lane = {"id": uid(), "type": kind, "name": track.get("name", f"Track {lane_index+1}"),
                "is_default_name": False, "segments": []}
        if track.get("srt"):
            asset(track["srt"])
        for item in sorted(track.get("clips", []), key=lambda c: c["start"]):
            k = item["kind"]
            require(k in ("text", "video", "image", "audio"), f"Unsupported clip kind: {k}")
            require((k == "audio") == (kind == "audio"), "Audio must use a separate audio track")
            tr = interval(item["start"], item["end"], fps)
            timerange = jy.Timerange(**tr)
            settings = jy.ClipSettings(**item.get("clip", {}))
            if k == "text":
                style = {**manifest.get("text_style", {}), **track.get("text_style", {}), **item.get("style", {})}
                font_path = style.pop("font", manifest.get("font"))
                require(font_path is not None, "Supply a real local font file for native text")
                shadow = style.pop("shadow", None)
                require(isinstance(item["text"], str) and bool(item["text"]), "Empty native text")
                segment = jy.TextSegment(item["text"], timerange, style=jy.TextStyle(**style),
                    clip_settings=settings, shadow=jy.TextShadow(**shadow) if shadow else None)
                fonts[segment.material_id] = asset(font_path)
                known_speeds[segment.speed.global_id] = segment.speed.export_json()
                track_type = jy.TrackType.text
            else:
                material = jy.AudioMaterial(asset(item["path"])) if k == "audio" else jy.VideoMaterial(asset(item["path"]))
                if k != "audio":
                    require(material.material_type == ("photo" if k == "image" else "video"), "Clip kind does not match media")
                source = interval(item.get("source_start", 0), item.get("source_start", 0) + tr["duration"]/1e6, fps)
                require(k == "image" or source["start"] + source["duration"] <= material.duration + 1000,
                        f"Source range exceeds media duration: {item['path']}")
                kwargs = {"source_timerange": jy.Timerange(**source), "volume": item.get("volume", 1.0 if k == "audio" else 0.0)}
                if k == "audio":
                    segment = jy.AudioSegment(material, timerange, **kwargs)
                    track_type = jy.TrackType.audio
                else:
                    segment = jy.VideoSegment(material, timerange, clip_settings=settings, **kwargs)
                    track_type = jy.TrackType.video
            for keyframe in item.get("keyframes", []):
                require(k != "audio", "Visual keyframes cannot be applied to audio")
                offset = round(keyframe["time"] * 1e6)
                require(0 <= offset <= tr["duration"], "Keyframe outside clip")
                segment.add_keyframe(getattr(jy.KeyframeProperty, keyframe["property"]), offset, keyframe["value"])
            # Temporary typed tracks let the library register materials correctly.
            ref = script.append_track(jy.TrackSpec(track_type, uid()))
            script.add_segment(segment, ref)
            lane["segments"].append(segment.export_json())
        exported_tracks.append(lane)

    draft = json.loads(script.dumps())
    draft.update(id=uid(), name=output.name, **MODES, free_render_index_mode_on=False,
                 version=360000, new_version="189.0.0")
    draft["tracks"] = compact_tracks(exported_tracks) if compact else exported_tracks
    visual = [t for t in draft["tracks"] if t["type"] != "audio"]
    require(visual and visual[0]["segments"], "First visual track must contain material; no empty main track")
    for index, track in enumerate(draft["tracks"]):
        track["flag"] = 0 if track is visual[0] or track["type"] == "audio" else 2
        for segment in track["segments"]:
            segment.update(render_index=index, track_render_index=index)
    materials = draft["materials"]
    for material in materials.get("texts", []):
        path = fonts[material["id"]]
        content = json.loads(material["content"])
        for style in content["styles"]:
            style["font"] = {"id": "", "path": path}
        material.update(content=json.dumps(content, ensure_ascii=False), font_path=path, font_resource_id="", fonts=[])
    ids = {m["id"] for values in materials.values() for m in values if isinstance(m, dict) and "id" in m}
    materials.setdefault("speeds", []).extend(value for key, value in known_speeds.items() if key not in ids)
    # Observed local-media defaults in Jianying 11.6; not official capability bits.
    for material in materials.get("videos", []):
        material.update(local_material_id=uid(), unique_id=uid(), material_id="", check_flag=62978047,
                        is_unified_beauty_mode=True, is_set_beauty_mode=True,
                        stable={"time_range": {}}, matting={"path": ""},
                        video_algorithm={"path": "", "story_video_modify_video_config": {}})
    video_ids = {m["id"] for m in materials.get("videos", [])}
    for track in draft["tracks"]:
        for segment in track["segments"]:
            if segment["material_id"] not in video_ids:
                continue
            segment["source"] = "segmentsourcenormal"
            for category, typ in (("placeholder_infos", "placeholder_info"), ("canvases", "canvas_color"),
                                  ("sound_channel_mappings", "none"), ("material_colors", None),
                                  ("vocal_separations", "vocal_separation")):
                ref = {"id": uid()}
                if typ:
                    ref["type"] = typ
                if category == "placeholder_infos":
                    ref["meta_type"] = "none"
                materials.setdefault(category, []).append(ref)
                segment["extra_material_refs"].append(ref["id"])
    write_bundle(output, draft, read(output / "draft_meta_info.json"))
    return check(output)


def check(folder):
    folder = Path(folder).resolve()
    draft = read(folder / "draft_content.json")
    project = read(folder / "Timelines/project.json")
    require(all(draft.get(k) is v and project["config"].get(k) is v for k, v in MODES.items()), "Draft/project modes mismatch")
    require(draft.get("free_render_index_mode_on") is False, "Unexpected legacy render mode")
    require(project["id"] == project["main_timeline_id"] == draft["id"], "Project/timeline ID mismatch")
    require([t["id"] for t in project["timelines"]] == [draft["id"]], "Only single-timeline bundles supported")
    require(read(folder / "Timelines" / draft["id"] / "draft_content.json") == draft, "Timeline mirror mismatch")
    meta = read(folder / "draft_meta_info.json")
    require(meta["draft_id"] == draft["id"] and Path(meta["draft_fold_path"]).resolve() == folder, "Draft metadata mismatch")
    visual = [t for t in draft["tracks"] if t["type"] != "audio"]
    require(visual and all(t["type"] == "mixed" for t in visual), "Typed visual tracks prevent mixed placement")
    mains = [t for t in visual if t.get("flag", 0) == 0]
    require(len(mains) == 1 and mains[0] is visual[0] and mains[0].get("segments"), "Require one populated bottom main track")
    require(all(t.get("flag") == 2 for t in visual[1:]), "Overlay tracks must use flag=2")
    materials = {}
    for values in draft["materials"].values():
        for material in values:
            if isinstance(material, dict) and "id" in material:
                require(material["id"] not in materials, "Duplicate material ID")
                require("draft" not in material, "Nested drafts require separate validation")
                materials[material["id"]] = material

    def bundled_file(value):
        if value:
            path = Path(value).resolve()
            require(path.is_file() and folder in path.parents, f"Missing or external asset: {value}")

    for material in materials.values():
        for key in ("path", "font_path"):
            bundled_file(material.get(key))
        if material.get("type") == "text":
            content = json.loads(material["content"])
            require(isinstance(content["text"], str) and bool(content["text"]), "Empty native text")
            for style in content.get("styles", []):
                require(style.get("font", {}).get("path"), "Native text needs a local font path")
                bundled_file(style["font"]["path"])
            for font in material.get("fonts", []):
                bundled_file(font.get("path"))
    segment_ids, track_ids = set(), set()
    for index, track in enumerate(draft["tracks"]):
        require(track["id"] not in track_ids, "Duplicate track ID")
        track_ids.add(track["id"])
        end = 0
        for segment in track.get("segments", []):
            require(segment["id"] not in segment_ids, "Duplicate segment ID")
            segment_ids.add(segment["id"])
            r = segment["target_timerange"]
            start, duration = r.get("start", 0), r["duration"]
            require(start >= end and duration > 0, "Overlapping, unsorted or empty segment")
            end = start + duration
            require(end <= draft["duration"], "Segment exceeds draft duration")
            require(all(abs(v*draft["fps"]/1e6-round(v*draft["fps"]/1e6)) < .001 for v in (start, end)), "Time is not frame aligned")
            require(segment.get("track_render_index") == index and segment.get("render_index") == index, "Stale render index")
            require(segment["material_id"] in materials, "Missing primary material")
            require(all(ref in materials for ref in segment.get("extra_material_refs", [])), "Missing extra material reference")
            material = materials[segment["material_id"]]
            require((material["type"] in ("music", "audio", "extract_music")) == (track["type"] == "audio"), "Material on incompatible track")
            if material["type"] in ("video", "music", "audio", "extract_music"):
                src = segment["source_timerange"]
                require(src.get("start", 0) >= 0 and src["duration"] > 0 and
                        src.get("start", 0) + src["duration"] <= material["duration"] + 1000, "Source range exceeds media duration")
    return {"structure_verified": True, "tracks": len(draft["tracks"]), "segments": len(segment_ids),
            "native_texts": len(draft["materials"].get("texts", [])), "app_preview_verified": False,
            "app_export_verified": False}


def relocate(value, source, dest):
    if isinstance(value, dict):
        return {k: relocate(v, source, dest) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate(v, source, dest) for v in value]
    if isinstance(value, str):
        # Rich text stores another JSON document inside a string.
        if value.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(relocate(json.loads(value), source, dest), ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        for old, new in ((str(source), str(dest)), (source.as_posix(), dest.as_posix())):
            if value == old or value.startswith(old + "/") or value.startswith(old + "\\"):
                return new + value[len(old):]
    return value


def install(source, root, name):
    source, root = Path(source).resolve(), Path(root).resolve()
    dest = root / safe_name(name)
    require(root.is_dir(), "Select an existing Jianying draft root directory")
    require(not dest.exists(), f"Refusing to overwrite: {dest}")
    require(source not in dest.parents, "Destination cannot be inside source")
    check(source)
    draft = read(source / "draft_content.json")
    old_id = draft["id"]
    # Copy only this tool's bundle files; do not carry caches or account data.
    dest.mkdir()
    shutil.copytree(source / "materials", dest / "materials")
    draft = relocate(draft, source, dest)
    draft.update(id=uid(), name=name)
    write_bundle(dest, draft, relocate(read(source / "draft_meta_info.json"), source, dest))
    result = check(dest)
    result.update(path=str(dest), new_draft_id=draft["id"], source_draft_id=old_id)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    b.add_argument("manifest", type=Path)
    b.add_argument("output", type=Path)
    b.add_argument("--compact", action="store_true")
    c = commands.add_parser("check")
    c.add_argument("folder", type=Path)
    i = commands.add_parser("install")
    i.add_argument("source", type=Path)
    i.add_argument("root", type=Path)
    i.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.manifest, args.output, args.compact)
        elif args.command == "check":
            result = check(args.folder)
        else:
            result = install(args.source, args.root, args.name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(1, f"FAILED: {exc}\n")


if __name__ == "__main__":
    main()
