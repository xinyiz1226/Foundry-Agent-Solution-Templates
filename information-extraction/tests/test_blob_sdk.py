"""Real Azure SDK pipeline over an offline in-memory HTTP transport, not Azure."""

from email.utils import formatdate
from urllib.parse import parse_qs, unquote, urlparse
import unittest
import xml.etree.ElementTree as ET

from information_extraction import Blocked, Execution, Status
from information_extraction.sample import synthetic_plan
from tests.test_blob_store import AZURE_AVAILABLE, Backend, SyntheticModel

if AZURE_AVAILABLE:
    from azure.core.exceptions import ServiceResponseError
    from azure.core.pipeline.transport import HttpResponse, HttpTransport
    from azure.core.utils import case_insensitive_dict
    from azure.storage.blob import ContainerClient
    from information_extraction.blob_store import BlobStore

    class Stream:
        def __init__(self, body):
            self.iterator = iter((body,))
            self.content_length = len(body)

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.iterator)

    class Response(HttpResponse):
        def __init__(self, request, status, body=b"", headers=None):
            super().__init__(request, None)
            self.status_code = status
            self.reason = "fixture"
            self._body = body
            self.headers = case_insensitive_dict({
                "content-length": str(len(body)),
                "content-type": "application/octet-stream",
                "etag": '"fixture-etag"',
                "last-modified": formatdate(0, usegmt=True),
                "x-ms-blob-type": "BlockBlob",
                **(headers or {}),
            })
            self.content_type = self.headers["content-type"]

        def body(self):
            return self._body

        def stream_download(self, pipeline, **kwargs):
            return Stream(self._body)

    class MemoryTransport(HttpTransport):
        def __init__(self):
            self.backend = Backend()
            self.requests = []
            self.claim_outcome = None

        def open(self):
            pass

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def send(self, request, **kwargs):
            self.requests.append(request)
            url = urlparse(request.url)
            query = parse_qs(url.query)
            name = unquote(url.path).split("/", 2)[-1]
            if query.get("comp") == ["list"]:
                root = ET.Element("EnumerationResults")
                blobs = ET.SubElement(root, "Blobs")
                for key, value in sorted(self.backend.blobs.items()):
                    if key.startswith(query.get("prefix", [""])[0]):
                        entry = ET.SubElement(blobs, "Blob")
                        ET.SubElement(entry, "Name").text = key
                        properties = ET.SubElement(entry, "Properties")
                        ET.SubElement(properties, "Content-Length").text = str(len(value))
                        ET.SubElement(properties, "BlobType").text = "BlockBlob"
                ET.SubElement(root, "NextMarker")
                return Response(request, 200, ET.tostring(root), {"content-type": "application/xml"})
            if request.method == "PUT":
                if name in self.backend.blobs:
                    return Response(request, 409, headers={"x-ms-error-code": "BlobAlreadyExists"})
                self.backend.blobs[name] = request.body
                if "/claims/" in name:
                    if self.claim_outcome == "timeout":
                        raise ServiceResponseError("offline_unknown_outcome")
                    if self.claim_outcome == "exists":
                        return Response(request, 409, headers={"x-ms-error-code": "BlobAlreadyExists"})
                    if self.claim_outcome == "condition":
                        return Response(request, 412, headers={"x-ms-error-code": "ConditionNotMet"})
                return Response(request, 201)
            if name not in self.backend.blobs:
                return Response(request, 404, headers={"x-ms-error-code": "BlobNotFound"})
            data = self.backend.blobs[name]
            if request.method == "HEAD":
                return Response(request, 200, headers={"content-length": str(len(data))})
            if request.method == "GET":
                return Response(request, 206, data, {
                    "content-range": f"bytes 0-{len(data) - 1}/{len(data)}",
                })
            raise AssertionError("unexpected_offline_http_method")


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class BlobSDKContractTests(unittest.TestCase):
    def execution(self):
        transport = MemoryTransport()
        # Deliberately leave the SDK retry policy at its nonzero default.
        client = ContainerClient(
            "https://example.invalid", "fixture", credential=None, transport=transport,
        )
        self.addCleanup(client.close)
        model = SyntheticModel()
        return Execution(BlobStore(client, prefix="offline"), model), model, transport

    def test_actual_sdk_sets_create_only_and_conditional_bounded_download_headers(self):
        execution, model, transport = self.execution()
        initial = execution.create("job", synthetic_plan(), "create")
        result = execution.advance("job", 0, "advance")
        self.assertEqual(execution.read("job"), result)
        self.assertEqual(execution.create("job", synthetic_plan(), "create"), initial)
        self.assertEqual(execution.advance("job", 0, "advance"), result)
        self.assertEqual(len(model.calls), 1)
        writes = [r for r in transport.requests if r.method == "PUT"]
        reads = [r for r in transport.requests if r.method == "GET" and "comp=list" not in r.url]
        self.assertTrue(writes)
        self.assertTrue(reads)
        self.assertTrue(all(r.headers.get("If-None-Match") == "*" for r in writes))
        self.assertTrue(all(r.headers.get("If-Match") == '"fixture-etag"' for r in reads))
        self.assertTrue(all(r.headers.get("x-ms-range", "").startswith("bytes=0-") for r in reads))

    def test_claim_timeout_and_existing_response_never_retry_or_grant_ownership(self):
        for outcome, error in (
            ("timeout", ServiceResponseError), ("exists", Blocked), ("condition", Blocked),
        ):
            with self.subTest(outcome=outcome):
                execution, model, transport = self.execution()
                execution.create("job", synthetic_plan(), "create")
                transport.claim_outcome = outcome
                with self.assertRaises(error):
                    execution.advance("job", 0, "advance")
                self.assertEqual(len([r for r in transport.requests
                                     if r.method == "PUT" and "/claims/" in r.url]), 1)
                self.assertEqual(execution.read("job").status, Status.IN_PROGRESS)
                with self.assertRaises(Blocked):
                    execution.advance("job", 0, "advance")
                self.assertEqual(model.calls, [])
