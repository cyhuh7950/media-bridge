import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
PUBLIC_DOC_DIRECTORIES = {"install", "manuals"}


def test_only_public_manual_directories_are_tracked_under_docs() -> None:
    unexpected = sorted(
        path.relative_to(ROOT).as_posix()
        for path in DOCS.rglob("*")
        if path.is_file() and path.relative_to(DOCS).parts[0] not in PUBLIC_DOC_DIRECTORIES
    )
    assert unexpected == []


def test_internal_agent_document_is_not_in_public_source_tree() -> None:
    assert not (ROOT / "SKILL.md").exists()


def test_public_repository_has_readme_and_license() -> None:
    required = ("README.md", "LICENSE", "packaging/npm/README.md", "packaging/npm/LICENSE")
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == []


def test_public_readme_links_only_to_retained_manuals() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    linked_docs = set()
    for fragment in readme.split("(")[1:]:
        target = fragment.split(")", 1)[0]
        if target.startswith("docs/"):
            linked_docs.add(target.split("#", 1)[0])
    missing = sorted(path for path in linked_docs if not (ROOT / path).is_file())
    assert missing == []


def test_retained_markdown_has_no_broken_local_links() -> None:
    documents = [ROOT / "README.md", ROOT / "packaging/npm/README.md"]
    documents.extend(sorted((ROOT / "docs/install").glob("*.md")))
    documents.extend(sorted((ROOT / "docs/manuals").rglob("*.md")))
    broken = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            clean_target = target.split("#", 1)[0]
            if not clean_target or "://" in clean_target or clean_target.startswith("mailto:"):
                continue
            if not (document.parent / clean_target).resolve().exists():
                broken.append(f"{document.relative_to(ROOT).as_posix()} -> {target}")
    assert broken == []


def test_retained_manuals_do_not_expose_private_environment_names() -> None:
    documents = [ROOT / "README.md", ROOT / "packaging/npm/README.md"]
    documents.extend(sorted((ROOT / "docs/install").glob("*.md")))
    documents.extend(sorted((ROOT / "docs/manuals").rglob("*.md")))
    forbidden = re.compile(
        r"ysna-server|SINSAN|WSL-server|D:\\Project|C:\\Users|/home/(?:daon|ubuntu)",
        re.IGNORECASE,
    )
    exposed = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        if forbidden.search(text):
            exposed.append(document.relative_to(ROOT).as_posix())
    assert exposed == []


def test_npm_metadata_points_to_public_source_repository() -> None:
    package = json.loads((ROOT / "packaging/npm/package.json").read_text(encoding="utf-8"))
    assert package["license"] == "MIT"
    assert package["repository"] == {
        "type": "git",
        "url": "git+https://github.com/cyhuh7950/media-bridge.git",
    }
    assert package["homepage"] == "https://github.com/cyhuh7950/media-bridge#readme"
    assert package["bugs"] == {"url": "https://github.com/cyhuh7950/media-bridge/issues"}
