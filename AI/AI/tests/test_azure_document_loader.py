import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


ENDPOINT = "https://example.cognitiveservices.azure.com"
KEY = "di-secret-value"
DEDICATED_ENV = {
    "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": ENDPOINT,
    "AZURE_DOCUMENT_INTELLIGENCE_KEY": KEY,
}
ALL_CONFIG_VARS = (
    "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
    "AZURE_DOCUMENT_INTELLIGENCE_KEY",
    "AZURE_DOCUMENT_INTELLIGENCE_TIMEOUT",
    "AZURE_ENDPOINT",
    "OPENAI_API_KEY",
)


def sdk_stubs(client_cls, credential_cls):
    """Stub modules so the loader imports without the Azure SDK or network."""
    modules = {}
    for name in ("azure", "azure.ai", "azure.core"):
        modules[name] = types.ModuleType(name)
    di = types.ModuleType("azure.ai.documentintelligence")
    di.DocumentIntelligenceClient = client_cls
    credentials = types.ModuleType("azure.core.credentials")
    credentials.AzureKeyCredential = credential_cls
    modules["azure.ai.documentintelligence"] = di
    modules["azure.core.credentials"] = credentials
    return modules


def make_client_cls(content="# Title\n\n| a | b |", error=None):
    poller = MagicMock()
    if error is None:
        poller.result.return_value = types.SimpleNamespace(content=content)
    else:
        poller.result.side_effect = error
    client = MagicMock()
    client.begin_analyze_document.return_value = poller
    return MagicMock(return_value=client), client, poller


class AzureDocumentLoaderTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {name: "" for name in ALL_CONFIG_VARS}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.client_cls, self.client, self.poller = make_client_cls()
        self.credential_cls = MagicMock()
        sdk = patch.dict(sys.modules, sdk_stubs(self.client_cls, self.credential_cls))
        sdk.start()
        self.addCleanup(sdk.stop)
        doc = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        doc.write(b"%PDF-fake")
        doc.close()
        self.addCleanup(os.unlink, doc.name)
        self.doc_path = doc.name

    def _loader(self, env=None, **kwargs):
        from AI.Chunking.AzureDocument_Loader import AzureDocumentIntelligenceLoader

        with patch.dict(os.environ, DEDICATED_ENV if env is None else env, clear=False):
            return AzureDocumentIntelligenceLoader(**kwargs)

    def _load(self, env=None, **kwargs):
        loader = self._loader(env, **kwargs)
        return loader.load_document(self.doc_path)

    def test_missing_endpoint_fails_closed_naming_variable_only(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._loader({"AZURE_DOCUMENT_INTELLIGENCE_KEY": KEY})

        message = str(ctx.exception)
        self.assertIn("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", message)
        self.assertNotIn("AZURE_DOCUMENT_INTELLIGENCE_KEY", message)
        self.assertNotIn(KEY, message)

    def test_missing_key_fails_closed_naming_variable_only(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._loader({"AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": ENDPOINT})

        message = str(ctx.exception)
        self.assertIn("AZURE_DOCUMENT_INTELLIGENCE_KEY", message)
        self.assertNotIn(ENDPOINT, message)

    def test_legacy_embedder_variables_do_not_satisfy_loader(self):
        legacy = {"AZURE_ENDPOINT": ENDPOINT, "OPENAI_API_KEY": KEY}

        with self.assertRaises(RuntimeError) as ctx:
            self._loader(legacy)

        message = str(ctx.exception)
        self.assertIn("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", message)
        self.assertIn("AZURE_DOCUMENT_INTELLIGENCE_KEY", message)
        self.assertNotIn(KEY, message)
        self.client_cls.assert_not_called()

    def test_client_built_once_from_dedicated_credentials(self):
        loader = self._loader()
        loader.load_document(self.doc_path)
        loader.load_document(self.doc_path)

        self.client_cls.assert_called_once()
        self.assertEqual(self.client_cls.call_args.kwargs["endpoint"], ENDPOINT)
        self.credential_cls.assert_called_once_with(KEY)

    def test_constructor_arguments_override_environment(self):
        self._loader(endpoint="https://override.example", key="override-key")

        self.assertEqual(self.client_cls.call_args.kwargs["endpoint"], "https://override.example")
        self.credential_cls.assert_called_once_with("override-key")

    def test_markdown_content_returned_as_single_item_list(self):
        self.assertEqual(self._load(), ["# Title\n\n| a | b |"])

    def test_requests_markdown_with_prebuilt_layout(self):
        self._load()

        kwargs = self.client.begin_analyze_document.call_args.kwargs
        self.assertEqual(kwargs["model_id"], "prebuilt-layout")
        self.assertEqual(kwargs["output_content_format"], "markdown")
        self.assertEqual(kwargs["body"], b"%PDF-fake")

    def test_empty_content_returns_empty_list(self):
        for content in ("", None):
            with self.subTest(content=content):
                self.poller.result.return_value = types.SimpleNamespace(content=content)
                self.assertEqual(self._load(), [])

    def test_timeout_defaults_to_300_seconds(self):
        self._load()

        self.poller.result.assert_called_once_with(timeout=300)

    def test_timeout_env_is_honored(self):
        self._load({**DEDICATED_ENV, "AZURE_DOCUMENT_INTELLIGENCE_TIMEOUT": "45"})

        self.poller.result.assert_called_once_with(timeout=45)

    def test_sdk_error_is_logged_without_secrets_and_reraised(self):
        self.poller.result.side_effect = ValueError("analysis failed")

        with self.assertLogs("AI.Chunking.AzureDocument_Loader", level="ERROR") as logs:
            with self.assertRaises(ValueError):
                self._load()

        output = "\n".join(logs.output)
        self.assertIn(os.path.basename(self.doc_path), output)
        self.assertNotIn(KEY, output)


if __name__ == "__main__":
    unittest.main()
