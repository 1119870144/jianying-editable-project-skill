"""Compact new visual tracks without changing concurrent stacking or clip data."""
import heapq
import uuid
import warnings
from collections import Counter


NAMES = {"background": "背景", "person": "人物", "subtitle": "字幕", "auxiliary": "辅助素材"}


def _overlaps(a, b):
    a, b = a["target_timerange"], b["target_timerange"]
    return max(a.get("start", 0), b.get("start", 0)) < min(
        a.get("start", 0) + a["duration"], b.get("start", 0) + b["duration"])


def _track(name, segments):
    return {"id": str(uuid.uuid4()).upper(), "type": "mixed", "name": name,
            "is_default_name": False,
            "segments": sorted(segments, key=lambda s: s["target_timerange"].get("start", 0))}


def _legacy(tracks):
    placed, lanes = [], []
    for track in tracks:
        for segment in track.get("segments", []):
            lane = max((z + 1 for other, z in placed if _overlaps(segment, other)), default=0)
            while len(lanes) <= lane:
                lanes.append([])
            lanes[lane].append(segment)
            placed.append((segment, lane))
    return [_track(f"Visual {i + 1}", segments) for i, segments in enumerate(lanes)]


def _order(groups, edges):
    """Topologically order merged lanes; a contraction cycle forbids the merge."""
    owner = {node: i for i, group in enumerate(groups) for node in group}
    outgoing = {i: set() for i, group in enumerate(groups) if group}
    indegree = Counter()
    for a, b in edges:
        a, b = owner[a], owner[b]
        if a == b:
            return None
        if b not in outgoing[a]:
            outgoing[a].add(b)
            indegree[b] += 1
    ready = [i for i in outgoing if not indegree[i]]
    heapq.heapify(ready)
    ordered = []
    while ready:
        i = heapq.heappop(ready)
        ordered.append(i)
        for j in outgoing[i]:
            indegree[j] -= 1
            if not indegree[j]:
                heapq.heappush(ready, j)
    return ordered if len(ordered) == len(outgoing) else None


def compact_tracks(tracks):
    """Use optional manifest roles while preserving every temporal overlap order.

    With no visual role, retain the old compaction layout. Otherwise untagged
    clips are auxiliary; different roles never share a lane. Same-role lanes
    merge greedily only when non-overlapping and their constraint graph stays
    acyclic. This is conservative, not a minimum-track optimizer. Screen bounds
    are deliberately unused. Warnings report roles requiring multiple lanes.
    Output has semantic names, no private role fields, and untouched segments.
    Audio tracks retain their objects and relative order, appended as before.
    """
    visual = [t for t in tracks if t["type"] != "audio"]
    audio = [t for t in tracks if t["type"] == "audio"]
    if not any(t.get("role") is not None for t in visual):
        return _legacy(visual) + audio
    nodes = []
    for track in visual:
        role = track.get("role")
        role = "auxiliary" if role is None else role
        if role not in NAMES:
            raise ValueError(f"Unsupported track role: {role}")
        nodes.extend((role, s) for s in track.get("segments", []))
    # Input track order is the original z-order; never infer spatial disjointness.
    edges = [(i, j) for i, (_, a) in enumerate(nodes)
             for j in range(i + 1, len(nodes)) if _overlaps(a, nodes[j][1])]
    groups = [[i] for i in range(len(nodes))]
    for i in range(len(groups)):
        if not groups[i]:
            continue
        for j in range(i + 1, len(groups)):
            if not groups[j] or nodes[groups[i][0]][0] != nodes[groups[j][0]][0]:
                continue
            if any(_overlaps(nodes[a][1], nodes[b][1]) for a in groups[i] for b in groups[j]):
                continue
            old = groups[j]
            groups[i] += old
            groups[j] = []
            if _order(groups, edges) is None:
                groups[i] = groups[i][:-len(old)]
                groups[j] = old
    ordered = _order(groups, edges)
    counts = Counter(nodes[groups[i][0]][0] for i in ordered)
    for role, count in counts.items():
        if count > 1:
            warnings.warn(f"Kept {count} {role} tracks: overlap or z-order conflicts prevent merging.",
                          UserWarning, stacklevel=2)
    seen, result = Counter(), []
    for i in ordered:
        role = nodes[groups[i][0]][0]
        seen[role] += 1
        name = NAMES[role] + (f" {seen[role]}" if counts[role] > 1 else "")
        result.append(_track(name, [nodes[n][1] for n in groups[i]]))
    return result + audio
