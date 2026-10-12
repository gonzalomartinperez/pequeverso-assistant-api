"""A targeted paid runner must preserve the initial matrix and existing financial gates."""

import copy
import json

import pytest

from scripts.revalidate_end_to_end import main, validate_matrix


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
        'reply_policy': 'spanish_native',
        'policy_expected_languages': {'original:1': 'es', 'revalidation-new:1': 'es'},
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


@pytest.mark.parametrize('expectations', [{}, {'original:1': 'en', 'revalidation-new:1': 'es'}])
def test_new_policy_must_annotate_every_turn_without_relabeling_baseline(expectations):
    manifest, baseline = matrices()
    manifest['policy_expected_languages'] = expectations
    with pytest.raises(ValueError, match='explicit Spanish-policy expectation'):
        validate_matrix(manifest, baseline)
    assert manifest['cases'][0]['turns'][0]['expected_language'] == 'en'


def test_wrong_baseline_digest_stops_before_key_or_budget_access(tmp_path, monkeypatch, capsys):
    manifest, baseline = matrices()
    manifest['baseline_manifest_sha256'] = '0' * 64
    manifest_path, baseline_path = tmp_path / 'matrix.json', tmp_path / 'baseline.json'
    manifest_path.write_text(json.dumps(manifest))
    baseline_path.write_text(json.dumps(baseline))
    budget = tmp_path / 'must-not-be-created.sqlite3'
    monkeypatch.setattr(
        'sys.argv',
        [
            'revalidate_end_to_end.py',
            '--manifest',
            str(manifest_path),
            '--baseline-manifest',
            str(baseline_path),
            '--previous-run',
            str(tmp_path / 'missing-run'),
            '--key-file',
            str(tmp_path / 'missing-key'),
            '--budget-state',
            str(budget),
            '--output-dir',
            str(tmp_path / 'new-output'),
            '--source-revision',
            'synthetic-test-revision',
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert 'baseline manifest does not match its frozen digest' in capsys.readouterr().err
    assert not budget.exists()
