import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BUILDER = Path(__file__).resolve().parents[1] / 'tools' / 'build_lookup.py'
FACULTY = '11111111-1111-4111-8111-111111111111'
PROFESSION = '22222222-2222-4222-8222-222222222222'
TRACK = '33333333-3333-4333-8333-333333333333'
COURSE = '44444444-4444-4444-8444-444444444444'
TOPIC = '55555555-5555-4555-8555-555555555555'
LESSON = 'ab666666-6666-4666-8666-666666666666'
OTHER_TOPIC = '77777777-7777-4777-8777-777777777777'


class BuildLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.output = self.source / 'lookup' / 'v1'

    def write_legacy(self, data, slug='react', track=TRACK, directory='Web'):
        path = self.source / directory / (slug + '_' + track + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        return path

    def legacy(self, items=None):
        return {'f': FACULTY, 'p': PROFESSION, 'tr': TRACK, 'items': items if items is not None else [
            {'c': COURSE, 't': TOPIC, 'ls': [LESSON]}
        ]}

    def build(self):
        result = subprocess.run(
            [sys.executable, str(BUILDER), '--source', str(self.source), '--output', str(self.output)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.output / 'manifest.json').read_bytes())

    def shard(self, manifest, prefix='ab'):
        entry = manifest['shards'][prefix]
        path = self.source / entry['path']
        data = path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
        self.assertEqual(path.name, prefix + '-' + entry['sha256'] + '.idx')
        return json.loads(data)

    @staticmethod
    def decode(shard, lesson):
        result = []
        for topic_index in shard['lessons'][lesson]:
            track_index, course, topic = shard['topics'][topic_index]
            faculty, profession, track, slug = shard['tracks'][track_index]
            result.append((faculty, profession, track, course, topic, lesson, slug))
        return result

    def test_single_lesson_decodes_to_literal_full_route(self):
        # Dropping a route component or referencing the wrong table must fail.
        self.write_legacy(self.legacy())
        manifest = self.build()
        self.assertEqual(manifest['schema'], 1)
        self.assertEqual(manifest['prefixLength'], 2)
        self.assertEqual(manifest['lessonCount'], 1)
        self.assertEqual(manifest['routeCount'], 1)
        self.assertRegex(manifest['version'], r'^[0-9a-f]{64}$')
        self.assertEqual(set(manifest['shards']), {'ab'})
        shard = self.shard(manifest)
        self.assertEqual(shard['schema'], 1)
        self.assertEqual(shard['prefix'], 'ab')
        self.assertEqual(shard['lessons'][LESSON], [0])
        self.assertEqual(self.decode(shard, LESSON), [(
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            '33333333-3333-4333-8333-333333333333',
            '44444444-4444-4444-8444-444444444444',
            '55555555-5555-4555-8555-555555555555',
            'ab666666-6666-4666-8666-666666666666',
            'react',
        )])
        self.assertNotIn(LESSON, json.dumps(manifest))
        self.assertEqual(list(self.output.glob('shards/*.json')), [])

    def test_shared_lesson_preserves_two_routes_and_deduplicates_identical_route(self):
        # A scalar lesson mapping or counting duplicate input as a route must fail.
        self.write_legacy(self.legacy([
            {'c': COURSE, 't': OTHER_TOPIC, 'ls': [LESSON]},
            {'c': COURSE, 't': TOPIC, 'ls': [LESSON, LESSON]},
        ]))
        manifest = self.build()
        self.assertEqual(manifest['lessonCount'], 1)
        self.assertEqual(manifest['routeCount'], 2)
        decoded = self.decode(self.shard(manifest), LESSON)
        self.assertEqual([route[4] for route in decoded], [
            '55555555-5555-4555-8555-555555555555',
            '77777777-7777-4777-8777-777777777777',
        ])
        self.assertTrue(all(route[:4] == (FACULTY, PROFESSION, TRACK, COURSE) for route in decoded))

    def test_empty_legacy_shapes_produce_an_empty_manifest(self):
        # Treating valid legacy placeholders as malformed input must fail.
        self.write_legacy([], slug='placeholder')
        self.write_legacy(self.legacy([]), slug='empty-items')
        self.write_legacy(self.legacy([{'c': COURSE, 't': TOPIC, 'ls': []}]), slug='empty-lessons')
        manifest = self.build()
        self.assertEqual(manifest['lessonCount'], 0)
        self.assertEqual(manifest['routeCount'], 0)
        self.assertEqual(manifest['shards'], {})

    def test_shared_id_can_point_to_distinct_tracks(self):
        # Reusing a track table index across distinct routes must fail.
        self.write_legacy(self.legacy())
        other = {
            'f': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'p': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            'tr': '88888888-8888-4888-8888-888888888888',
            'items': [{'c': '99999999-9999-4999-8999-999999999999', 't': OTHER_TOPIC, 'ls': [LESSON]}],
        }
        self.write_legacy(other, slug='other', track=other['tr'])
        manifest = self.build()
        self.assertEqual(manifest['routeCount'], 2)
        decoded = self.decode(self.shard(manifest), LESSON)
        self.assertEqual(decoded, [
            (FACULTY, PROFESSION, TRACK, COURSE, TOPIC, LESSON, 'react'),
            ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
             '88888888-8888-4888-8888-888888888888', '99999999-9999-4999-8999-999999999999',
             OTHER_TOPIC, LESSON, 'other'),
        ])

    def test_identical_routes_in_alias_files_are_deduplicated(self):
        # An alias filename must not create another six-ID route.
        self.write_legacy(self.legacy(), slug='z-alias')
        self.write_legacy(self.legacy(), slug='a-alias')
        manifest = self.build()
        shard = self.shard(manifest)
        self.assertEqual(manifest['routeCount'], 1)
        self.assertEqual(len(shard['tracks']), 1)
        self.assertEqual(self.decode(shard, LESSON), [
            (FACULTY, PROFESSION, TRACK, COURSE, TOPIC, LESSON, 'a-alias')
        ])

    def test_only_immediate_legacy_faculty_json_files_are_read(self):
        # Reading generated/test data or deeper fixture directories must fail.
        self.write_legacy(self.legacy())
        for reserved in ['.git', 'index', 'lookup', 'tools', 'tests']:
            directory = self.source / reserved
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'invalid.json').write_text('{not legacy json')
        nested = self.source / 'Web' / 'nested'
        nested.mkdir()
        (nested / 'invalid.json').write_text('{not legacy json')
        manifest = self.build()
        self.assertEqual(manifest['lessonCount'], 1)

    def test_build_is_deterministic_and_preserves_legacy_bytes(self):
        # Filesystem/input order or rebuilding must not alter lookup bytes.
        data = self.legacy([
            {'c': COURSE, 't': OTHER_TOPIC, 'ls': [LESSON]},
            {'c': COURSE, 't': TOPIC, 'ls': [LESSON]},
        ])
        path = self.write_legacy(data)
        original = path.read_bytes()
        self.build()
        first = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(path.read_bytes(), original)
        data['items'].reverse()
        path.write_text(json.dumps(data, sort_keys=True))
        rewritten = path.read_bytes()
        self.build()
        second = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), rewritten)

    def test_invalid_input_does_not_replace_the_existing_index(self):
        # Accepting malformed input or publishing a partial build must fail.
        path = self.write_legacy(self.legacy())
        self.build()
        original = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        invalid = [
            ('bad lesson UUID', self.legacy([{'c': COURSE, 't': TOPIC, 'ls': ['not-a-uuid']}])),
            ('bad faculty UUID', {**self.legacy(), 'f': 'not-a-uuid'}),
            ('filename track mismatch', {**self.legacy(), 'tr': '88888888-8888-4888-8888-888888888888'}),
            ('extra top-level key', {**self.legacy(), 'unexpected': 1}),
            ('nonempty array', [self.legacy()]),
            ('items not array', {**self.legacy(), 'items': {}}),
            ('lessons not array', self.legacy([{'c': COURSE, 't': TOPIC, 'ls': LESSON}])),
            ('bad course UUID', self.legacy([{'c': 'bad', 't': TOPIC, 'ls': [LESSON]}])),
            ('bad topic UUID', self.legacy([{'c': COURSE, 't': 'bad', 'ls': [LESSON]}])),
            ('extra item key', self.legacy([{'c': COURSE, 't': TOPIC, 'ls': [LESSON], 'unexpected': 1}])),
        ]
        for label, data in invalid:
            with self.subTest(label=label):
                path.write_text(json.dumps(data))
                result = subprocess.run(
                    [sys.executable, str(BUILDER), '--source', str(self.source), '--output', str(self.output)],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(path.name, result.stderr)
                current = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
                self.assertEqual(original, current)

    def test_invalid_filename_is_rejected(self):
        # Silently skipping a malformed source filename must fail.
        path = self.write_legacy(self.legacy())
        self.build()
        invalid = path.with_name('broken.json')
        path.rename(invalid)
        result = subprocess.run(
            [sys.executable, str(BUILDER), '--source', str(self.source), '--output', str(self.output)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken.json', result.stderr)

    def test_rebuild_removes_only_previously_manifest_owned_obsolete_shards(self):
        # Leaving old owned shards or deleting unrelated files must fail.
        path = self.write_legacy(self.legacy())
        first = self.build()
        old_shard = self.source / first['shards']['ab']['path']
        unrelated = self.output / 'shards' / ('ff-' + '0' * 64 + '.idx')
        unrelated.write_bytes(b'unrelated file')
        note = self.output / 'shards' / 'keep.txt'
        note.write_bytes(b'keep this too')
        path.write_text(json.dumps(self.legacy([
            {'c': COURSE, 't': TOPIC, 'ls': ['cd666666-6666-4666-8666-666666666666']}
        ])))
        second = self.build()
        self.assertNotEqual(first['version'], second['version'])
        self.assertEqual(set(second['shards']), {'cd'})
        self.assertFalse(old_shard.exists())
        self.assertEqual(unrelated.read_bytes(), b'unrelated file')
        self.assertEqual(note.read_bytes(), b'keep this too')

    def test_incomplete_previous_manifest_cannot_claim_unrelated_shard_ownership(self):
        # A corrupt manifest must not authorize deleting an unrelated file.
        self.write_legacy(self.legacy())
        self.build()
        name = 'ff-' + '0' * 64 + '.idx'
        unrelated = self.output / 'shards' / name
        unrelated.write_bytes(b'unrelated file')
        (self.output / 'manifest.json').write_text(json.dumps({
            'schema': 1,
            'shards': {'ff': {'path': 'lookup/v1/shards/' + name, 'sha256': '0' * 64, 'lessonCount': 1}},
        }))
        self.build()
        self.assertTrue(unrelated.exists())
        self.assertEqual(unrelated.read_bytes(), b'unrelated file')

    def test_obsolete_shard_modified_after_manifest_is_preserved(self):
        # The old manifest must not authorize deleting manually replaced bytes.
        path = self.write_legacy(self.legacy())
        first = self.build()
        replaced = self.source / first['shards']['ab']['path']
        replaced.write_bytes(b'manually replaced file')
        path.write_text(json.dumps(self.legacy([
            {'c': COURSE, 't': TOPIC, 'ls': ['cd666666-6666-4666-8666-666666666666']}
        ])))
        self.build()
        self.assertTrue(replaced.exists())
        self.assertEqual(replaced.read_bytes(), b'manually replaced file')

    def test_source_symlinks_are_rejected(self):
        # A source-looking link must not silently read outside the source root.
        self.write_legacy(self.legacy())
        self.build()
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / ('other_' + TRACK + '.json')
            target.write_text(json.dumps(self.legacy()))
            link = self.source / 'Web' / ('linked_' + TRACK + '.json')
            link.symlink_to(target)
            result = subprocess.run(
                [sys.executable, str(BUILDER), '--source', str(self.source), '--output', str(self.output)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(link.name, result.stderr)


if __name__ == '__main__':
    unittest.main()
