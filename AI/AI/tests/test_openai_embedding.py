import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.Chunking.OpenAI_Embedding import OpenAIEmbeddingModel


class EmbeddingItem:
    def __init__(self, embedding, index=0):
        self.embedding = embedding
        self.index = index


class FakeEmbeddingsAPI:
    def __init__(self, vectors, reverse=False):
        self.vectors = vectors
        self.reverse = reverse
        self.calls = []

    def create(self, model, input):
        self.calls.append({"model": model, "input": input})
        items = [EmbeddingItem(vector, index) for index, vector in enumerate(self.vectors[: len(input)])]
        return types.SimpleNamespace(data=items[::-1] if self.reverse else items)


class FakeClient:
    def __init__(self, vectors, reverse=False):
        self.embeddings = FakeEmbeddingsAPI(vectors, reverse)


class OpenAIEmbeddingTests(unittest.TestCase):
    def test_uses_openrouter_with_the_openrouter_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}, clear=False), patch(
            "AI.Chunking.OpenAI_Embedding.OpenAI"
        ) as openai_cls:
            model = OpenAIEmbeddingModel(model_id="baai/bge-m3")

        self.assertEqual(openai_cls.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(openai_cls.call_args.kwargs["api_key"], "sk-or-test")
        self.assertIs(model.client, openai_cls.return_value)

    def test_without_key_raises(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                OpenAIEmbeddingModel(model_id="baai/bge-m3")

    def test_embed_documents_returns_vectors_in_input_order(self):
        client = FakeClient([[0.1, 0.2], [0.3, 0.4]], reverse=True)
        model = OpenAIEmbeddingModel(model_id="baai/bge-m3", client=client)

        vectors = model.embed_documents(["hello", "world"])

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(client.embeddings.calls[0]["model"], "baai/bge-m3")

    def test_embed_documents_batches_and_truncates_input(self):
        client = FakeClient([[0.0]] * 64)
        model = OpenAIEmbeddingModel(model_id="baai/bge-m3", client=client)

        vectors = model.embed_documents(["x" * 9000] + [" "] * 64)

        self.assertEqual(len(vectors), 65)
        self.assertEqual([len(call["input"]) for call in client.embeddings.calls], [64, 1])
        self.assertEqual(len(client.embeddings.calls[0]["input"][0]), 8000)
        self.assertEqual(client.embeddings.calls[0]["input"][1], " ")

    def test_provider_failure_raises_without_details(self):
        client = FakeClient([])
        client.embeddings.create = lambda model, input: (_ for _ in ()).throw(ValueError("sk-or-secret"))
        model = OpenAIEmbeddingModel(model_id="baai/bge-m3", client=client)

        with self.assertRaisesRegex(RuntimeError, "^Embedding provider request failed$"):
            model.embed_documents(["hello"])

    def test_wrong_vector_count_raises(self):
        model = OpenAIEmbeddingModel(model_id="baai/bge-m3", client=FakeClient([[0.1]]))

        with self.assertRaisesRegex(RuntimeError, "unexpected vector count"):
            model.embed_documents(["a", "b"])


if __name__ == "__main__":
    unittest.main()
