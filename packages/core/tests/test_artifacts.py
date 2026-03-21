from localknowledge.artifacts import ArtifactStore
from localknowledge.documents import DocumentStore


def _create_doc(db):
    return DocumentStore(db).create(
        title="Test", source_type="article", source_product="readcast"
    )


def test_crud(db):
    doc = _create_doc(db)
    store = ArtifactStore(db)
    artifact = store.create(
        doc.id, "audio", path="/tmp/audio.mp3", metadata={"voice": "sky"}
    )
    assert artifact["id"]
    fetched = store.get(artifact["id"])
    assert fetched is not None
    assert fetched["artifact_type"] == "audio"
    assert fetched["metadata"] == {"voice": "sky"}


def test_filter_by_type(db):
    doc = _create_doc(db)
    store = ArtifactStore(db)
    store.create(doc.id, "audio", path="/tmp/a.mp3")
    store.create(doc.id, "transcript", path="/tmp/t.txt")
    audio_only = store.get_for_document(doc.id, artifact_type="audio")
    assert len(audio_only) == 1
    assert audio_only[0]["artifact_type"] == "audio"


def test_get_latest(db):
    doc = _create_doc(db)
    store = ArtifactStore(db)
    store.create(doc.id, "audio", path="/tmp/v1.mp3")
    second = store.create(doc.id, "audio", path="/tmp/v2.mp3")
    latest = store.get_latest(doc.id, "audio")
    assert latest["id"] == second["id"]


def test_cascade_on_document_delete(db):
    doc = _create_doc(db)
    artifacts = ArtifactStore(db)
    artifact = artifacts.create(doc.id, "audio")
    DocumentStore(db).delete(doc.id, hard=True)
    assert artifacts.get(artifact["id"]) is None


def test_status_transitions(db):
    doc = _create_doc(db)
    store = ArtifactStore(db)
    artifact = store.create(doc.id, "audio")
    assert artifact["status"] == "queued"

    store.update_status(artifact["id"], "processing")
    updated = store.get(artifact["id"])
    assert updated["status"] == "processing"

    store.update_status(artifact["id"], "done", metadata={"duration_sec": 120.5})
    done = store.get(artifact["id"])
    assert done["status"] == "done"
    assert done["metadata"]["duration_sec"] == 120.5
