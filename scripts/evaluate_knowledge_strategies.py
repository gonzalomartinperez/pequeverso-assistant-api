"""Thin explicit-fixture entry point; resource composition lives in bootstrap."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bootstrap.knowledge_evaluation import main, safe_exception_hook

if __name__ == '__main__':
    sys.excepthook = safe_exception_hook
    root = ROOT
    changed = subprocess.run(
        [
            'git',
            'status',
            '--porcelain',
            '--untracked-files=all',
            '--',
            'app',
            'scripts/evaluate_knowledge_strategies.py',
            'evals/knowledge',
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if changed.stdout.strip():
        raise SystemExit('Commit application and evaluation code before freezing a fixture run')
    revision = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=root, check=True, capture_output=True, text=True
    )
    os.environ['PV_EVALUATION_CODE_REVISION'] = revision.stdout.strip()
    main()
