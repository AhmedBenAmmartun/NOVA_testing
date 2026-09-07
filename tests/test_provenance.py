from __future__ import annotations

from pathlib import Path

from nova_intelligence.provenance import file_provenance, observation_provenance, sha256_bytes


def test_sha256_bytes_is_deterministic() -> None:
    assert sha256_bytes(b"nova") == sha256_bytes(b"nova")
    assert sha256_bytes(b"nova") != sha256_bytes(b"NOVA")


def test_file_provenance_records_relative_source_and_digest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "docs" / "note.md"
    target.parent.mkdir()
    target.write_text("verified fact", encoding="utf-8")

    prov = file_provenance(target, root=root, source_kind="documentation")

    assert prov.source == "docs/note.md"
    assert prov.source_kind == "documentation"
    assert len(prov.digest) == 64
    assert prov.observed_at


def test_observation_provenance_does_not_store_payload() -> None:
    prov = observation_provenance("git", "git rev-parse HEAD", "secret-ish-output")
    assert prov.source == "git rev-parse HEAD"
    assert "secret-ish-output" not in prov.note
    assert len(prov.digest) == 64


def test_external_file_provenance_hides_absolute_parent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "private-user-path" / "evidence.json"
    external.parent.mkdir()
    external.write_text("{}", encoding="utf-8")

    prov = file_provenance(external, root=repo, source_kind="test")

    assert prov.source == "<external>/evidence.json"
    assert "private-user-path" not in prov.source
