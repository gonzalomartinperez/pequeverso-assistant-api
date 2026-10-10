"""Exercise four fixture streams in an explicitly identified local smoke container.

No live-provider support. Reports cgroup-v2 memory and persistent-volume sizes; the memory
peak includes page cache and is not the same as RSS or Docker's cache-subtracted usage.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import email.message
import http.cookiejar
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        raise urllib.error.HTTPError(
            req.full_url, code, 'fixture redirects are forbidden', email.message.Message(), None
        )


def probe(url: str, container: str) -> dict[str, object]:
    origin = urlsplit(url)
    if origin.scheme != 'http' or origin.hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('fixture probe requires an HTTP loopback origin')
    config = json.loads(subprocess.check_output(['docker', 'inspect', container]))[0]
    environment = set(config['Config']['Env'])
    if not {'AI_PROVIDER=fixture', 'ALLOW_PAID_AI=false'} <= environment:
        raise ValueError('container must explicitly select fixture and refuse paid AI')
    barrier = threading.Barrier(4)

    def ask(index: int) -> float:
        opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        headers = {'Origin': 'http://localhost:3000', 'Content-Type': 'application/json'}
        # URL scheme and loopback host are checked above.
        request = urllib.request.Request(url + '/api/v1/session', data=b'{}', headers=headers)  # noqa: S310
        with opener.open(request, timeout=10) as response:
            token = json.load(response)['csrf_token']
        barrier.wait(timeout=10)
        request = urllib.request.Request(  # noqa: S310 - HTTP loopback only
            url + '/api/v1/messages',
            data=json.dumps({'content': 'What does the kit include?'}).encode(),
            headers={**headers, 'X-CSRF-Token': token, 'Idempotency-Key': f'probe-local-{index:04d}'},
        )
        started = time.monotonic()
        with opener.open(request, timeout=70) as response:
            stream = response.read().decode()
        if stream.count('event: run.completed') != 1 or 'event: message.completed' not in stream:
            raise RuntimeError('fixture stream did not complete exactly once')
        return round((time.monotonic() - started) * 1000, 2)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        durations = list(executor.map(ask, range(4)))
    measurement = subprocess.check_output(
        [
            'docker',
            'exec',
            container,
            'python',
            '-c',
            (
                'from pathlib import Path; import json; '
                'root=Path("/sys/fs/cgroup"); '
                'print(json.dumps({"memory_peak_bytes":int((root/"memory.peak").read_text()),'
                '"memory_current_bytes":int((root/"memory.current").read_text()),'
                '"memory_events":(root/"memory.events").read_text(),'
                '"data_bytes":sum(p.stat().st_size for p in Path("/data").iterdir() if p.is_file())}))'
            ),
        ]
    )
    result: dict[str, object] = json.loads(measurement)
    result['concurrent_fixture_runs'] = 4
    result['turn_ms'] = durations
    result['memory_limit_bytes'] = config['HostConfig']['Memory']
    result['nano_cpus'] = config['HostConfig']['NanoCpus']
    memory_events = dict(line.split() for line in str(result['memory_events']).splitlines())
    if memory_events.get('oom_kill') != '0' or memory_events.get('oom') != '0':
        raise RuntimeError('fixture run exhausted its memory quota')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--container', required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.url.rstrip('/'), args.container), sort_keys=True))


if __name__ == '__main__':
    main()
