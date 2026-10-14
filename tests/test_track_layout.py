import copy
import sys
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from track_layout import compact_tracks


def track(role, ident, start, end):
    item = {"id": "track-" + ident, "type": "mixed", "segments": [
        {"id": ident, "material_id": "media-" + ident,
         "target_timerange": {"start": start, "duration": end - start},
         "source_timerange": {"start": 200, "duration": end - start},
         "clip": {"transform": {"x": 0.2, "y": -0.3}},
         "common_keyframes": [{"property_type": "KFTypePositionX",
                               "keyframe_list": [{"time_offset": 200, "values": [0.2]}]}]}]}
    if role is not None:
        item["role"] = role
    return item


def layout(tracks):
    return [[s["id"] for s in t["segments"]] for t in tracks]


class TrackLayoutTests(unittest.TestCase):
    def assert_invariants(self, original, result):
        visual = [t for t in original if t["type"] != "audio"]
        old = [s for t in visual for s in t["segments"]]
        new = [s for t in result if t["type"] != "audio" for s in t["segments"]]
        self.assertEqual(sorted(old, key=lambda s: s["id"]), sorted(new, key=lambda s: s["id"]))
        positions = {s["id"]: i for i, t in enumerate(result) for s in t["segments"]}
        for i, a in enumerate(old):
            ar = a["target_timerange"]
            for b in old[i + 1:]:
                br = b["target_timerange"]
                if max(ar["start"], br["start"]) < min(ar["start"] + ar["duration"], br["start"] + br["duration"]):
                    self.assertLess(positions[a["id"]], positions[b["id"]])
        for t in result:
            if t["type"] == "audio":
                continue
            self.assertNotIn("role", t)
            ranges = [s["target_timerange"] for s in t["segments"]]
            for a, b in zip(ranges, ranges[1:]):
                self.assertLessEqual(a["start"] + a["duration"], b["start"])

    def test_roles_merge_and_protect_native_content_and_audio(self):
        tracks = [track("background", "bg", 0, 20), track("person", "p1", 0, 4),
                  track("subtitle", "s1", 0, 4), track("auxiliary", "a", 4, 8),
                  track("person", "p2", 4, 8), track("subtitle", "s2", 4, 8)]
        audio = {"id": "audio", "type": "audio", "name": "Original", "segments": [], "flag": 0}
        tracks.insert(2, audio)
        before = copy.deepcopy(tracks)
        result = compact_tracks(tracks)
        self.assertEqual(tracks, before)
        self.assertIs(result[-1], audio)
        self.assertEqual(layout(result), [["bg"], ["a"], ["p1", "p2"], ["s1", "s2"], []])
        self.assertEqual([t["name"] for t in result[:-1]], ["背景", "辅助素材", "人物", "字幕"])
        self.assert_invariants(before, result)

    def test_global_order_can_move_unrelated_lanes_to_merge_subtitles(self):
        tracks = [track("subtitle", "s1", 0, 5), track("person", "p", 5, 10),
                  track("subtitle", "s2", 5, 10)]
        result = compact_tracks(tracks)
        self.assertEqual(layout(result), [["p"], ["s1", "s2"]])
        self.assert_invariants(tracks, result)

    def test_nonoverlap_role_merge_that_would_create_cycle_is_rejected(self):
        tracks = [track("person", "low", 0, 5), track("auxiliary", "middle", 0, 10),
                  track("person", "high", 5, 10)]
        with self.assertWarnsRegex(UserWarning, "2 person tracks.*z-order"):
            result = compact_tracks(tracks)
        self.assertEqual(layout(result), [["low"], ["middle"], ["high"]])
        self.assert_invariants(tracks, result)

    def test_overlapping_same_role_requires_separate_lanes_even_with_bounds(self):
        tracks = [track("person", "a", 0, 10), track("person", "b", 2, 4)]
        tracks[0]["segments"][0]["bounds"] = [0, 0, 10, 10]
        tracks[1]["segments"][0]["bounds"] = [100, 100, 10, 10]
        with self.assertWarnsRegex(UserWarning, "overlap"):
            result = compact_tracks(tracks)
        self.assertEqual(len(result), 2)
        self.assert_invariants(tracks, result)

    def test_different_roles_never_share_a_lane_even_when_disjoint(self):
        tracks = [track("background", "b", 0, 1), track("person", "p", 1, 2),
                  track("subtitle", "s", 2, 3), track(None, "other", 3, 4)]
        result = compact_tracks(tracks)
        self.assertEqual(len(result), 4)
        self.assert_invariants(tracks, result)

    def test_no_roles_retains_legacy_placement(self):
        tracks = [track(None, str(i), a, b)
                  for i, (a, b) in enumerate(((0, 8), (0, 2), (2, 4), (1, 3), (5, 7)))]
        result = compact_tracks(tracks)
        self.assertEqual(layout(result), [["0"], ["1", "2", "4"], ["3"]])
        self.assertEqual([t["name"] for t in result], ["Visual 1", "Visual 2", "Visual 3"])
        self.assert_invariants(tracks, result)

    def test_empty_and_audio_only_inputs_and_unknown_roles(self):
        self.assertEqual(compact_tracks([]), [])
        audio = {"type": "audio", "segments": [], "role": "original"}
        self.assertIs(compact_tracks([audio])[0], audio)
        with self.assertRaisesRegex(ValueError, "Unsupported track role"):
            compact_tracks([track("guessed", "a", 0, 1)])

    def test_multi_segment_input_is_not_mutated_and_untagged_is_auxiliary(self):
        a = track("auxiliary", "a", 0, 1)
        a["segments"].append(track(None, "b", 2, 3)["segments"][0])
        tracks = [a, track(None, "c", 1, 2)]
        before = copy.deepcopy(tracks)
        with warnings.catch_warnings(record=True) as messages:
            result = compact_tracks(tracks)
        self.assertEqual(messages, [])
        self.assertEqual(layout(result), [["a", "c", "b"]])
        self.assertEqual(tracks, before)
        self.assert_invariants(tracks, result)


if __name__ == "__main__":
    unittest.main()
