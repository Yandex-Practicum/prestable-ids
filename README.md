# Practicum admin lesson mappings

Legacy data stays in `<faculty>/<slug>_<track-UUID>.json`:

```json
{"f":"faculty UUID","p":"profession UUID","tr":"track UUID","items":[{"c":"course UUID","t":"topic UUID","ls":["lesson UUID"]}]}
```

The initial static lookup covers all 470,288 known lesson IDs, including the
61,106 routes verified against the current local export. Retained historical
records are not evidence of live admin availability.

## Build and validate the static lookup

Run these after changing legacy JSON data, before publishing the dataset:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 tools/build_lookup.py --source . --output lookup/v1
```

No dependencies are required. Repeated builds from identical data produce
identical bytes. The generator reads only immediate faculty JSON files, rejects
invalid data and never edits those inputs. An invalid source leaves the previous
manifest intact. New shards are written before the manifest is replaced; cleanup
is limited to unchanged old shards owned by a validated previous manifest.

## Public lookup contract

`lookup/v1/manifest.json` contains schema/version, counts and shard descriptors.
A lesson uses the first two hexadecimal characters of its UUID as its prefix.
Each descriptor names `lookup/v1/shards/<prefix>-<SHA-256>.idx` and gives its
exact-byte SHA-256 and unique lesson count.

Each shard contains JSON with:

- `schema: 1` and its `prefix`;
- `tracks`: rows `[faculty UUID, profession UUID, track UUID, slug]`;
- `topics`: rows `[track index, course UUID, topic UUID]`;
- `lessons`: full lesson UUID to an array of topic indexes.

A shard contains everything needed to reconstruct its lesson routes. Multiple
distinct routes are preserved; identical six-ID routes are deduplicated. Where
identical track IDs have filename aliases, the lexicographically first slug is
used. The manifest version hashes the canonical prefix-to-shard-hash mapping.

Shards deliberately use `.idx`, so older extension searches restricted to
`extension:json` do not mistake them for legacy mappings.

Publish the manifest and its generated shards together. A new client may still
hold an old manifest; it refreshes once if an old shard has been removed. The
existing legacy JSON consumers remain compatible.
