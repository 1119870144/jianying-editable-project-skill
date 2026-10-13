import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from material_registry import register_local_media, check_media_registry, align_official_fonts


class MaterialRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'person.mp4'
        self.media.write_bytes(b'file existence fixture')
        self.material = {'id': 'timeline-media', 'type': 'video', 'path': str(self.media), 'duration': 1_000_000}
        self.draft = {'materials': {'videos': [self.material]}}
        self.meta = {'draft_fold_path': str(self.root), 'draft_materials': []}

    def test_missing_registration_is_reproduced_and_fixed(self):
        with self.assertRaisesRegex(ValueError, 'registration'):
            check_media_registry(self.draft, self.meta)
        register_local_media(self.draft, self.meta)
        check_media_registry(self.draft, self.meta)
        self.assertEqual(self.material['id'], 'timeline-media')
        self.assertEqual(self.material['local_material_id'], self.meta['draft_materials'][0]['value'][0]['id'])

    def test_nested_reuse_gets_one_registration_and_conflicts_fail(self):
        nested = copy.deepcopy(self.material)
        self.draft['materials']['drafts'] = [{'draft': {'materials': {'videos': [nested]}}}]
        register_local_media(self.draft, self.meta)
        self.assertEqual(self.material['local_material_id'], nested['local_material_id'])
        self.assertEqual(len(self.meta['draft_materials'][0]['value']), 1)
        self.meta['draft_materials'][0]['value'][0]['file_Path'] = str(self.root / 'different.mp4')
        with self.assertRaisesRegex(ValueError, 'registration'):
            check_media_registry(self.draft, self.meta)

    def test_local_audio_music_id_is_not_a_platform_resource(self):
        audio = {'id': 'local-audio', 'type': 'music', 'music_id': 'local-audio', 'path': str(self.media)}
        platform = {'id': 'platform', 'type': 'music', 'resource_id': '123', 'path': 'platform-managed.mp3'}
        self.draft['materials']['audios'] = [audio, platform]
        register_local_media(self.draft, self.meta)
        self.assertTrue(audio['unique_id'])
        self.assertNotIn('local_material_id', platform)
        check_media_registry(self.draft, self.meta)

    def test_font_alignment_preserves_style_and_rejects_different_font(self):
        original, cached = self.root / 'font.ttf', self.root / 'cached.ttf'
        original.write_bytes(b'same font'); cached.write_bytes(b'same font')
        content = {'text': '标题', 'styles': [{'size': 12, 'color': [1, 1, 0], 'font': {'id': '123', 'path': str(original)}}]}
        text = {'font_resource_id': '123', 'content': json.dumps(content), 'fonts': [{'resource_id': '123', 'path': str(cached)}]}
        self.draft['materials']['texts'] = [text]
        result = align_official_fonts(self.draft)
        self.assertEqual(result['official_font_styles_aligned'], 1)
        expected = copy.deepcopy(content); expected['styles'][0]['font']['path'] = str(cached)
        self.assertEqual(json.loads(text['content']), expected)
        text['content'] = json.dumps(content); cached.write_bytes(b'another font')
        with self.assertRaisesRegex(ValueError, 'identity'):
            align_official_fonts(self.draft)


if __name__ == '__main__':
    unittest.main()
