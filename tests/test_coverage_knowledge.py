"""Knowledge projections require stable identities before any storage writes."""

from dataclasses import replace

import pytest

from app.domain.knowledge import ProjectionStamp
from tests.test_knowledge_indexing import corpus


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"version": "latest"}, "fingerprints must be sha256"),
        ({"catalog_sha256": "123"}, "fingerprints must be sha256"),
        ({"source_revision": "develop"}, "exact source revision"),
        ({"parser_version": ""}, "parser version"),
    ],
)
def test_knowledge_revision_requires_exact_content_and_source_identity(changes, message):
    with pytest.raises(ValueError, match=message):
        replace(corpus().revision, **changes)


@pytest.mark.parametrize("field", ["id", "source_id", "source_pointer"])
def test_public_chunk_requires_stable_source_identity(field):
    with pytest.raises(ValueError, match="stable source identity"):
        replace(corpus().chunks[0], **{field: ""})


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unnamed"])
def test_corpus_rejects_ambiguous_entity_provenance(kind):
    original = corpus()
    first = original.entities[0]
    entities = {
        "missing": (),
        "duplicate": (first, first),
        "unnamed": (replace(first, id=""),),
    }
    with pytest.raises(ValueError, match="entity ids must be nonempty and unique"):
        replace(original, entities=entities[kind])


@pytest.mark.parametrize("duplicate", [False, True])
def test_corpus_requires_a_nonempty_unique_set_of_chunk_ids(duplicate):
    original = corpus()
    first = original.chunks[0]
    with pytest.raises(ValueError, match="chunks must be nonempty and uniquely identified"):
        replace(original, chunks=(first, first) if duplicate else ())


def test_projection_proof_cannot_use_a_mutable_catalog_label():
    with pytest.raises(ValueError, match="projections require exact knowledge fingerprints"):
        ProjectionStamp("a" * 64, "latest", 1, 0, 0)
