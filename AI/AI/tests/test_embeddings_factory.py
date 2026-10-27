import sys
import os
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.API import embeddings


class EmbeddingFactoryTests(unittest.TestCase):
    def test_catalog_names(self):
        names = [e["name"] for e in embeddings.AVAILABLE_EMBEDDINGS]
        self.assertEqual(names, ["baai/bge-m3", "openai/text-embedding-3-small"])
        self.assertTrue(all(e["source"] == "api" for e in embeddings.AVAILABLE_EMBEDDINGS))

    def test_default_is_bge_m3(self):
        self.assertEqual(embeddings.DEFAULT_EMBEDDING_MODEL, "baai/bge-m3")

    def test_bge_m3_is_forced_to_openrouter(self):
        with patch.object(embeddings, "OpenAIEmbeddingModel") as ctor:
            embeddings.create_embedding_model("BAAI/bge-m3")
        ctor.assert_called_once_with(model_id="baai/bge-m3", openrouter_only=True)

    def test_small_keeps_provider_precedence(self):
        with patch.object(embeddings, "OpenAIEmbeddingModel") as ctor:
            embeddings.create_embedding_model("openai/text-embedding-3-small")
        ctor.assert_called_once_with(model_id="text-embedding-3-small", openrouter_only=False)

    def test_unknown_name_raises(self):
        for name in ("openai/ada-002", "openai/text-embedding-3", "openai/text-embedding-3-large"):
            with self.assertRaises(ValueError):
                embeddings.create_embedding_model(name)

    def test_empty_name_raises(self):
        with self.assertRaisesRegex(ValueError, "EMBEDDING_MODEL is empty"):
            embeddings.create_embedding_model("  ")

    def test_bge_m3_wiring_reaches_openrouter_with_prefixed_model(self):
        calls = []

        def create(model, input):
            calls.append(model)
            return types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[0.1, 0.2], index=0)]
            )

        fake_client = MagicMock()
        fake_client.embeddings.create = create
        env = {
            "OPENAI_API_KEY": "sk-x",
            "AZURE_ENDPOINT": "https://x",
            "OPENROUTER_API_KEY": "sk-or",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "AI.Chunking.OpenAI_Embedding.OpenAI", return_value=fake_client
        ) as openai_cls, patch("AI.Chunking.OpenAI_Embedding.AzureOpenAI") as azure_cls:
            embeddings.create_embedding_model("baai/bge-m3").embed_documents(["hi"])

        azure_cls.assert_not_called()
        self.assertEqual(openai_cls.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(calls, ["baai/bge-m3"])
