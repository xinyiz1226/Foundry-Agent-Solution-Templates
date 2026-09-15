"""Ephemeral keys for the external Entra signing-key/ID-token test contract."""

import json


TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
OPERATOR = "33333333-3333-4333-8333-333333333333"
NOW = 2_000_000_000


class SignedIdentity:
    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from jwt.algorithms import RSAAlgorithm

        self.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = json.loads(RSAAlgorithm.to_jwk(self.signing_key.public_key()))
        self.public_key.update(kid="test-key", use="sig", alg="RS256")

    def token(self, **overrides):
        import jwt

        claims = {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": CLIENT, "tid": TENANT, "oid": OPERATOR, "ver": "2.0",
            "sub": "test-subject", "iat": NOW - 10, "nbf": NOW - 10, "exp": NOW + 3600,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.signing_key, algorithm="RS256", headers={"kid": "test-key"})
