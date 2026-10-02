"""The results site: pages assembled from Markdown reports, with links that still work."""

from pathlib import Path

import pytest

from triagelab.site import Page, SiteSpec, anchor, asset_name, build_site, load_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/o/r"


def repo(tmp_path: Path) -> Path:
    """A tiny repository: two reports, a figure, and a file that is not on the site."""
    root = tmp_path / "repo"
    (root / "reports" / "figures").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "reports" / "figures" / "curve.png").write_bytes(b"\x89PNG fake")
    (root / "docs" / "DECISIONS.md").write_text("# Decisions\n", encoding="utf-8")
    (root / "reports" / "results.md").write_text(
        "# Results\n\n"
        "| system | F1 |\n|---|---|\n| agent | **0.80** |\n\n"
        "![The curve](figures/curve.png)\n\n"
        "See [calibration](calibration.md), [one section](calibration.md#ece), "
        "[the decisions](../docs/DECISIONS.md), [the docs folder](../docs), "
        "[elsewhere](https://example.org/x), [below](#results) and [gone](missing.md).\n",
        encoding="utf-8",
    )
    (root / "reports" / "calibration.md").write_text(
        "# Calibration\n\nBack to [results](results.md).\n", encoding="utf-8"
    )
    return root


SPEC = SiteSpec(
    title="lab", tagline="a tagline", repo_url=URL,
    pages=[
        Page(slug="index", title="Results", sources=["reports/results.md"]),
        Page(slug="calibration", title="Calibration & more", sources=["reports/calibration.md"]),
    ],
)  # fmt: skip


def test_pages_are_written_with_their_tables_and_navigation(tmp_path: Path) -> None:
    out = tmp_path / "site"
    pages = build_site(SPEC, repo(tmp_path), out)
    assert [p.name for p in pages] == ["index.html", "calibration.html"]
    index = (out / "index.html").read_text(encoding="utf-8")
    assert '<div class="table"><table>' in index
    assert "<strong>0.80</strong>" in index
    assert '<a href="index.html" class="here">Results</a>' in index
    assert '<a href="calibration.html">Calibration &amp; more</a>' in index  # escaped
    assert (out / ".nojekyll").is_file()


def test_links_are_rewritten_by_where_their_target_lives(tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(SPEC, repo(tmp_path), out)
    index = (out / "index.html").read_text(encoding="utf-8")
    # A report on the site: its page, at its section (or at the anchor asked for).
    assert f'href="calibration.html#{anchor("reports/calibration.md")}"' in index
    assert 'href="calibration.html#ece"' in index
    # Any other file or folder of the repository: on GitHub.
    assert f'href="{URL}/blob/main/docs/DECISIONS.md"' in index
    assert f'href="{URL}/tree/main/docs"' in index
    # External links, in-page anchors and broken links are left alone.
    assert 'href="https://example.org/x"' in index
    assert 'href="#results"' in index
    assert 'href="missing.md"' in index
    back = (out / "calibration.html").read_text(encoding="utf-8")
    assert f'href="index.html#{anchor("reports/results.md")}"' in back
    assert f'<section id="{anchor("reports/calibration.md")}">' in back


def test_images_are_copied_next_to_the_pages(tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(SPEC, repo(tmp_path), out)
    name = asset_name("reports/figures/curve.png")
    assert name == "reports__figures__curve.png"
    assert (out / "assets" / name).read_bytes() == b"\x89PNG fake"
    assert f'src="assets/{name}"' in (out / "index.html").read_text(encoding="utf-8")


def test_a_rebuild_replaces_the_site_and_a_missing_report_stops_it(tmp_path: Path) -> None:
    root, out = repo(tmp_path), tmp_path / "site"
    build_site(SPEC, root, out)
    (out / "stale.html").write_text("old", encoding="utf-8")
    build_site(SPEC, root, out)
    assert not (out / "stale.html").exists()
    broken = SPEC.model_copy(
        update={"pages": [Page(slug="index", title="x", sources=["reports/nope.md"])]}
    )
    with pytest.raises(FileNotFoundError, match=r"nope\.md"):
        build_site(broken, root, out)


def test_the_real_site_builds_from_a_checkout_alone(tmp_path: Path) -> None:
    """What pages.yml does: no data, no runs, only committed files."""
    spec = load_spec(REPO_ROOT / "reports" / "site.yaml")
    pages = build_site(spec, REPO_ROOT, tmp_path / "site")
    assert {p.name for p in pages} >= {"index.html", "test-set.html", "calibration.html"}
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "The held-out test set" in index
    assert (tmp_path / "site" / "assets" / asset_name("reports/figures/demo.gif")).is_file()
