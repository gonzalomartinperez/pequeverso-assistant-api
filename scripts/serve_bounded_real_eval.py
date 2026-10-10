"""Owner-authorized loopback-only evaluation server; never a deployment recipe.

The default fixture mode does not read a key. Real mode shares the exact evaluation ledger.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from dotenv import dotenv_values
from pydantic import SecretStr

from app.bootstrap.config import Settings
from app.bootstrap.container import create_app
from scripts.real_eval_budget import BoundedProvider, Envelope


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    state = args.state_dir.resolve()
    if state.is_relative_to(ROOT):
        raise ValueError('private state must be outside repository')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(state.stat().st_mode) != 0o700:
        raise ValueError('state directory must be private mode700')
    token = secrets.token_urlsafe(32)
    settings = Settings(
        _env_file=None,
        environment='development',
        ai_provider='fixture',
        allow_paid_ai=False,
        openai_api_key=None,
        assistant_enabled=True,
        database_path=str(state / 'ui-operations.sqlite3'),
        session_cookie_secure=False,
        allowed_origins=['http://localhost:3342'],
        ops_read_token=SecretStr(token),
        openai_max_retries=0,
    )
    provider = None
    if args.live:
        if args.key_file is None or stat.S_IMODE(args.key_file.stat().st_mode) != 0o600:
            raise ValueError('live key file must be private mode600')
        values = dotenv_values(args.key_file, interpolate=False)
        key = values.get('OPENAI_API_KEY')
        if (
            not key
            or values.get('OPENAI_MODEL') != 'gpt-6-luna'
            or values.get('OPENAI_REASONING_EFFORT') != 'medium'
        ):
            raise ValueError('private evaluation configuration does not match authorized model')
        envelope = Envelope(state / 'aggregate-budget.sqlite3')
        if envelope.snapshot()['stop_reason']:
            raise ValueError('evaluation ledger is stopped')
        provider = BoundedProvider(key, envelope)
        settings = settings.model_copy(
            update={'ai_provider': 'openai', 'allow_paid_ai': True, 'openai_api_key': SecretStr(key)}
        )
    ops = state / 'local-ops.env.local'
    ops.write_text(f'LIVE_OPS_URL=http://localhost:18088\nLIVE_OPS_TOKEN={token}\n')
    ops.chmod(0o600)
    app = create_app(settings, provider=provider)
    for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2', 'openai'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    uvicorn.run(app, host='127.0.0.1', port=18088, access_log=False, log_config=None)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- redact all errors at private-key boundary
        print(json.dumps({'outcome': 'stopped', 'error_type': type(error).__name__}))
        sys.exit(2)
