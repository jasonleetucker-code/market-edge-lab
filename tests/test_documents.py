import sqlite3

import pytest

from edge_lab.http import FetchResult
from edge_lab.storage import SnapshotStore


def _doc(body, url="https://assets.example.test/terms.pdf", at="2026-09-22T18:00:00+00:00"):
    return FetchResult(url, url, 200, "application/pdf", body, at, 3, 1)


@pytest.fixture
def store(tmp_path):
    s = SnapshotStore(tmp_path / "e.sqlite3")
    s.start_run("r")
    return s


def test_exact_bytes_and_hash_are_stored(store):
    import hashlib

    body = b"%PDF-1.7\n\x00\xffbinary"
    rid, sha, new = store.save_document(run_id="r", source_id="kalshi_public", doc_type="kalshi_contract_terms", fetch=_doc(body))
    assert new and sha == hashlib.sha256(body).hexdigest()
    assert store.document_bytes(sha) == body


def test_versions_are_retained_not_overwritten(store):
    url = "https://assets.example.test/terms.pdf"
    _, v1, _ = store.save_document(run_id="r", source_id="k", doc_type="t", fetch=_doc(b"v1"))
    _, same, new_again = store.save_document(run_id="r", source_id="k", doc_type="t", fetch=_doc(b"v1", at="2026-09-23T00:00:00+00:00"))
    _, v2, changed = store.save_document(run_id="r", source_id="k", doc_type="t", fetch=_doc(b"v2", at="2026-09-24T00:00:00+00:00"))
    assert same == v1 and not new_again and changed
    versions = store.document_versions(url)
    assert [v["sha256"] for v in versions] == [v1, v2]
    assert versions[0]["retrievals"] == 2
    assert store.document_bytes(v1) == b"v1"  # old version still recoverable


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE document_blobs SET body = x'00'",
        "DELETE FROM document_blobs",
        "UPDATE document_retrievals SET sha256 = 'x'",
        "DELETE FROM document_retrievals",
        "INSERT OR REPLACE INTO document_retrievals(id, run_id, source_id, doc_type, requested_url, fetched_at_utc, byte_length, sha256) SELECT id, run_id, 'x', 'x', 'x', 'x', 1, sha256 FROM document_retrievals",
    ],
)
def test_documents_are_immutable(store, sql):
    store.save_document(run_id="r", source_id="k", doc_type="t", fetch=_doc(b"original"))
    with sqlite3.connect(store.path) as conn:
        conn.execute("PRAGMA recursive_triggers = ON")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(sql)


@pytest.mark.parametrize("recursive", ["ON", "OFF"])
def test_blob_replacement_keeps_original_bytes(store, recursive):
    _, sha, _ = store.save_document(run_id="r", source_id="k", doc_type="t", fetch=_doc(b"original"))
    with sqlite3.connect(store.path) as conn:
        conn.execute(f"PRAGMA recursive_triggers = {recursive}")
        conn.execute("INSERT OR REPLACE INTO document_blobs(sha256, byte_length, body) VALUES (?, 1, x'00')", (sha,))
    assert store.document_bytes(sha) == b"original"
