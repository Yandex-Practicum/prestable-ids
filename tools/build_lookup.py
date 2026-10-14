#!/usr/bin/env python3
"""Build the versioned static lesson lookup from legacy faculty JSON files."""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
UUID = re.compile(UUID_PATTERN + r'\Z')
FILENAME = re.compile(r'(.+)_(' + UUID_PATTERN + r')\.json\Z')
PREFIX = re.compile(r'[0-9a-f]{2}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
EXCLUDED_DIRECTORIES = {'.git', 'index', 'lookup', 'tools', 'tests'}
SHARD_PATH = 'lookup/v1/shards/'


def canonical_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def read_legacy(source):
    if not source.is_dir():
        raise ValueError(f'{source}: source must be a directory')
    lessons = defaultdict(lambda: defaultdict(set))
    track_slugs = {}
    for faculty in sorted(source.iterdir()):
        if not faculty.is_dir() or faculty.name in EXCLUDED_DIRECTORIES:
            continue
        if faculty.is_symlink():
            raise ValueError(f'{faculty}: source directory symlinks are not supported')
        for path in sorted(faculty.glob('*.json')):
            if path.is_symlink():
                raise ValueError(f'{path}: source file symlinks are not supported')
            if not path.is_file():
                continue
            match = FILENAME.fullmatch(path.name)
            if match is None:
                raise ValueError(f'{path}: expected <slug>_<track-UUID>.json')
            slug, filename_track = match.groups()
            try:
                data = json.loads(path.read_bytes())
            except (OSError, ValueError) as error:
                raise ValueError(f'{path}: {error}') from error
            if data == []:
                continue
            if not isinstance(data, dict) or set(data) != {'f', 'p', 'tr', 'items'}:
                raise ValueError(f'{path}: expected f, p, tr and items fields, or []')
            for key in ('f', 'p', 'tr'):
                if not isinstance(data[key], str) or UUID.fullmatch(data[key]) is None:
                    raise ValueError(f'{path}: {key} must be a lowercase UUID')
            if filename_track != data['tr']:
                raise ValueError(f'{path}: filename UUID does not match tr')
            if not isinstance(data['items'], list):
                raise ValueError(f'{path}: items must be an array')
            track = (data['f'], data['p'], data['tr'])
            track_slugs[track] = min(slug, track_slugs.get(track, slug))
            for position, item in enumerate(data['items']):
                if not isinstance(item, dict) or set(item) != {'c', 't', 'ls'}:
                    raise ValueError(f'{path}: items[{position}] must contain c, t and ls')
                for key in ('c', 't'):
                    if not isinstance(item[key], str) or UUID.fullmatch(item[key]) is None:
                        raise ValueError(f'{path}: items[{position}].{key} must be a lowercase UUID')
                if not isinstance(item['ls'], list):
                    raise ValueError(f'{path}: items[{position}].ls must be an array')
                route = (*track, item['c'], item['t'])
                for lesson in item['ls']:
                    if not isinstance(lesson, str) or UUID.fullmatch(lesson) is None:
                        raise ValueError(f'{path}: items[{position}].ls contains an invalid UUID')
                    lessons[lesson[:2]][lesson].add(route)
    return lessons, track_slugs


def make_shard(prefix, lesson_routes, track_slugs):
    track_keys = sorted({route[:3] for routes in lesson_routes.values() for route in routes})
    track_indexes = {track: index for index, track in enumerate(track_keys)}
    tracks = [[*track, track_slugs[track]] for track in track_keys]
    topic_keys = sorted({
        (track_indexes[route[:3]], route[3], route[4])
        for routes in lesson_routes.values() for route in routes
    })
    topic_indexes = {topic: index for index, topic in enumerate(topic_keys)}
    lessons = {
        lesson: sorted({topic_indexes[(track_indexes[route[:3]], route[3], route[4])] for route in routes})
        for lesson, routes in sorted(lesson_routes.items())
    }
    return canonical_json({'schema': 1, 'prefix': prefix, 'tracks': tracks, 'topics': topic_keys, 'lessons': lessons})


def make_lookup(source):
    lessons, track_slugs = read_legacy(source)
    payloads = {}
    shards = {}
    for prefix, lesson_routes in sorted(lessons.items()):
        payload = make_shard(prefix, lesson_routes, track_slugs)
        digest = hashlib.sha256(payload).hexdigest()
        filename = prefix + '-' + digest + '.idx'
        payloads[filename] = payload
        shards[prefix] = {'path': SHARD_PATH + filename, 'sha256': digest, 'lessonCount': len(lesson_routes)}
    version = hashlib.sha256(canonical_json({prefix: shard['sha256'] for prefix, shard in shards.items()})).hexdigest()
    manifest = {
        'schema': 1, 'version': version, 'prefixLength': 2,
        'lessonCount': sum(len(bucket) for bucket in lessons.values()),
        'routeCount': sum(len(routes) for bucket in lessons.values() for routes in bucket.values()),
        'shards': shards,
    }
    return manifest, payloads


def previous_owned_shards(output):
    try:
        manifest = json.loads((output / 'manifest.json').read_bytes())
    except (OSError, ValueError):
        return set()
    fields = {'schema', 'version', 'prefixLength', 'lessonCount', 'routeCount', 'shards'}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        return set()
    if type(manifest['schema']) is not int or manifest['schema'] != 1 or manifest['prefixLength'] != 2:
        return set()
    if not isinstance(manifest['version'], str) or SHA256.fullmatch(manifest['version']) is None:
        return set()
    if any(type(manifest[key]) is not int or manifest[key] < 0 for key in ('lessonCount', 'routeCount')):
        return set()
    if manifest['routeCount'] < manifest['lessonCount'] or not isinstance(manifest['shards'], dict):
        return set()
    owned = set()
    lesson_count = 0
    for prefix, shard in manifest['shards'].items():
        if not isinstance(prefix, str) or PREFIX.fullmatch(prefix) is None or not isinstance(shard, dict):
            return set()
        if set(shard) != {'path', 'sha256', 'lessonCount'}:
            return set()
        digest = shard.get('sha256')
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            return set()
        if type(shard['lessonCount']) is not int or shard['lessonCount'] <= 0:
            return set()
        filename = prefix + '-' + digest + '.idx'
        if shard['path'] != SHARD_PATH + filename:
            return set()
        lesson_count += shard['lessonCount']
        owned.add(filename)
    version = hashlib.sha256(canonical_json({prefix: shard['sha256'] for prefix, shard in manifest['shards'].items()})).hexdigest()
    if lesson_count != manifest['lessonCount'] or version != manifest['version']:
        return set()
    if not owned and manifest['routeCount'] != 0:
        return set()
    return owned


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == payload:
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.lookup-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build(source, output):
    # Validate and prepare every shard before changing the published manifest.
    manifest, payloads = make_lookup(source)
    owned = previous_owned_shards(output)
    for filename, payload in payloads.items():
        write_atomic(output / 'shards' / filename, payload)
    write_atomic(output / 'manifest.json', canonical_json(manifest))
    for filename in owned - payloads.keys():
        path = output / 'shards' / filename
        digest = filename[3:-4]
        if path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            path.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = build(args.source, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f'build lookup: {error}\n')
    print(json.dumps({key: manifest[key] for key in ('version', 'lessonCount', 'routeCount')}
                     | {'shardCount': len(manifest['shards'])}, sort_keys=True))


if __name__ == '__main__':
    main()
