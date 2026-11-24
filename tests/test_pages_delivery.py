import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from urllib.parse import unquote, urlsplit

from ops.pages_delivery import (DeliveryError, artifact_problem, expected_release,
                                verify_served, wait_artifact, wait_for)


def artifact(ident=12, expired=False, size=123):
    return {'id': ident, 'name': 'github-pages', 'expired': expired, 'size_in_bytes': size}


class Clock:
    def __init__(self):
        self.now = 0

    def time(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class DeliveryTests(unittest.TestCase):
    def test_uploaded_artifact_becomes_visible_after_empty_listing(self):
        clock = Clock()
        payloads = iter([{'total_count': 0, 'artifacts': []},
                         {'total_count': 1, 'artifacts': [artifact()]}])
        calls = []

        def read(url, token):
            calls.append(url)
            return json.dumps(next(payloads)).encode()

        wait_artifact('owner/repo', '34', '12', reader=read,
                      clock=clock.time, sleep=clock.sleep)
        self.assertEqual(len(calls), 2)
        self.assertIn('/runs/34/artifacts?', calls[0])

    def test_different_run_artifact_id_or_expired_artifact_cannot_satisfy_gate(self):
        for item in [artifact(13), artifact(expired=True)]:
            self.assertIsNotNone(artifact_problem({'artifacts': [item]}, '12'))

    def test_ambiguous_or_empty_artifact_is_rejected(self):
        for items in [[artifact(), artifact(13)], [artifact(size=0)]]:
            with self.assertRaises(DeliveryError):
                artifact_problem({'artifacts': items}, '12')

    def test_missing_artifact_times_out_without_deploying(self):
        clock = Clock()
        with self.assertRaisesRegex(DeliveryError, 'timed out'):
            wait_for(lambda: 'missing artifact', timeout=10,
                     clock=clock.time, sleep=clock.sleep)
        self.assertEqual(clock.now, 10)

    def test_transient_network_error_can_recover(self):
        calls = iter([URLError('temporary'), None])
        clock = Clock()

        def check():
            value = next(calls)
            if value:
                raise value

        wait_for(check, clock=clock.time, sleep=clock.sleep)
        self.assertEqual(clock.now, 5)

    def test_permission_failure_is_not_retried(self):
        clock = Clock()
        def denied():
            raise DeliveryError('HTTP 403: check read permissions')
        with self.assertRaisesRegex(DeliveryError, 'HTTP 403'):
            wait_for(denied, clock=clock.time, sleep=clock.sleep)
        self.assertEqual(clock.now, 0)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = Path(self.tmp.name)
        (self.site / 'data').mkdir()
        self.write('index.html', b'<html>current release</html>')
        manifest = {'format': 1, 'snapshot_completed_at': '2026-11-23T23:17:58+00:00',
                    'generated_at': '2026-11-24T00:20:22+00:00',
                    'models': [{'id': 'nfl_props'}], 'windows': ['all']}
        self.write('data/manifest.json', json.dumps(manifest).encode())
        for name in ['game-performance', 'nfl-coherence', 'overall-all', 'nfl_props-all']:
            self.write(f'data/{name}.json', b'{"current": true}')

    def write(self, path, data):
        (self.site / path).write_bytes(data)

    def current(self, url):
        return (self.site / unquote(urlsplit(url).path.removeprefix('/lab/'))).read_bytes()

    def test_complete_served_release_passes(self):
        verify_served(self.site, 'https://example.test/lab/', reader=self.current, timeout=0)

    def test_stale_manifest_or_single_stale_aggregate_cannot_pass(self):
        for stale in ['data/manifest.json', 'data/nfl_props-all.json']:
            def mixed(url):
                return b'old release' if stale in url else self.current(url)
            with self.assertRaisesRegex(DeliveryError, 'served files differ'):
                verify_served(self.site, 'https://example.test/lab/', reader=mixed, timeout=0)

    def test_missing_report_fails_before_network(self):
        (self.site / 'data/nfl_props-all.json').unlink()
        with self.assertRaisesRegex(DeliveryError, 'Incomplete expected release'):
            expected_release(self.site)

    def test_unavailable_public_report_is_failure(self):
        def missing(url):
            raise URLError('404')
        with self.assertRaisesRegex(DeliveryError, 'served files differ'):
            verify_served(self.site, 'https://example.test/lab/', reader=missing, timeout=0)

    def test_incomplete_propagation_is_retried(self):
        clock = Clock()
        def propagating(url):
            return b'old release' if clock.now == 0 else self.current(url)
        verify_served(self.site, 'https://example.test/lab/', reader=propagating,
                      clock=clock.time, sleep=clock.sleep)
        self.assertEqual(clock.now, 5)

    def test_unsafe_public_file_is_not_uploaded_as_a_valid_release(self):
        self.write('private.sqlite', b'database')
        with self.assertRaisesRegex(DeliveryError, 'Unexpected public file'):
            expected_release(self.site)

    def test_directory_symlink_cannot_bypass_public_file_check(self):
        (self.site / 'linked-directory').symlink_to(self.site / 'data', target_is_directory=True)
        with self.assertRaisesRegex(DeliveryError, 'Unexpected public symlink'):
            expected_release(self.site)


if __name__ == '__main__':
    unittest.main()
