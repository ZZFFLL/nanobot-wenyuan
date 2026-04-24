from importlib.metadata import PackageNotFoundError

import nanobot


def test_resolve_version_prefers_source_tree_version(monkeypatch) -> None:
    monkeypatch.setattr(nanobot, "_read_pyproject_version", lambda: "0.1.5.post2")
    monkeypatch.setattr(nanobot, "_pkg_version", lambda _name: "0.1.4.post5")

    assert nanobot._resolve_version() == "0.1.5.post2"


def test_resolve_version_uses_installed_metadata_when_source_version_missing(monkeypatch) -> None:
    monkeypatch.setattr(nanobot, "_read_pyproject_version", lambda: None)
    monkeypatch.setattr(nanobot, "_pkg_version", lambda _name: "0.1.5.post2")

    assert nanobot._resolve_version() == "0.1.5.post2"


def test_resolve_version_uses_default_when_no_source_or_metadata(monkeypatch) -> None:
    monkeypatch.setattr(nanobot, "_read_pyproject_version", lambda: None)

    def _missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(nanobot, "_pkg_version", _missing)

    assert nanobot._resolve_version() == "0.1.5.post2"
