"""A targeted paid runner must preserve the initial matrix and existing financial gates."""

import copy

import pytest

from scripts.revalidate_end_to_end import validate_matrix


def matrices():
    original = {
        'id': 'original',
        'turns': [{'question': 'Original question', 'expected_language': 'en'}],
    }
    baseline = {'cases': [original, {'id': 'remainder', 'turns': [{'question': 'Other question'}] * 199}]}
    variant = {
        'id': 'revalidation-new',
        'relation': 'new_variant',
        'turns': [{'question': 'New question', 'expected_language': 'en'}],
    }
    manifest = {
        'phase': 'post-adjustment targeted revalidation; not independent holdout',
        'query_count': 2,
        'cases': [copy.deepcopy(original), variant],
    }
    return manifest, baseline


def test_targeted_matrix_accepts_preserved_case_and_separate_variant():
    manifest, baseline = matrices()
    assert validate_matrix(manifest, baseline) == {
        'queries': 2,
        'repeated_cases': 1,
        'new_variant_cases': 1,
    }


@pytest.mark.parametrize(('field', 'value'), [('question', 'Altered question'), ('expected_language', 'es')])
def test_revalidation_cannot_relabel_or_edit_an_original_case(field, value):
    manifest, baseline = matrices()
    manifest['cases'][0]['turns'][0][field] = value
    with pytest.raises(ValueError, match='unchanged'):
        validate_matrix(manifest, baseline)


def test_revalidation_cannot_replace_the_full_baseline_with_a_small_one():
    manifest, baseline = matrices()
    baseline['cases'].pop()
    with pytest.raises(ValueError, match='>=200'):
        validate_matrix(manifest, baseline)


def test_revalidation_rejects_duplicate_case_ids():
    manifest, baseline = matrices()
    manifest['cases'].append(copy.deepcopy(manifest['cases'][1]))
    with pytest.raises(ValueError, match='unique'):
        validate_matrix(manifest, baseline)


def test_revalidation_cannot_expand_past_its_finite_query_limit():
    manifest, baseline = matrices()
    manifest['cases'][1]['turns'] *= 64
    manifest['query_count'] = 65
    with pytest.raises(ValueError, match='64 queries'):
        validate_matrix(manifest, baseline)


def test_revalidation_must_disclose_phase_and_actual_query_count():
    manifest, baseline = matrices()
    manifest['query_count'] = 10
    with pytest.raises(ValueError, match='query count'):
        validate_matrix(manifest, baseline)
    manifest['phase'] = 'independent holdout'
    with pytest.raises(ValueError, match='non-independent'):
        validate_matrix(manifest, baseline)
