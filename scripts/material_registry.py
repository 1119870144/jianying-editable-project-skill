"""Keep local media registration and official font references consistent."""
import hashlib
import json
import time
import uuid
from pathlib import Path


def drafts(draft):
    yield draft
    for material in draft.get('materials', {}).get('drafts', []):
        if isinstance(material.get('draft'), dict):
            yield from drafts(material['draft'])


def local_media(draft):
    for child in drafts(draft):
        for category in ('videos', 'audios'):
            for material in child.get('materials', {}).get(category, []):
                if material.get('path') and material.get('type') in ('video', 'photo', 'music', 'audio', 'extract_music'):
                    # Platform music keeps its own resource registration.
                    if category == 'audios' and material.get('resource_id'):
                        continue
                    yield material


def register_local_media(draft, meta):
    """Register each used file by local_material_id; keep unrelated imports."""
    groups = meta.setdefault('draft_materials', [])
    group = next((g for g in groups if g.get('type') == 0), None)
    if group is None:
        group = {'type': 0, 'value': []}
        groups.append(group)
    entries = group.setdefault('value', [])
    root = Path(meta['draft_fold_path'])
    by_path = {}
    for entry in entries:
        if entry.get('file_Path'):
            path = Path(entry['file_Path'])
            path = path if path.is_absolute() else root / path
            by_path.setdefault(str(path.resolve()).casefold(), entry)
    identities = {}
    now = int(time.time())
    for material in local_media(draft):
        path = Path(material['path']).resolve()
        if not path.is_file():
            raise ValueError(f'Missing registered media: {path}')
        key = str(path).casefold()
        if key not in by_path:
            entry = {'id': str(uuid.uuid4()), 'file_Path': str(path), 'type': 0,
                     'metetype': 'music' if material['type'] in ('music', 'audio', 'extract_music') else material['type'],
                     'extra_info': path.name, 'duration': material.get('duration', 0),
                     'width': material.get('width', 0), 'height': material.get('height', 0),
                     'create_time': now, 'import_time': now, 'import_time_ms': now * 1_000_000,
                     'item_source': 1, 'enter_from': 0, 'md5': '', 'ai_group_type': '', 'material_color_tag': '',
                     'roughcut_time_range': {'start': 0, 'duration': material.get('duration', 0)},
                     'sub_time_range': {'start': -1, 'duration': -1}}
            entries.append(entry)
            by_path[key] = entry
        material['local_material_id'] = by_path[key]['id']
        material['unique_id'] = identities.setdefault(key, material.get('unique_id') or uuid.uuid4().hex)
        # Internal material_id is not the timeline's primary material reference.
        material['material_id'] = ''
    check_media_registry(draft, meta)
    return len(identities)


def check_media_registry(draft, meta):
    entries = [v for g in meta.get('draft_materials', []) if g.get('type') == 0 for v in g.get('value', [])]
    root = Path(meta['draft_fold_path'])
    for material in local_media(draft):
        matches = [v for v in entries if v.get('id') == material.get('local_material_id')]
        paths = {(root / v['file_Path']).resolve() for v in matches if v.get('file_Path')}
        if not material.get('local_material_id') or paths != {Path(material['path']).resolve()}:
            raise ValueError(f'Missing or conflicting media registration: {material.get("material_name", material["id"])}')
        if not material.get('unique_id'):
            raise ValueError('Missing media unique_id')


def align_official_fonts(draft):
    """Align only existing official font IDs with byte-identical font files."""
    changed, local = 0, set()
    for child in drafts(draft):
        for text in child.get('materials', {}).get('texts', []):
            resource = text.get('font_resource_id')
            content = json.loads(text['content'])
            if not resource:
                for style in content.get('styles', []):
                    if style.get('font', {}).get('path'):
                        local.add(style['font']['path'])
                continue
            font = next((f for f in text.get('fonts', []) if f.get('resource_id') == resource and f.get('path')), None)
            if font is None or not Path(font['path']).is_file():
                raise ValueError(f'Official font resource unavailable: {resource}')
            target = Path(font['path'])
            digest = hashlib.sha256(target.read_bytes()).digest()
            for style in content.get('styles', []):
                current = style.get('font', {})
                if current.get('id') != resource:
                    continue
                old = Path(current.get('path', ''))
                if not old.is_file() or hashlib.sha256(old.read_bytes()).digest() != digest:
                    raise ValueError(f'Font identity cannot be verified: {old}')
                if current['path'] != str(target):
                    current['path'] = str(target)
                    changed += 1
            text['font_path'] = str(target)
            text['content'] = json.dumps(content, ensure_ascii=False)
    return {'official_font_styles_aligned': changed, 'local_fonts_requiring_cloud_validation': sorted(local)}
