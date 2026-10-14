"""Validate native keyframes and repair partial geometric keyframe groups.

Native clips with geometric animation must anchor both position axes. Preserve
existing curves, scale mode and masks; alpha-only and static clips need no fix.
Times are source microseconds for media, and local microseconds for text.
"""

import copy
import math
import uuid


GEOMETRY = {"KFTypePositionX", "KFTypePositionY", "KFTypeScaleX", "KFTypeScaleY", "KFTypeRotation"}
POSITION = {"KFTypePositionX", "KFTypePositionY"}
TEXT = {"text", "subtitle"}


def _walk(draft, path=""):
    yield draft, path
    for index, material in enumerate(draft.get("materials", {}).get("drafts", [])):
        if isinstance(material.get("draft"), dict):
            yield from _walk(material["draft"], f"{path}/materials/drafts/{index}/draft")


def _segments(draft, path):
    kinds = {m["id"]: m.get("type") for rows in draft.get("materials", {}).values()
             if isinstance(rows, list) for m in rows if isinstance(m, dict) and "id" in m}
    for ti, track in enumerate(draft.get("tracks", [])):
        for si, segment in enumerate(track.get("segments", [])):
            yield segment, kinds.get(segment.get("material_id")), f"{path}/tracks/{ti}/segments/{si}"


def _require(condition, path, message):
    if not condition:
        raise ValueError(f"{path}: {message}")


def _finite(value, path):
    _require(isinstance(value, (int, float)) and not isinstance(value, bool)
             and math.isfinite(value), path, "expected a finite number")


def _range(value, path):
    _require(isinstance(value, dict), path, "missing time range")
    start, duration = value.get("start", 0), value.get("duration")
    for key, number in (("start", start), ("duration", duration)):
        _finite(number, f"{path}/{key}")
        _require(isinstance(number, int), f"{path}/{key}", "expected integer microseconds")
    _require(start >= 0 and duration > 0, path, "invalid time range")
    return start, duration


def _clock(segment, kind, path):
    _, duration = _range(segment.get("target_timerange"), f"{path}/target_timerange")
    speed = segment.get("speed", 1.0)
    _finite(speed, f"{path}/speed")
    _require(speed > 0, f"{path}/speed", "speed must be positive")
    source = segment.get("source_timerange")
    if kind in TEXT or source is None:
        return 0, duration
    start, duration = _range(source, f"{path}/source_timerange")
    return start, start + duration


def _values(clip):
    position, scale = clip.get("transform") or {}, clip.get("scale") or {}
    return {"KFTypePositionX": position.get("x", 0.0), "KFTypePositionY": position.get("y", 0.0),
            "KFTypeScaleX": scale.get("x", 1.0), "KFTypeScaleY": scale.get("y", 1.0),
            "KFTypeRotation": clip.get("rotation", 0.0)}


def _validate(draft, allow_partial=False):
    report = {"drafts": 0, "segments": 0, "keyframe_groups": 0, "keyframes": 0, "geometry_segments": 0}
    for node, path in _walk(draft):
        report["drafts"] += 1
        for segment, kind, location in _segments(node, path):
            report["segments"] += 1
            clip = segment.get("clip")
            if clip:
                for key, value in {**_values(clip), "alpha": clip.get("alpha", 1.0)}.items():
                    _finite(value, f"{location}/clip/{key}")
            groups = segment.get("common_keyframes", [])
            if not groups:
                continue
            start, end = _clock(segment, kind, location)
            seen, geometry = set(), set()
            for gi, group in enumerate(groups):
                gp = f"{location}/common_keyframes/{gi}"
                prop = group.get("property_type")
                _require(isinstance(prop, str) and bool(prop), gp, "missing property_type")
                binding = group.get("material_id", "")
                _require(isinstance(binding, str), gp, "invalid material_id")
                identity = (binding, prop)
                _require(identity not in seen, gp, f"duplicate property {prop} for material {binding!r}")
                seen.add(identity)
                if not binding and prop in GEOMETRY:
                    geometry.add(prop)
                points = group.get("keyframe_list")
                _require(isinstance(points, list) and bool(points), gp, "empty keyframe group")
                previous = None
                for pi, point in enumerate(points):
                    pp = f"{gp}/keyframe_list/{pi}"
                    time = point.get("time_offset")
                    _finite(time, f"{pp}/time_offset")
                    _require(isinstance(time, int), pp, "expected integer keyframe microseconds")
                    _require(previous is None or time > previous, pp, "duplicate or unsorted keyframe time")
                    _require(start <= time <= end, pp, f"keyframe time outside source range [{start}, {end}]")
                    previous = time
                    values = point.get("values")
                    _require(isinstance(values, list) and bool(values), pp, "missing keyframe values")
                    for vi, value in enumerate(values):
                        _finite(value, f"{pp}/values/{vi}")
                    if prop in GEOMETRY:
                        _require(len(values) == 1, pp, "geometry keyframes need one scalar value")
                    report["keyframes"] += 1
                report["keyframe_groups"] += 1
            if geometry:
                _require(isinstance(clip, dict), location, "geometry keyframes require clip settings")
                report["geometry_segments"] += 1
                _require(allow_partial or POSITION <= geometry, location, "partial geometry: missing PositionX or PositionY")
    report["geometry_verified"] = True
    return report


def validate_geometry(draft):
    """Return counts or raise ValueError with a JSON path; never mutate input.

    Check every common keyframe, including alpha and mask values. Mask material
    binding is a separate validation concern. Endpoints are inclusive; offsets
    must already use the source clock (source_start + local_time * speed).
    """
    return _validate(draft)


def _anchor(prop, start, value):
    return {"id": uuid.uuid4().hex, "material_id": "", "property_type": prop,
            "keyframe_list": [{"id": uuid.uuid4().hex, "time_offset": start, "values": [value],
                               "curveType": "Line", "graphID": "", "string_value": "",
                               "left_control": {"x": 0.0, "y": 0.0},
                               "right_control": {"x": 0.0, "y": 0.0}}]}


def normalize_geometry(draft):
    """Return (deep copy, changes); only complete geometric groups missing X/Y.

    Do not alter existing keys, uniform_scale, source times or Y signs. Recursively
    handle materials.drafts[].draft without adding animation to static wrappers.
    Reject malformed data instead of guessing how its existing animation works.
    """
    _validate(draft, allow_partial=True)
    result = copy.deepcopy(draft)
    report = {"segments": [], "anchors_added": 0}
    for node, path in _walk(result):
        for segment, kind, location in _segments(node, path):
            groups = segment.get("common_keyframes", [])
            existing = {g["property_type"] for g in groups if not g.get("material_id")}
            if not existing & GEOMETRY or POSITION <= existing:
                continue
            start, _ = _clock(segment, kind, location)
            values = _values(segment["clip"])
            uniform = (segment.get("uniform_scale") or {}).get("on")
            if uniform and values["KFTypeScaleX"] == values["KFTypeScaleY"]:
                values.pop("KFTypeScaleY")
            added = [prop for prop in values if prop not in existing]
            groups.extend(_anchor(prop, start, values[prop]) for prop in added)
            report["anchors_added"] += len(added)
            report["segments"].append({"id": segment.get("id"), "kind": kind, "path": location,
                                       "target_start": segment["target_timerange"]["start"],
                                       "source_start": start, "missing_properties": added})
    report["segments_normalized"] = len(report["segments"])
    report["validation"] = validate_geometry(result)
    return result, report
