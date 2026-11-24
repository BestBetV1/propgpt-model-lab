"""Read-only checks for the artifact handoff and the actual Pages response."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class DeliveryError(RuntimeError):
    pass


def fetch(url, token=None):
    headers = {'Cache-Control': 'no-cache', 'User-Agent': 'PropGPT-Pages-delivery'}
    if token:
        headers.update(Authorization='Bearer ' + token,
                       Accept='application/vnd.github+json',
                       **{'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise DeliveryError(f'HTTP {exc.code}: check read permissions') from None
        raise URLError(f'HTTP {exc.code}') from None
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise DeliveryError('TLS certificate verification failed; configure a trusted CA bundle') from None
        raise


def wait_for(check, *, timeout=180, interval=5, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while True:
        try:
            problem = check()
        except (URLError, TimeoutError) as exc:
            # Do not serialize request bodies or headers (which may carry credentials).
            problem = f'transient {type(exc).__name__}'
        if problem is None:
            return
        remaining = deadline - clock()
        if remaining <= 0:
            raise DeliveryError('Delivery check timed out: ' + problem)
        print(problem, flush=True)
        sleep(min(interval, remaining))


def artifact_problem(payload, expected_id):
    matches = [a for a in payload['artifacts']
               if a['name'] == 'github-pages' and not a['expired']]
    if len(matches) > 1:
        raise DeliveryError('Multiple active github-pages artifacts in this run')
    if not matches or str(matches[0]['id']) != str(expected_id):
        return 'Waiting for the exact uploaded github-pages artifact'
    if matches[0]['size_in_bytes'] <= 0:
        raise DeliveryError('The uploaded Pages artifact is empty')
    return None


def wait_artifact(repo, run, artifact_id, *, reader=fetch, **retry):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise DeliveryError('Invalid repository')
    if not str(run).isdigit() or not str(artifact_id).isdigit():
        raise DeliveryError('Run and uploaded artifact IDs are required')
    url = f'https://api.github.com/repos/{repo}/actions/runs/{run}/artifacts?per_page=100'

    def check():
        data = json.loads(reader(url, os.environ.get('GH_TOKEN')))
        if data['total_count'] > 100:
            raise DeliveryError('Too many artifacts to verify an unambiguous handoff')
        return artifact_problem(data, artifact_id)

    wait_for(check, **retry)
    print(f'Artifact {artifact_id} is visible in run {run}')


def expected_release(site):
    site = Path(site)
    manifest = json.loads((site / 'data/manifest.json').read_bytes())
    stamp = datetime.fromisoformat(manifest['snapshot_completed_at'])
    if manifest['format'] != 1 or stamp.tzinfo is None:
        raise DeliveryError('Expected a versioned snapshot with an aware cutoff')
    required = {'index.html', 'data/manifest.json', 'data/game-performance.json',
                'data/nfl-coherence.json'}
    for model in ['overall'] + [m['id'] for m in manifest['models']]:
        required.update(f'data/{model}-{window}.json' for window in manifest['windows'])
    files = {}
    for path in site.rglob('*'):
        if path.is_symlink():
            raise DeliveryError('Unexpected public symlink: ' + path.relative_to(site).as_posix())
        if path.is_file():
            if path.suffix not in {'.html', '.css', '.js', '.json'}:
                raise DeliveryError('Unexpected public file: ' + path.relative_to(site).as_posix())
            files[path.relative_to(site).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    missing = required - files.keys()
    if missing:
        raise DeliveryError('Incomplete expected release: ' + ', '.join(sorted(missing)))
    return manifest, files


def verify_served(site, base_url, *, reader=fetch, **retry):
    parsed = urlsplit(base_url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment:
        raise DeliveryError('Expected a clean HTTPS Pages URL')
    manifest, files = expected_release(site)
    release = files['data/manifest.json']

    def compare(item):
        name, expected = item
        url = base_url.rstrip('/') + '/' + quote(name, safe='/') + '?release=' + release
        try:
            observed = hashlib.sha256(reader(url)).hexdigest()
            return name if observed != expected else None
        except (URLError, TimeoutError):
            return name

    def check():
        with ThreadPoolExecutor(max_workers=8) as pool:
            mismatches = [name for name in pool.map(compare, files.items()) if name]
        if mismatches:
            return f'{len(mismatches)} served files differ or are unavailable: ' + ', '.join(mismatches[:4])
        return None

    wait_for(check, **retry)
    print(json.dumps({'status': 'verified', 'files': len(files),
                      'snapshot_completed_at': manifest['snapshot_completed_at'],
                      'generated_at': manifest['generated_at'], 'manifest_sha256': release}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'artifact', 'verify'])
    parser.add_argument('--site', default='site')
    parser.add_argument('--url', default=os.environ.get('PAGES_URL'))
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    try:
        if args.timeout < 0:
            raise DeliveryError('Timeout cannot be negative')
        if args.action == 'validate':
            manifest, files = expected_release(args.site)
            print(json.dumps({'files': len(files), 'snapshot_completed_at': manifest['snapshot_completed_at']}))
        elif args.action == 'artifact':
            wait_artifact(os.environ.get('GITHUB_REPOSITORY', ''),
                          os.environ.get('GITHUB_RUN_ID', ''),
                          os.environ.get('PAGES_ARTIFACT_ID', ''), timeout=args.timeout)
        else:
            verify_served(args.site, args.url or '', timeout=args.timeout)
    except (DeliveryError, KeyError, ValueError, OSError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
