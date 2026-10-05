#!/usr/bin/env python3
"""Validate local assets and links for the DEXTERA GitHub Pages deployment."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import json
import re

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SITE_URL = "https://zeyansun.github.io/dextera/"

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.refs = []
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            if data["id"] in self.ids:
                self.duplicates.append(data["id"])
            self.ids.add(data["id"])
        for key in ("src", "href", "poster"):
            if data.get(key):
                self.refs.append((tag, data[key]))
        if data.get("srcset"):
            for item in data["srcset"].split(","):
                self.refs.append((tag, item.strip().split()[0]))

def check_ref(reference, parent, page=None):
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc:
        return
    if not parsed.path:
        if page is not None and parsed.fragment:
            assert unquote(parsed.fragment) in page.ids, f"Missing anchor: {reference}"
        return
    assert not parsed.path.startswith("/"), f"Root-relative resource breaks project URL: {reference}"
    target = (parent / unquote(parsed.path)).resolve()
    assert target.is_relative_to(DIST.resolve()), f"Resource outside dist: {reference}"
    assert target.is_file(), f"Missing resource: {reference}"
    published_url = urljoin(SITE_URL, reference)
    assert published_url.startswith(SITE_URL), f"Resource escapes /dextera/: {reference}"

def manifest_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"url", "reference", "preview"} and isinstance(item, str):
                yield item
            else:
                yield from manifest_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from manifest_refs(item)

def main():
    assert (DIST / "index.html").is_file(), "Missing dist/index.html"
    paths = list(DIST.rglob("*"))
    assert not any(path.is_symlink() for path in paths), "Symlinks are not supported"
    files = [path for path in paths if path.is_file()]
    assert files, "Empty deployment"
    total = sum(path.stat().st_size for path in files)
    assert total < 1_000_000_000, "GitHub Pages site exceeds 1 GB"
    for path in files:
        assert path.stat().st_size < 100 * 1024 * 1024, f"Git file exceeds 100 MiB: {path}"

    count = 0
    pages = {}
    for path in DIST.rglob("*.html"):
        page = Page()
        text = path.read_text(encoding="utf-8")
        page.feed(text)
        assert not page.duplicates, f"Duplicate IDs: {page.duplicates}"
        assert not re.search(r"<base\b", text, flags=re.I), "Unexpected base URL"
        pages[path] = page
        for _, ref in page.refs:
            check_ref(ref, path.parent, page)
            count += 1

    pattern = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)""")
    for path in DIST.rglob("*.css"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            ref = next(item for item in match.groups() if item is not None).strip()
            check_ref(ref, path.parent)
            count += 1

    index_text = (DIST / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script\b[^>]*\bid="scene-manifest"[^>]*>([\s\S]*?)</script>',
        index_text,
    )
    assert match, "Missing inline scene manifest"
    manifest = json.loads(match.group(1))
    stored = json.loads((DIST / "assets/viewer/manifest.json").read_text(encoding="utf-8"))
    assert manifest == stored, "Inline and stored scene manifests differ"
    assert len(manifest["layouts"]) == 3, "Expected three layouts"
    assert len(manifest["backgrounds"]) == 3, "Expected three backgrounds"
    for ref in manifest_refs(manifest):
        check_ref(ref, DIST)
        count += 1
    for background in manifest["backgrounds"]:
        assert (DIST / background["url"]).stat().st_size == background["bytes"]

    assert (DIST / ".nojekyll").is_file(), "Missing .nojekyll"
    assert not re.search(r"\bICRA\b|Scope and future directions", index_text, flags=re.I)
    print(json.dumps({
        "site_url": SITE_URL,
        "files": len(files),
        "bytes": total,
        "references_checked": count,
        "layouts": len(manifest["layouts"]),
        "backgrounds": len(manifest["backgrounds"]),
        "result": "passed",
    }, indent=2))

if __name__ == "__main__":
    main()
