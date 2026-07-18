"""
Unit tests for Cloudflare auto-provision helpers (MBT POS 2.3.78).

Run:
  python -m pytest tests/test_cloudflare_setup.py -v
  python tests/test_cloudflare_setup.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend import cloudflare_setup as cf


class TestSubdomainSanitize(unittest.TestCase):
    def test_basic_slug(self):
        self.assertEqual(cf.shop_to_subdomain('Edmus Shop'), 'edmus-shop')
        self.assertEqual(cf.shop_to_subdomain('  ED MUS  '), 'ed-mus')

    def test_trim_and_invalid_chars(self):
        self.assertEqual(cf.shop_to_subdomain('Foo!!!Bar@@@'), 'foo-bar')
        self.assertEqual(cf.shop_to_subdomain('---'), 'mbt-shop')

    def test_leading_digit(self):
        self.assertTrue(cf.shop_to_subdomain('99 Mart').startswith('shop-'))

    def test_reserved_names(self):
        for name in ('admin', 'www', 'cloudflare', 'test', 'api', 'mail'):
            slug = cf.shop_to_subdomain(name)
            self.assertNotEqual(slug, name, f'reserved {name} must be remapped')
            ok, _ = cf.validate_subdomain(slug)
            self.assertTrue(ok, f'remapped {slug} should validate')

    def test_validate_rejects_reserved_raw(self):
        ok, reason = cf.validate_subdomain('admin')
        self.assertFalse(ok)
        self.assertIn('reserved', reason)

    def test_validate_rejects_bad_chars(self):
        ok, _ = cf.validate_subdomain('bad_name!')
        self.assertFalse(ok)

    def test_full_domain(self):
        self.assertEqual(cf.full_domain('edmus'), 'edmus.mugobyte.com')
        self.assertEqual(
            cf.full_domain('edmus.mugobyte.com'), 'edmus.mugobyte.com')


class TestTokenTypes(unittest.TestCase):
    def test_connector_cfut(self):
        self.assertTrue(cf._is_tunnel_run_token('cfut_abc123xyz'))
        self.assertFalse(cf._looks_like_management_api_token('cfut_abc123xyz'))

    def test_connector_jwt(self):
        jwt = 'eyJ' + ('a' * 40) + '.' + ('b' * 10) + '.' + ('c' * 10)
        self.assertTrue(cf._is_tunnel_run_token(jwt))
        self.assertFalse(cf._looks_like_management_api_token(jwt))

    def test_management_token(self):
        tok = 'cfat_' + ('x' * 40)
        self.assertFalse(cf._is_tunnel_run_token(tok))
        self.assertTrue(cf._looks_like_management_api_token(tok))


class TestRedact(unittest.TestCase):
    def test_redacts_tokens(self):
        s = cf._redact_secrets(
            'Bearer cfat_secrettoken123 Authorization cfut_other eyJaaaaaaaaaaaaaaaaaaaa.bbbb.cccc')
        self.assertNotIn('secrettoken', s)
        self.assertIn('[REDACTED]', s)


class TestDnsUpsert(unittest.TestCase):
    def test_existing_cname_noop(self):
        calls = []

        def fake_api(method, path, body=None, timeout=45, retries=None):
            calls.append((method, path, body))
            if method == 'GET' and 'type=CNAME' in path:
                return {
                    'success': True,
                    'result': [{
                        'id': 'rec1',
                        'content': 'tid123.cfargotunnel.com',
                        'proxied': True,
                    }],
                }
            raise AssertionError(f'unexpected {method} {path}')

        with mock.patch.object(cf, '_cf_api', side_effect=fake_api):
            cf._api_ensure_dns_cname('zone1', 'edmus.mugobyte.com', 'tid123')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'GET')

    def test_existing_cname_update(self):
        calls = []

        def fake_api(method, path, body=None, timeout=45, retries=None):
            calls.append((method, path, body))
            if method == 'GET' and 'type=CNAME' in path:
                return {
                    'success': True,
                    'result': [{
                        'id': 'rec1',
                        'content': 'old.cfargotunnel.com',
                        'proxied': True,
                    }],
                }
            if method == 'PUT':
                return {'success': True, 'result': {}}
            raise AssertionError(f'unexpected {method} {path}')

        with mock.patch.object(cf, '_cf_api', side_effect=fake_api):
            cf._api_ensure_dns_cname('zone1', 'edmus.mugobyte.com', 'tid999')
        methods = [c[0] for c in calls]
        self.assertIn('PUT', methods)

    def test_create_when_missing(self):
        calls = []

        def fake_api(method, path, body=None, timeout=45, retries=None):
            calls.append((method, path, body))
            if method == 'GET' and 'type=CNAME' in path:
                return {'success': True, 'result': []}
            if method == 'GET':
                return {'success': True, 'result': []}
            if method == 'POST':
                return {'success': True, 'result': {'id': 'new'}}
            raise AssertionError(f'unexpected {method} {path}')

        with mock.patch.object(cf, '_cf_api', side_effect=fake_api):
            cf._api_ensure_dns_cname('zone1', 'edmus.mugobyte.com', 'tid999')
        self.assertIn('POST', [c[0] for c in calls])

    def test_duplicate_post_upserts(self):
        """POST already-exists → GET + PUT (upsert)."""
        state = {'post': 0}

        def fake_api(method, path, body=None, timeout=45, retries=None):
            if method == 'GET' and 'type=CNAME' in path:
                if state['post'] == 0:
                    return {'success': True, 'result': []}
                return {
                    'success': True,
                    'result': [{'id': 'recX', 'content': 'x', 'proxied': False}],
                }
            if method == 'GET':
                return {'success': True, 'result': []}
            if method == 'POST':
                state['post'] += 1
                raise cf.CloudflareAPIError(
                    'already exists 81057', status=400, kind='api',
                    retryable=False, body='already exists')
            if method == 'PUT':
                return {'success': True, 'result': {}}
            raise AssertionError(f'unexpected {method} {path}')

        with mock.patch.object(cf, '_cf_api', side_effect=fake_api):
            cf._api_ensure_dns_cname('zone1', 'edmus.mugobyte.com', 'tid999')


class TestCfApiErrors(unittest.TestCase):
    def test_401_not_retryable(self):
        def raise_401(*a, **k):
            raise HTTPError(
                'https://api.cloudflare.com', 401, 'Unauthorized',
                hdrs=None, fp=io.BytesIO(b'{"errors":[{"code":10000}]}'))

        with mock.patch.object(cf, '_get_cloudflare_api_token', return_value='cfat_' + 'x' * 40):
            with mock.patch('urllib.request.urlopen', side_effect=raise_401):
                with self.assertRaises(cf.CloudflareAPIError) as ctx:
                    cf._cf_api('GET', '/accounts', retries=2)
        self.assertEqual(ctx.exception.kind, 'auth')
        self.assertFalse(ctx.exception.retryable)

    def test_timeout_retryable(self):
        calls = {'n': 0}

        def raise_timeout(*a, **k):
            calls['n'] += 1
            raise TimeoutError('timed out')

        with mock.patch.object(cf, '_get_cloudflare_api_token', return_value='cfat_' + 'x' * 40):
            with mock.patch('urllib.request.urlopen', side_effect=raise_timeout):
                with mock.patch.object(cf, 'time') as tmod:
                    tmod.sleep = lambda s: None
                    with self.assertRaises(cf.CloudflareAPIError) as ctx:
                        cf._cf_api('GET', '/accounts', retries=2)
        self.assertEqual(ctx.exception.kind, 'timeout')
        self.assertTrue(ctx.exception.retryable)
        self.assertGreaterEqual(calls['n'], 3)


class TestActiveGating(unittest.TestCase):
    def test_mark_active_requires_https(self):
        saved = {}

        def fake_save(updates):
            saved.update(updates)
            return cf.get_config_path()

        with mock.patch.object(cf, 'load_web_config', return_value={
            'tunnel_domain': 'edmus.mugobyte.com',
            'tunnel_id': 'tid',
        }):
            with mock.patch.object(cf, 'save_web_config', side_effect=fake_save):
                with mock.patch.object(cf, '_dns_resolves_via', return_value=(True, 'ok')):
                    with mock.patch.object(cf, '_dns_resolves', return_value=(True, 'ok')):
                        with mock.patch.object(
                                cf, '_http_check', return_value=(False, 'fail')):
                            ok = cf.mark_remote_active_if_healthy(
                                domain='edmus.mugobyte.com',
                                tunnel_id='tid',
                                verify={'remote_https_ok': False, 'dns_ok': True},
                            )
        self.assertFalse(ok)
        self.assertFalse(saved.get('remote_setup_ok'))
        self.assertTrue(saved.get('remote_setup_pending'))

    def test_mark_active_when_healthy(self):
        saved = {}

        def fake_save(updates):
            saved.update(updates)
            return cf.get_config_path()

        with mock.patch.object(cf, 'load_web_config', return_value={}):
            with mock.patch.object(cf, 'save_web_config', side_effect=fake_save):
                ok = cf.mark_remote_active_if_healthy(
                    domain='edmus.mugobyte.com',
                    tunnel_id='tid',
                    verify={
                        'remote_https_ok': True,
                        'dns_ok': True,
                        'public_dns_ok': True,
                    },
                )
        self.assertTrue(ok)
        self.assertTrue(saved.get('remote_setup_ok'))
        self.assertFalse(saved.get('remote_setup_pending'))


class TestRetryQueue(unittest.TestCase):
    def test_enqueue_dedupe(self):
        with cf._cf_retry_lock:
            cf._cf_retry_queue.clear()
        cf.enqueue_cf_retry('pending', 'edmus', 'edmus.mugobyte.com')
        cf.enqueue_cf_retry('pending', 'edmus', 'edmus.mugobyte.com')
        with cf._cf_retry_lock:
            self.assertEqual(len(cf._cf_retry_queue), 1)
            cf._cf_retry_queue.clear()


if __name__ == '__main__':
    unittest.main()
