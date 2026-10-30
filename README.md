# release-hashes

File hashes for every published Dirigible Studio release. WordPress sites
running the Dirigible theme compare an update with these before installing
it, and re-check their installed copies in the site report.

- `<slug>/<version>.json`: one file per release, written once and never
  changed.
- `products.json`: the repositories watched, each with its install slug.
- `bin/hash-release`: the hashing script.
- `bin/publish`: finds releases without a hash file and writes them (run by
  `.github/workflows/publish.yml` when a release starts it, hourly as a
  backup, or by hand).

## The hash spec (`dirigible-hashes-v1`)

1. Take the files `git archive <tag>` produces (`export-ignore` applies, as
   in GitHub's source zip).
2. Leave out what the licensing server's `.dsignore` leaves out: literal
   paths and folder prefixes, read from the top folder only, plus that
   top-level `.dsignore` itself. A rule the server would reject fails here
   too.
3. Leave out the top-level `dirigible-signature.json` (a legacy signature
   file). One in a subfolder is hashed like any other file.
4. Hash each file's bytes with sha256, keyed by its path under the top
   folder, using `/`.
5. `tree` is the sha256 of the lines `<sha256> <path>\n`, sorted bytewise
   (UTF-8) by path.

A release file:

```json
{
  "format": "dirigible-hashes-v1",
  "slug": "dirigible-events",
  "version": "4.1.90",
  "repo": "DirigibleStudio/dirigible-events",
  "tag": "4.1.90",
  "commit": "<40 hex>",
  "published_at": "<ISO 8601>",
  "tree": "<sha256>",
  "files": { "<path>": "<sha256>" }
}
```

## Fixture

`tests/fixtures/package/` is a small installed tree; its expected `tree` and
`files` are in `tests/fixtures/package.expected.json`, and the exact bytes
that `tree` hashes are in `tests/fixtures/package.lines.txt`. Any other
implementation of the spec should reproduce that `tree` from that folder.
`tests/fixtures/source/` is the same tree with a `.dsignore` and the files it
removes, and hashes the same.

```bash
python3 -m unittest discover tests
```

## Publishing

Drafts, prereleases and releases whose header `Version` doesn't match the tag
are skipped, as the licensing server skips them. An existing
`<slug>/<version>.json` is never rewritten: if a tag later moves, the hash
stays with the commit that was packaged first.
