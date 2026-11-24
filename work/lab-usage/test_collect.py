import unittest
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
from unittest.mock import patch
import collect

class Limits(unittest.TestCase):
    def test_credentials_use_verified_tls_and_redirects_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'CODEX_HOME':directory}):
            (Path(directory)/'auth.json').write_text(json.dumps({'tokens':{'access_token':'fixture'}}))
            with patch.object(collect.urllib.request,'build_opener') as build:
                build.return_value.open.return_value=io.BytesIO(b'{"rate_limit":{}}')
                collect.collect('codex')
                policy,https=build.call_args.args
                self.assertIsNone(policy.redirect_request(None,None,302,'',{},'https://example.invalid'))
                self.assertTrue(https._context.check_hostname)
                self.assertEqual(https._context.verify_mode,ssl.CERT_REQUIRED)
                self.assertGreaterEqual(https._context.minimum_version,ssl.TLSVersion.TLSv1_2)
                request=build.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url,'https://chatgpt.com/backend-api/wham/usage')
    def test_retry_after_supports_seconds_and_http_date(self):
        self.assertEqual(collect.retry_after('87', 0),87)
        self.assertEqual(collect.retry_after('Thu, 01 Jan 1970 00:02:00 GMT', 20),100)
        self.assertIsNone(collect.retry_after('invalid',0))
    def test_fable_uses_scoped_limit_not_weekly_share(self):
        data = {'seven_day': {'utilization': 48}, 'weekly_scoped_shares': [{'used_percent_of_weekly': 37}], 'limits': [{'kind': 'weekly_scoped', 'percent': 73, 'resets_at': '2030-01-01T00:00:00Z', 'scope': {'model': {'display_name': 'Fable'}}}]}
        self.assertEqual(collect.normalize('claude', data)['fable'], {'used': 73, 'reset': 1893456000})
    def test_invalid_fable_does_not_hide_total(self):
        data = {'seven_day': {'utilization': 48}, 'limits': [{'kind': 'weekly_scoped', 'percent': 'bad', 'scope': {'model': {'display_name': 'Fable'}}}]}
        self.assertEqual(collect.normalize('claude', data)['used'], 48)
        self.assertNotIn('fable', collect.normalize('claude', data))
    def test_codex_selects_week_by_duration(self):
        data = {'rate_limit': {'primary_window': {'used_percent': 9, 'limit_window_seconds': 604800, 'reset_at': 1900000000}, 'secondary_window': {'used_percent': 5, 'limit_window_seconds': 18000}}}
        self.assertEqual(collect.normalize('codex', data), {'used': 9, 'reset': 1900000000})
    def test_claude_zero_and_iso_reset(self):
        self.assertEqual(collect.normalize('claude', {'seven_day': {'utilization': 0, 'resets_at': '2030-01-01T00:00:00Z'}}), {'used': 0, 'reset': 1893456000})
    def test_missing_week_is_unavailable(self):
        with self.assertRaises(ValueError): collect.normalize('codex', {'rate_limit': {'primary_window': {'used_percent': 3, 'limit_window_seconds': 18000}}})
    def test_invalid_percent(self):
        for n in [True, -1, float('nan'), 'token-secret']:
            with self.assertRaises(ValueError): collect.normalize('claude', {'seven_day': {'utilization': n}})
    def test_over_limit_and_bad_reset(self):
        self.assertEqual(collect.normalize('claude', {'seven_day': {'utilization': 110, 'resets_at': 'bad'}}), {'used': 110, 'reset': None})

if __name__ == '__main__': unittest.main()
