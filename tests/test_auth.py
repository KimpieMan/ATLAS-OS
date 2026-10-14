import json
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from atlas.auth import ChatGPT, AUTH, PLAN_SCOPE


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.auth = ChatGPT(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_pkce_host_stability_state_and_client_id(self):
        query = parse_qs(urlparse(self.auth.start()).query)
        self.assertEqual(query['client_id'], ['dynamic_agent_client'])
        self.assertEqual(query['redirect_uri'], ['http://127.0.0.1:8080/auth/callback'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertIn(PLAN_SCOPE, query['scope'][0])
        reopened = ChatGPT(self.temp.name)
        self.assertEqual(self.auth.state['host'], reopened.state['host'])
        with self.assertRaises(ValueError):
            self.auth.callback({'state': 'wrong', 'code': 'ignored'})
        with self.assertRaises(ValueError):
            self.auth.callback({'state': query['state'][0], 'code': 'ignored'})

    def signed_callback(self, nonce_override=None):
        query = parse_qs(urlparse(self.auth.start()).query)
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = {'iss': AUTH, 'sub': 'user1', 'aud': 'issued-client', 'exp': int(time.time()) + 300,
                  'nonce': nonce_override or query['nonce'][0], 'email': 'test@example.com'}
        id_token = jwt.encode(claims, private, algorithm='RS256')
        response = Mock(ok=True)
        response.json.return_value = {'access_token': 'access-secret', 'refresh_token': 'refresh-secret',
                                     'id_token': id_token, 'expires_in': 3600, 'scope': PLAN_SCOPE}
        self.auth.metadata = {'issuer': AUTH, 'jwks_uri': AUTH + '/jwks'}
        with patch.object(self.auth.http, 'post', return_value=response), patch('atlas.auth.jwt.PyJWKClient') as jwks:
            jwks.return_value.get_signing_key_from_jwt.return_value.key = private.public_key()
            self.auth.callback({'state': query['state'][0], 'code': 'code', 'client_id': 'issued-client'})

    def test_signed_identity_and_encrypted_storage(self):
        self.signed_callback()
        self.assertEqual(self.auth.token(), 'access-secret')
        self.assertEqual(self.auth.state['active'], 'issued-client')
        self.assertNotIn(b'access-secret', self.auth.path.read_bytes())
        public = json.dumps(self.auth.public_accounts())
        self.assertNotIn('access-secret', public)
        self.assertNotIn('refresh-secret', public)
        self.assertEqual(ChatGPT(self.temp.name).token(), 'access-secret')

    def test_wrong_nonce_does_not_activate(self):
        with self.assertRaises(ValueError):
            self.signed_callback('wrong-nonce')
        self.assertIsNone(self.auth.state['active'])

    def test_stream_must_complete(self):
        self.auth.token = Mock(return_value='access')
        response = Mock(ok=True)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_lines.return_value = iter(['data: {"type":"response.output_text.delta","delta":"Partial"}', ''])
        with patch.object(self.auth.http, 'post', return_value=response):
            with self.assertRaises(ValueError):
                self.auth.respond('test', 'Hello', {}, [])
        response.iter_lines.return_value = iter(['data: {"type":"response.completed","response":{"status":"completed","output":[]}}', ''])
        with patch.object(self.auth.http, 'post', return_value=response) as post:
            self.assertEqual(self.auth.respond('test', 'Hello', {}, []), [])
            self.assertFalse(post.call_args.kwargs['json']['store'])
            self.assertTrue(post.call_args.kwargs['json']['stream'])

    def test_refresh_and_logout_keep_registration(self):
        self.signed_callback()
        self.auth.state['accounts']['issued-client']['expires_at'] = 0
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {'access_token': 'new-secret', 'refresh_token': 'rotated', 'expires_in': 3600}
        with patch.object(self.auth.http, 'post', return_value=response):
            self.assertEqual(self.auth.token(), 'new-secret')
        self.assertEqual(self.auth.state['accounts']['issued-client']['refresh_token'], 'rotated')
        self.auth.metadata['revocation_endpoint'] = AUTH + '/revoke'
        with patch.object(self.auth.http, 'post', return_value=response):
            self.assertTrue(self.auth.logout())
        self.assertIn('issued-client', self.auth.state['accounts'])
        self.assertNotIn('access_token', self.auth.state['accounts']['issued-client'])


if __name__ == '__main__':
    unittest.main()
