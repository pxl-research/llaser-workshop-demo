import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))



class EmbeddingItem:
    def __init__(self, embedding, index=0):
        self.embedding = embedding
        self.index = index


class FakeEmbeddingsAPI:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def create(self, model, input):
        self.calls.append({"model": model, "input": input})
        return types.SimpleNamespace(
            data=[EmbeddingItem(vector, index) for index, vector in enumerate(self.vectors[: len(input)])]
        )


class FakeClient:
    def __init__(self, vectors):
        self.embeddings = FakeEmbeddingsAPI(vectors)


class OpenAIEmbeddingTests(unittest.TestCase):
    def test_uses_openai_client_when_azure_endpoint_is_absent(self):
        fake_client = object()
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "AZURE_ENDPOINT": "", "OPENROUTER_API_KEY": ""},
            clear=False,
        ), patch("AI.Chunking.OpenAI_Embedding.OpenAI", return_value=fake_client) as openai_cls, patch(
            "AI.Chunking.OpenAI_Embedding.AzureOpenAI"
        ) as azure_cls:
            from AI.Chunking.OpenAI_Embedding import create_embedding_client

            client = create_embedding_client()

        self.assertIs(client, fake_client)
        openai_cls.assert_called_once()
        azure_cls.assert_not_called()

    def test_uses_azure_client_when_azure_endpoint_is_set(self):
        fake_client = object()
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "azure-key",
                "AZURE_ENDPOINT": "https://example.openai.azure.com",
            },
            clear=False,
        ), patch("AI.Chunking.OpenAI_Embedding.AzureOpenAI", return_value=fake_client) as azure_cls, patch(
            "AI.Chunking.OpenAI_Embedding.OpenAI"
        ) as openai_cls:
            from AI.Chunking.OpenAI_Embedding import create_embedding_client

            client = create_embedding_client()

        self.assertIs(client, fake_client)
        azure_cls.assert_called_once()
        openai_cls.assert_not_called()

    def test_falls_back_to_openrouter_without_openai_key(self):
        fake_client = object()
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "AZURE_ENDPOINT": "",
                "OPENROUTER_API_KEY": "sk-or-test",
            },
            clear=False,
        ), patch("AI.Chunking.OpenAI_Embedding.OpenAI", return_value=fake_client) as openai_cls:
            from AI.Chunking.OpenAI_Embedding import create_embedding_client

            client = create_embedding_client()

        self.assertIs(client, fake_client)
        kwargs = openai_cls.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "https://openrouter.ai/api/v1")

    def test_embed_documents_batches_and_returns_vectors(self):
        from AI.Chunking.OpenAI_Embedding import OpenAIEmbeddingModel

        client = FakeClient([[0.1, 0.2], [0.3, 0.4]])
        model = OpenAIEmbeddingModel(model_id="text-embedding-3-small", client=client)

        vectors = model.embed_documents(["hello", "world"])

        self.assertEqual(len(vectors), 2)
        self.assertAlmostEqual(vectors[0][0], 0.1, places=5)
        self.assertAlmostEqual(vectors[1][1], 0.4, places=5)
        self.assertEqual(client.embeddings.calls[0]["model"], "text-embedding-3-small")

    def _requested_model(self, env, patched_class, catalog_name="openai/text-embedding-3-small"):
        from AI.API.embeddings import create_embedding_model

        fake_client = FakeClient([[0.1, 0.2]])
        with patch.dict(os.environ, env, clear=False), patch(
            f"AI.Chunking.OpenAI_Embedding.{patched_class}", return_value=fake_client
        ):
            model = create_embedding_model(catalog_name)
            model.embed_documents(["hello"])
        return fake_client.embeddings.calls[0]["model"]

    def test_openrouter_fallback_sends_prefixed_model_id(self):
        env = {"OPENAI_API_KEY": "", "AZURE_ENDPOINT": "", "OPENROUTER_API_KEY": "sk-or-test"}
        self.assertEqual(
            self._requested_model(env, "OpenAI"),
            "openai/text-embedding-3-small",
        )

    def test_openai_client_sends_unprefixed_model_id(self):
        env = {"OPENAI_API_KEY": "sk-test", "AZURE_ENDPOINT": "", "OPENROUTER_API_KEY": "sk-or-test"}
        self.assertEqual(self._requested_model(env, "OpenAI"), "text-embedding-3-small")

    def test_azure_client_sends_unprefixed_model_id(self):
        env = {
            "OPENAI_API_KEY": "azure-key",
            "AZURE_ENDPOINT": "https://example.openai.azure.com",
            "OPENROUTER_API_KEY": "sk-or-test",
        }
        self.assertEqual(self._requested_model(env, "AzureOpenAI"), "text-embedding-3-small")


class OpenRouterOnlyTests(unittest.TestCase):
    def test_openrouter_only_ignores_openai_and_azure(self):
        env = {"OPENROUTER_API_KEY": "sk-or-test", "OPENAI_API_KEY": "sk-x", "AZURE_ENDPOINT": "https://x"}
        with patch.dict(os.environ, env, clear=False), patch(
            "AI.Chunking.OpenAI_Embedding.OpenAI"
        ) as openai_cls, patch("AI.Chunking.OpenAI_Embedding.AzureOpenAI") as azure_cls:
            from AI.Chunking.OpenAI_Embedding import OpenAIEmbeddingModel

            model = OpenAIEmbeddingModel(model_id="baai/bge-m3", openrouter_only=True)

        azure_cls.assert_not_called()
        self.assertEqual(openai_cls.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(openai_cls.call_args.kwargs["api_key"], "sk-or-test")
        self.assertIs(model.client, openai_cls.return_value)
        self.assertEqual(model.request_model_id, "baai/bge-m3")

    def test_openrouter_only_without_key_raises(self):
        env = {"OPENROUTER_API_KEY": "", "OPENAI_API_KEY": "sk-x"}
        with patch.dict(os.environ, env, clear=False):
            from AI.Chunking.OpenAI_Embedding import OpenAIEmbeddingModel

            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                OpenAIEmbeddingModel(model_id="baai/bge-m3", openrouter_only=True)


if __name__ == "__main__":
    unittest.main()
