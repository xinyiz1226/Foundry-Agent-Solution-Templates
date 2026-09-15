"""Authorize real signed identity fixtures through the external JWKS seam."""

import importlib.util
import base64
import unittest

from tests.auth_fixtures import CLIENT, NOW, OPERATOR, TENANT, SignedIdentity

AVAILABLE = all(importlib.util.find_spec(name) for name in ("jwt", "httpx", "cryptography"))


@unittest.skipUnless(AVAILABLE, "optional cloud-workbench dependencies unavailable")
class OperatorAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = SignedIdentity()
        cls.public_key = cls.identity.public_key

    def setUp(self):
        self.now = NOW
        self.requests = []

    def token(self, **overrides):
        return self.identity.token(**overrides)

    def authorizer(self):
        import httpx
        from information_extraction.workbench_auth import OperatorAuthorizer, OperatorPolicy

        def respond(request):
            self.requests.append(request)
            return httpx.Response(200, json={"keys": [self.public_key]})

        auth = OperatorAuthorizer(
            OperatorPolicy(TENANT, CLIENT, OPERATOR),
            transport=httpx.MockTransport(respond), clock=lambda: self.now,
        )
        self.addCleanup(auth.close)
        return auth

    def test_only_the_signed_named_operator_can_read_or_act(self):
        from information_extraction.workbench_auth import AuthorizationError

        auth = self.authorizer()
        self.assertIsNone(auth.authorize([self.token()]))
        with self.assertRaises(AuthorizationError):
            auth.authorize([self.token(oid="44444444-4444-4444-8444-444444444444")])
        self.assertEqual(
            str(self.requests[0].url),
            "https://login.microsoftonline.com/11111111-1111-4111-8111-111111111111/discovery/v2.0/keys",
        )

    def test_open_session_does_not_renew_proof_and_key_reads_are_cached(self):
        from information_extraction.workbench_auth import AuthorizationError

        auth = self.authorizer()
        token = self.token()
        auth.authorize([token])
        self.now += 10
        auth.authorize([token])
        self.assertEqual(len(self.requests), 1)
        self.now = NOW + 890
        with self.assertRaisesRegex(AuthorizationError, "expired"):
            auth.authorize([token])
        self.assertIsNone(auth.authorize([self.token(iat=self.now, nbf=self.now)]))

    def test_untrusted_headers_and_invalid_claims_fail_closed_without_leaking_tokens(self):
        import jwt
        from information_extraction.workbench_auth import AuthorizationError

        auth = self.authorizer()
        invalid_tokens = [
            self.token(iss="https://attacker.example"), self.token(tid=CLIENT),
            self.token(aud=TENANT), self.token(aud=[CLIENT]), self.token(ver="1.0"),
            self.token(iat=NOW + 1), self.token(nbf=NOW + 1), self.token(exp=NOW),
            self.token(iat=True), self.token(exp="9999999999"), self.token(nbf=None),
            self.token(oid=None),
            jwt.encode({"oid": OPERATOR}, key=None, algorithm="none"),
            jwt.encode(
                {"oid": OPERATOR, "aud": CLIENT}, "a" * 32, algorithm="HS256",
                headers={"kid": "test-key"},
            ),
        ]
        for headers in ([], ["not-a-token"], [self.token(), self.token()], *([t] for t in invalid_tokens)):
            with self.subTest(headers_count=len(headers)):
                with self.assertRaises(AuthorizationError) as failure:
                    auth.authorize(headers)
                for token in headers:
                    self.assertNotIn(token, str(failure.exception))
        self.assertEqual(len(self.requests), 1)

    def test_signature_is_verified_not_just_the_header_or_claims(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        import jwt
        from information_extraction.workbench_auth import AuthorizationError

        claims = jwt.decode(self.token(), options={"verify_signature": False})
        foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(claims, foreign_key, algorithm="RS256", headers={"kid": "test-key"})
        with self.assertRaises(AuthorizationError):
            self.authorizer().authorize([forged])

    def test_rejected_key_reads_are_not_repeated_by_every_poll(self):
        import httpx
        from information_extraction.workbench_auth import AuthorizationError, OperatorAuthorizer, OperatorPolicy

        def unavailable(request):
            self.requests.append(request)
            return httpx.Response(503, text="private provider response")

        with_auth = OperatorAuthorizer(
            OperatorPolicy(TENANT, CLIENT, OPERATOR), clock=lambda: self.now,
            transport=httpx.MockTransport(unavailable),
        )
        self.addCleanup(with_auth.close)
        for _ in range(3):
            with self.assertRaises(AuthorizationError) as failure:
                with_auth.authorize([self.token()])
            self.assertNotIn("private provider response", str(failure.exception))
        self.assertEqual(len(self.requests), 1)

    def test_expired_keys_are_not_a_success_fallback_during_an_issuer_outage(self):
        import httpx
        from information_extraction.workbench_auth import AuthorizationError, OperatorAuthorizer, OperatorPolicy

        responses = iter([
            httpx.Response(200, json={"keys": [self.public_key]}),
            httpx.Response(503),
            httpx.Response(200, json={"keys": [self.public_key]}),
        ])
        auth = OperatorAuthorizer(
            OperatorPolicy(TENANT, CLIENT, OPERATOR), clock=lambda: self.now,
            transport=httpx.MockTransport(lambda _: next(responses)),
        )
        self.addCleanup(auth.close)
        auth.authorize([self.token()])
        self.now += 301
        with self.assertRaises(AuthorizationError):
            auth.authorize([self.token()])
        with self.assertRaises(AuthorizationError):
            auth.authorize([self.token()])
        self.now += 30
        self.assertIsNone(auth.authorize([self.token()]))

    def test_malformed_key_sets_redirects_and_foreign_key_issuers_are_rejected(self):
        import httpx
        from information_extraction.workbench_auth import AuthorizationError, OperatorAuthorizer, OperatorPolicy

        replies = [
            httpx.Response(302, headers={"location": "https://attacker.example"}),
            httpx.Response(200, text="{" + " " * 65536 + "}"),
            httpx.Response(200, json={"keys": None}),
            httpx.Response(200, json={"keys": [None]}),
            httpx.Response(200, json={"keys": [self.public_key, self.public_key]}),
            httpx.Response(200, json={"keys": [{**self.public_key, "issuer": "https://attacker.example"}]}),
            httpx.Response(200, text='{"keys":' + "[" * 1500 + "0" + "]" * 1500 + "}"),
        ]
        for reply in replies:
            with self.subTest(status=reply.status_code):
                auth = OperatorAuthorizer(
                    OperatorPolicy(TENANT, CLIENT, OPERATOR), clock=lambda: self.now,
                    transport=httpx.MockTransport(lambda _: reply),
                )
                self.addCleanup(auth.close)
                with self.assertRaises(AuthorizationError):
                    auth.authorize([self.token()])

    def test_token_supplied_key_urls_never_choose_the_key_server(self):
        import jwt

        claims = jwt.decode(self.token(), options={"verify_signature": False})
        token = jwt.encode(
            claims, self.identity.signing_key, algorithm="RS256",
            headers={"kid": "test-key", "jku": "https://attacker.example", "x5u": "https://attacker.example"},
        )
        self.authorizer().authorize([token])
        self.assertEqual([r.url.host for r in self.requests], ["login.microsoftonline.com"])
        self.assertTrue(all("authorization" not in r.headers and token not in str(r.url) for r in self.requests))

    def test_policy_is_explicit_and_cannot_disable_the_time_limit(self):
        from information_extraction.workbench_auth import AuthorizationError, OperatorPolicy

        for maximum in (0, True, 59, 3601, float("inf")):
            with self.subTest(maximum=maximum), self.assertRaises(AuthorizationError):
                OperatorPolicy(TENANT, CLIENT, OPERATOR, maximum)
        for tenant in ("common", "", TENANT.replace("-", "")):
            with self.subTest(tenant=tenant), self.assertRaises(AuthorizationError):
                OperatorPolicy(tenant, CLIENT, OPERATOR)

    def test_excessively_nested_token_json_is_a_safe_denial(self):
        from information_extraction.workbench_auth import AuthorizationError

        header = b'{"nested":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}"
        encoded = base64.urlsafe_b64encode(header).rstrip(b"=").decode()
        with self.assertRaises(AuthorizationError):
            self.authorizer().authorize([encoded + ".e30.AA"])
