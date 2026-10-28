import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

AI_DIR = PACKAGE_PARENT / "AI"


def stub_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def load_source(module_name: str, relative_path: str, stubs: dict) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, AI_DIR / relative_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


CHROMA_STUBS = {
    "chromadb": stub_module("chromadb", PersistentClient=MagicMock()),
    "chromadb.utils": stub_module(
        "chromadb.utils",
        embedding_functions=stub_module("chromadb.utils.embedding_functions", EmbeddingFunction=object),
    ),
}
VECTOR_STORES = load_source("AI.Chunking.Vector_Stores_session_test", "Chunking/Vector_Stores.py", CHROMA_STUBS)
SESSION_MEMORY = load_source(
    "AI.API.SessionMemory_session_test",
    "API/SessionMemory.py",
    {**CHROMA_STUBS, "AI.Chunking.Vector_Stores": VECTOR_STORES},
)


class FakeClient:
    """Chroma client double that hands out one stable collection per name."""

    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name, embedding_function=None):
        return self.collections.setdefault(name, MagicMock(name=name))


class SessionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        patcher = patch.object(VECTOR_STORES.chromadb, "PersistentClient", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uses_the_session_memory_collection(self):
        SESSION_MEMORY.SessionMemory(MagicMock(), session_id="s1")

        self.assertEqual(list(self.client.collections), ["session_memory"])

    def test_recent_turns_are_the_newest_n_oldest_first(self):
        memory = SESSION_MEMORY.SessionMemory(MagicMock(), session_id="s1")
        collection = memory.vector_store.collection
        collection.get.return_value = {
            "metadatas": [
                {"timestamp": "2026-01-01", "question": "a", "answer": "1", "doc_id": "id-a"},
                {"timestamp": "2026-03-01", "question": "c", "answer": "3", "doc_id": "id-c"},
                {"timestamp": "2026-02-01", "question": "b", "answer": "2", "doc_id": "id-b"},
            ],
        }

        turns = memory.get_recent_turns(2)

        self.assertEqual(turns, [
            {"question": "b", "answer": "2", "doc_id": "id-b"},
            {"question": "c", "answer": "3", "doc_id": "id-c"},
        ])
        self.assertEqual(collection.get.call_args.kwargs["where"], {"session_id": "s1"})

    def test_recent_turns_without_session_is_empty(self):
        memory = SESSION_MEMORY.SessionMemory(MagicMock(), session_id=None)

        self.assertEqual(memory.get_recent_turns(6), [])

    def test_retrieve_context_skips_excluded_turns(self):
        memory = SESSION_MEMORY.SessionMemory(MagicMock(), session_id="s1")
        memory.vector_store.collection.query.return_value = {
            "documents": [["Q: recent\nA: r", "Q: old\nA: o"]],
            "metadatas": [[{"doc_id": "id-recent", "timestamp": "t2"}, {"doc_id": "id-old", "timestamp": "t1"}]],
            "distances": [[0.1, 0.1]],
        }

        result = memory.retrieve_context("q", k=3, min_similarity=0.5, exclude_ids={"id-recent"})

        self.assertIn("Q: old", result)
        self.assertNotIn("Q: recent", result)
        # Ask for extra rows, so excluding recent turns still leaves k older ones.
        self.assertEqual(memory.vector_store.collection.query.call_args.kwargs["n_results"], 4)


if __name__ == "__main__":
    unittest.main()
