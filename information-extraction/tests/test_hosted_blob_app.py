import unittest

from tests import test_hosted_app as contract
from tests.test_blob_store import AZURE_AVAILABLE, Backend, FakeContainerClient


@unittest.skipUnless(
    contract.INVOCATIONS_AVAILABLE and AZURE_AVAILABLE, "optional hosted/Blob SDKs not installed",
)
class HostedBlobAppTests(contract.HostedAppTests):
    def make_store(self):
        from information_extraction.blob_store import BlobStore
        if not hasattr(self, "backend"):
            self.backend = Backend()
        return BlobStore(FakeContainerClient(self.backend), prefix="synthetic-http-fixture")
