import unittest

from tests import test_hosted_app as contract
from tests.test_blob_store import AZURE_AVAILABLE, Backend, FakeContainerClient


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class BlobHostedAppTests(contract.HostedAppTests):
    async def asyncSetUp(self):
        self.backend = Backend()
        await super().asyncSetUp()

    def make_store(self):
        from information_extraction.blob_store import BlobStore

        return BlobStore(FakeContainerClient(self.backend), prefix="hosted-fixture")
