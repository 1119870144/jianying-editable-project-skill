"""Read-only validation for a timeline and untransformed native compounds.

Bundle metadata, mirrors, media registration and keyframe curves are checked by
their respective modules. IDs and references here belong to each local draft.
"""
import json
import math
from pathlib import Path


AUDIO = {"music", "audio", "extract_music"}
MEDIA = AUDIO | {"video", "photo"}


def _require(ok, location, message):
    if not ok:
        raise ValueError(f"{location}: {message}")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _range(value, location):
    _require(isinstance(value, dict), location, "Missing time range")
    start, duration = value.get("start", 0), value.get("duration")
    _require(all(isinstance(v, int) and not isinstance(v, bool) for v in (start, duration))
             and start >= 0 and duration > 0, location, "Invalid time range")
    return start, duration


def _identity(segment, material, references, location):
    clip = segment.get("clip") or {}
    _require(isinstance(clip, dict), location, "Unsupported transformed compound wrapper")
    expected = {"alpha": 1, "rotation": 0, "scale": {"x": 1, "y": 1},
                "transform": {"x": 0, "y": 0}, "flip": {"horizontal": False, "vertical": False}}
    for key, default in expected.items():
        value = clip.get(key, default)
        if isinstance(default, dict):
            _require(isinstance(value, dict) and all(value.get(k, v) == v for k, v in default.items()),
                     location, "Unsupported transformed compound wrapper")
        else:
            _require(value == default, location, "Unsupported transformed compound wrapper")
    _require(segment.get("speed", 1) == 1 and
             (segment.get("uniform_scale") or {}).get("value", 1) == 1 and
             not segment.get("common_keyframes") and not segment.get("keyframe_refs"),
             location, "Unsupported animated or retimed compound wrapper")
    full_crop = {"upper_left_x": 0, "upper_left_y": 0, "upper_right_x": 1, "upper_right_y": 0,
                 "lower_left_x": 0, "lower_left_y": 1, "lower_right_x": 1, "lower_right_y": 1}
    _require(not material.get("crop") or material["crop"] == full_crop,
             location, "Unsupported cropped compound wrapper")
    for ref in references:
        _require(ref.get("type") not in ("mask", "common_mask"), location, "Unsupported masked compound wrapper")
        if ref.get("type") == "speed":
            _require(ref.get("speed", 1) == 1 and not ref.get("curve_speed"),
                     location, "Unsupported retimed compound wrapper")


def check_timeline(draft, folder, allowed_media_root=None, stable_media_only=False):
    """Return recursive counts or raise ValueError; never modify ``draft``.

    Ordinary files must exist under folder/materials or allowed_media_root.
    With stable_media_only, require and exclusively use allowed_media_root.
    Verified official font registrations may point to an existing external cache.
    Compounds must be whole, identity wrappers around one same-canvas/FPS draft.
    """
    folder = Path(folder).resolve()
    _require(not stable_media_only or allowed_media_root, "draft", "Stable media root is required")
    roots = [] if stable_media_only else [(folder / "materials").resolve()]
    if allowed_media_root is not None:
        roots.append(Path(allowed_media_root).resolve())
    root_canvas, root_fps = draft.get("canvas_config"), draft.get("fps")
    report = {"structure_verified": True, "tracks": len(draft.get("tracks", [])),
              "segments": 0, "native_texts": 0, "compound_count": 0,
              "app_preview_verified": False, "app_export_verified": False}

    def asset(value, location, official=False):
        prefix = "Official font: " if official else ""
        _require(isinstance(value, str) and bool(value), location, prefix + "Missing asset path")
        path = Path(value)
        path = (path if path.is_absolute() else folder / path).resolve()
        _require(path.is_file() and (official or any(root in path.parents for root in roots)),
                 location, prefix + f"Missing or external asset: {value}")
        return path

    def text_font(material, location):
        content = json.loads(material["content"])
        _require(isinstance(content.get("text"), str) and bool(content["text"]), location, "Empty native text")
        styles = content.get("styles", [])
        _require(isinstance(styles, list) and bool(styles), location, "Native text needs font styles")
        official = material.get("font_resource_id")
        path = None
        if official:
            path = asset(material.get("font_path"), location + "/font_path", official=True)
            registered = material.get("fonts", [])
            _require(len(registered) == 1 and
                     registered[0].get("resource_id") == registered[0].get("effect_id") == official and
                     asset(registered[0].get("path"), location + "/fonts", official=True) == path,
                     location, "Official font registration mismatch")
        elif material.get("font_path"):
            asset(material["font_path"], location + "/font_path")
        for style in styles:
            font = style.get("font", {})
            inner = asset(font.get("path"), location + "/content/font", official=bool(official))
            if official:
                _require(font.get("id") == official and inner == path, location,
                         "Official font inner/outer reference mismatch")
        if not official:
            for font in material.get("fonts", []):
                asset(font.get("path"), location + "/fonts")

    def visit(node, location):
        duration, fps = node.get("duration"), node.get("fps")
        _require(isinstance(duration, int) and not isinstance(duration, bool) and duration > 0 and
                 _number(fps) and fps > 0, location, "Invalid draft duration or FPS")
        _require(abs(duration * fps / 1e6 - round(duration * fps / 1e6)) < .001,
                 location, "Draft duration is not frame aligned")
        if location != "draft":
            canvas = node.get("canvas_config")
            _require(isinstance(root_canvas, dict) and isinstance(canvas, dict) and
                     all(isinstance(root_canvas.get(k), int) and root_canvas[k] > 0 and
                         canvas.get(k) == root_canvas[k] for k in ("width", "height")) and fps == root_fps,
                     location, "Compound canvas/FPS mismatch")
        tracks = node.get("tracks", [])
        visual = [t for t in tracks if t.get("type") != "audio"]
        _require(visual and all(t.get("type") == "mixed" for t in visual),
                 location, "Typed visual tracks prevent mixed placement")
        mains = [t for t in visual if t.get("flag", 0) == 0]
        _require(len(mains) == 1 and mains[0] is visual[0] and mains[0].get("segments"),
                 location, "Require one populated bottom main track")
        _require(all(t.get("flag") == 2 for t in visual[1:]), location, "Overlay tracks must use flag=2")
        materials, combinations, mask_ids = {}, {}, set()
        for category, values in node.get("materials", {}).items():
            for material in values:
                if not isinstance(material, dict) or "id" not in material:
                    continue
                mid = material["id"]
                _require(isinstance(mid, str) and mid and mid not in materials, location, "Duplicate or empty material ID")
                materials[mid] = material
                if category == "common_mask":
                    mask_ids.add(mid)
                if "draft" in material or category == "drafts":
                    _require(category == "drafts" and material.get("type") == "combination" and
                             isinstance(material.get("draft"), dict), location, "Unsupported nested draft material")
                    combinations[mid] = material
                if material.get("path"):
                    asset(material["path"], location + "/materials/" + mid)
                if material.get("type") in ("text", "subtitle"):
                    text_font(material, location + "/materials/" + mid)
                    report["native_texts"] += 1
        segment_ids, track_ids, used_combinations = set(), set(), set()
        for index, track in enumerate(tracks):
            tl = f"{location}/tracks/{index}"
            tid = track.get("id")
            _require(isinstance(tid, str) and tid and tid not in track_ids, tl, "Duplicate or empty track ID")
            track_ids.add(tid)
            end = 0
            for si, segment in enumerate(track.get("segments", [])):
                sl = f"{tl}/segments/{si}"
                sid = segment.get("id")
                _require(isinstance(sid, str) and sid and sid not in segment_ids, sl, "Duplicate or empty segment ID")
                segment_ids.add(sid)
                start, length = _range(segment.get("target_timerange"), sl)
                _require(start >= end, sl, "Overlapping or unsorted segment")
                end = start + length
                _require(end <= duration, sl, "Segment exceeds draft duration")
                _require(all(abs(v * fps / 1e6 - round(v * fps / 1e6)) < .001 for v in (start, end)),
                         sl, "Time is not frame aligned")
                _require(segment.get("track_render_index") == index and segment.get("render_index") == index,
                         sl, "Stale render index")
                _require(segment.get("material_id") in materials, sl, "Missing primary material")
                refs = segment.get("extra_material_refs", [])
                _require(len(refs) == len(set(refs)), sl, "Duplicate extra material reference")
                _require(all(ref in materials for ref in refs), sl, "Missing extra material reference")
                material = materials[segment["material_id"]]
                kind = material.get("type")
                _require(kind in MEDIA | {"text", "subtitle"}, sl, "Unsupported primary material type")
                _require((kind in AUDIO) == (track.get("type") == "audio"), sl, "Material on incompatible track")
                children = [ref for ref in refs if ref in combinations]
                if children or (kind == "video" and not material.get("path")):
                    _require(len(children) == 1 and kind == "video" and not material.get("path"),
                             sl, "Compound wrapper needs exactly one combination and an empty-path video")
                    child = combinations[children[0]]["draft"]
                    source_start, source_length = _range(segment.get("source_timerange"), sl + "/source")
                    _require(source_start == 0 and source_length == length == child.get("duration") == material.get("duration"),
                             sl, "Unsupported trimmed compound wrapper or duration mismatch")
                    _require(not any(ref in mask_ids for ref in refs), sl, "Unsupported masked compound wrapper")
                    _identity(segment, material, [materials[r] for r in refs], sl)
                    used_combinations.add(children[0])
                elif kind in MEDIA:
                    asset(material.get("path"), sl + "/material")
                if kind in AUDIO | {"video"}:
                    source_start, source_length = _range(segment.get("source_timerange"), sl + "/source")
                    _require(_number(material.get("duration")) and source_start + source_length <= material["duration"] + 1000,
                             sl, "Source range exceeds media duration")
                masks = [materials[r] for r in refs if r in mask_ids]
                for group in segment.get("common_keyframes", []):
                    if group.get("property_type", "").startswith("KFTypeCommonMask"):
                        binding = group.get("material_id")
                        matches = [m for m in masks if m.get("constant_material_id") == binding]
                        _require(binding and len(matches) == 1 and binding != matches[0]["id"],
                                 sl, "Mask keyframe binding must use referenced common_mask.constant_material_id")
                report["segments"] += 1
        _require(used_combinations == set(combinations), location, "Unreferenced compound material")
        for mid, material in combinations.items():
            report["compound_count"] += 1
            visit(material["draft"], location + "/materials/drafts/" + mid)

    visit(draft, "draft")
    return report
