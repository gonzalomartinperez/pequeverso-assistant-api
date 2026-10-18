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


def owned_invocation(tmp_path, monkeypatch):
    from scripts import revalidate_end_to_end as revalidate
    from scripts.real_eval_budget import Envelope

    manifest, baseline = matrices()
    baseline_path = tmp_path / 'baseline.json'
    baseline_path.write_text(json.dumps(baseline))
    manifest['baseline_manifest_sha256'] = revalidate.digest(baseline_path.read_bytes())
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    previous = tmp_path / 'previous'
    previous.mkdir()
    ledger = Envelope(tmp_path / 'budget.sqlite3')
    (previous / 'budget.json').write_text(json.dumps(ledger.snapshot()))
    output = tmp_path / 'new-output'
    monkeypatch.setattr(
        revalidate.sys,
        'argv',
        [
            'revalidate_end_to_end',
            '--manifest',
            str(manifest_path),
            '--baseline-manifest',
            str(baseline_path),
            '--previous-run',
            str(previous),
            '--key-file',
            str(tmp_path / 'synthetic-never-read'),
            '--budget-state',
            str(ledger.path),
            '--output-dir',
            str(output),
            '--source-revision',
            'a' * 40,
        ],
    )
    return revalidate, ledger, output


def test_revalidation_refuses_owned_budget_before_validation_key_output_or_evaluation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from scripts.real_eval_budget import evaluation_run_ownership

    revalidate, ledger, output = owned_invocation(tmp_path, monkeypatch)
    before = ledger.snapshot()
    phases = []
    monkeypatch.setattr(revalidate, 'verify_existing_budget', lambda *args, **kwargs: phases.append('verify'))
    monkeypatch.setattr(
        revalidate,
        'load_live_provider',
        lambda *args: phases.append('key') or SimpleNamespace(envelope=ledger),
    )
    monkeypatch.setattr(
        revalidate, 'evaluate', lambda *args, **kwargs: phases.append('evaluate') or {'stop_reason': None}
    )
    with evaluation_run_ownership(ledger.path), pytest.raises(ValueError, match='already owned'):
        revalidate.main()
    assert phases == []
    assert not output.exists()
    assert ledger.snapshot() == before


@pytest.mark.parametrize('evaluation_fails', [False, True])
def test_revalidation_owns_entire_paid_boundary_and_releases_on_success_or_error(
    tmp_path, monkeypatch, evaluation_fails
):
    from types import SimpleNamespace

    from scripts.real_eval_budget import evaluation_run_ownership

    revalidate, ledger, _ = owned_invocation(tmp_path, monkeypatch)
    before = ledger.snapshot()
    phases = []
    original_verify = revalidate.verify_existing_budget

    def require_ownership(phase):
        with pytest.raises(ValueError, match='already owned'), evaluation_run_ownership(ledger.path):
            pass
        phases.append(phase)

    def verify(*args, **kwargs):
        require_ownership('verify')
        original_verify(*args, **kwargs)

    def load(*args):
        require_ownership('key')
        return SimpleNamespace(envelope=ledger)

    def evaluate(*args, **kwargs):
        require_ownership('evaluate')
        if evaluation_fails:
            raise RuntimeError('synthetic_revalidation_failure')
        return {'stop_reason': None}

    monkeypatch.setattr(revalidate, 'verify_existing_budget', verify)
    monkeypatch.setattr(revalidate, 'load_live_provider', load)
    monkeypatch.setattr(revalidate, 'evaluate', evaluate)
    if evaluation_fails:
        with pytest.raises(RuntimeError, match='synthetic_revalidation_failure'):
            revalidate.main()
    else:
        revalidate.main()
    assert phases == ['verify', 'key', 'evaluate']
    with evaluation_run_ownership(ledger.path):
        pass
    assert ledger.snapshot() == before
