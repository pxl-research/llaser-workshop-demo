import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

# chromadb is a heavy runtime dependency; stub it when unavailable so ChromaVectorStore imports.
try:
    import chromadb  # noqa: F401
except ImportError:
    chromadb_stub = types.ModuleType("chromadb")
    utils_stub = types.ModuleType("chromadb.utils")
    ef_stub = types.ModuleType("chromadb.utils.embedding_functions")
    setattr(ef_stub, "EmbeddingFunction", object)
    setattr(utils_stub, "embedding_functions", ef_stub)
    setattr(chromadb_stub, "utils", utils_stub)
    setattr(chromadb_stub, "PersistentClient", MagicMock())
    sys.modules["chromadb"] = chromadb_stub
    sys.modules["chromadb.utils"] = utils_stub
    sys.modules["chromadb.utils.embedding_functions"] = ef_stub

from AI.Chunking import Vector_Stores  # noqa: E402
from AI.Chunking.Vector_Stores import ChromaVectorStore, compute_hash, exact_terms  # noqa: E402


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.rows = {}
        self.vector_hits = []

    def query(self, query_texts, n_results, include=None):
        return {"documents": [self.vector_hits[:n_results]]}

    def get(self, where=None, limit=None, include=None, where_document=None):
        needle = where_document["$contains"] if where_document else None
        ids = [
            row_id
            for row_id, (doc, meta) in self.rows.items()
            if (not where or all(meta.get(key) == value for key, value in where.items()))
            and (needle is None or needle in doc)
        ][:limit]
        return {
            "ids": ids,
            "documents": [self.rows[i][0] for i in ids],
            "metadatas": [self.rows[i][1] for i in ids],
        }

    def add(self, documents, metadatas, ids):
        for doc, meta, row_id in zip(documents, metadatas, ids):
            self.rows[row_id] = (doc, meta)

    def delete(self, where=None, ids=None):
        for row_id, (_doc, meta) in list(self.rows.items()):
            if (ids is not None and row_id in ids) or (
                where and all(self._delete_match(meta or {}, key, value) for key, value in where.items())
            ):
                del self.rows[row_id]

    @staticmethod
    def _delete_match(meta, key, value):
        if isinstance(value, dict):  # {"$nin": [...]}: rows lacking the key are kept, like Chroma
            return key in meta and meta[key] not in value["$nin"]
        return meta.get(key) == value

    def count(self):
        return len(self.rows)


class FakeChromaClient:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name, embedding_function=None):
        return self.collections.setdefault(name, FakeCollection(name))


def make_store(client=None):
    with patch.object(Vector_Stores.chromadb, "PersistentClient", return_value=client or FakeChromaClient()):
        return ChromaVectorStore(db_name="documents", embedding_model=MagicMock(), persist_directory="unused")


class ExactTermsTests(unittest.TestCase):
    def test_quoted_phrase(self):
        self.assertEqual(exact_terms('what is "torque limit" here'), ["torque limit"])

    def test_digit_token(self):
        self.assertEqual(exact_terms("price of x200 and iso-9001."), ["x200", "iso-9001"])

    def test_acronym(self):
        self.assertEqual(exact_terms("what does the PLC do"), ["PLC"])

    def test_plain_question_returns_nothing(self):
        self.assertEqual(exact_terms("how does the machine work?"), [])

    def test_short_numbers_are_ignored(self):
        self.assertEqual(exact_terms("explain step 2 of chapter 12 in 2024"), ["2024"])

    def test_capped_at_three(self):
        self.assertEqual(len(exact_terms("A1 B2 C3 D4 E5")), 3)

    def test_deduplicated_in_order(self):
        self.assertEqual(exact_terms("X200 PLC X200 PLC"), ["X200", "PLC"])


class KeywordRetrievalTests(unittest.TestCase):
    def make_store(self, vector_hits, rows):
        store = make_store()
        store.collection.vector_hits = vector_hits
        for i, doc in enumerate(rows):
            store.collection.add([doc], [{}], [f"id{i}"])
        return store

    def test_adds_keyword_chunk_missing_from_vector_hits(self):
        store = self.make_store(["semantic"], ["semantic", "part X200 specs"])

        self.assertEqual(
            store.retrieve_top_chunks("tell me about X200", 3), ["semantic", "part X200 specs"]
        )

    def test_no_duplicates_and_extras_capped_at_five(self):
        rows = ["semantic"] + [f"X200 row {i}" for i in range(9)]
        store = self.make_store(["semantic", "X200 row 0"], rows)

        chunks = store.retrieve_top_chunks("X200?", 10)

        self.assertEqual(len(chunks), len(set(chunks)))
        self.assertEqual(len(chunks), 2 + 5)

    def test_keyword_hits_returned_when_vector_query_is_empty(self):
        store = self.make_store([], ["part X200 specs"])

        self.assertEqual(store.retrieve_top_chunks("X200", 3), ["part X200 specs"])

    def test_keyword_failure_keeps_vector_results(self):
        store = self.make_store(["semantic"], [])
        store.collection.get = MagicMock(side_effect=RuntimeError("boom"))

        self.assertEqual(store.retrieve_top_chunks("X200", 3), ["semantic"])


class ChromaAddDocumentTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.store.collection = MagicMock()
        self.store.collection.get.return_value = {"ids": [], "metadatas": []}

    def make_file(self, tmp_dir: Path, name: str = "doc.txt") -> str:
        path = tmp_dir / name
        path.write_text("hello world")
        return str(path)

    def test_returns_number_of_chunks_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = self.make_file(Path(tmp))

            added = self.store.add_document(file_path, ["a", "b", "c"])

        self.assertEqual(added, 3)
        kwargs = self.store.collection.add.call_args.kwargs
        self.assertEqual(kwargs["documents"], ["a", "b", "c"])
        self.assertEqual(len(kwargs["ids"]), 3)

    def test_returns_zero_when_file_hash_is_already_indexed(self):
        self.store.collection.get.return_value = {
            "ids": ["existing_0"],
            "metadatas": [{"file_path": "/data/old.txt"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            file_path = self.make_file(Path(tmp))

            added = self.store.add_document(file_path, ["a", "b"])

        self.assertEqual(added, 0)
        self.store.collection.add.assert_not_called()

    def test_returns_zero_for_empty_chunks(self):
        self.assertEqual(self.store.add_document("whatever.txt", []), 0)
        self.store.collection.add.assert_not_called()

    def test_raises_runtime_error_chained_when_collection_add_fails(self):
        boom = ValueError("embedding failed")
        self.store.collection.add.side_effect = boom
        with tempfile.TemporaryDirectory() as tmp:
            file_path = self.make_file(Path(tmp))

            with self.assertRaises(RuntimeError) as ctx:
                self.store.add_document(file_path, ["a"])

        self.assertIs(ctx.exception.__cause__, boom)
        self.assertIn("embedding failed", str(ctx.exception))


class ChromaStoreTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeChromaClient()

    def make_store(self):
        return make_store(self.client)

    def test_is_indexed_false_on_empty_true_after_add_false_for_missing_file(self):
        store = self.make_store()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "doc.txt")
            Path(path).write_text("hello world")

            self.assertFalse(store.is_indexed(path))
            store.add_document(path, ["a", "b"])
            self.assertTrue(store.is_indexed(path))
            self.assertFalse(store.is_indexed(str(Path(tmp) / "missing.txt")))

    def test_changed_content_at_same_path_is_replaced_after_prune(self):
        store = self.make_store()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "doc.txt")
            Path(path).write_text("version one")
            self.assertEqual(store.add_document(path, ["a", "b", "c"]), 3)
            Path(path).write_text("version two")

            store.prune_missing({compute_hash(path)})
            self.assertEqual(store.add_document(path, ["x", "y"]), 2)

        rows = self.client.collections["documents"].rows
        self.assertEqual(sorted(doc for doc, _meta in rows.values()), ["x", "y"])

    def test_prune_missing_with_empty_set_empties_the_collection(self):
        store = self.make_store()
        store.collection.add(documents=["a", "b"], metadatas=[{"file_hash": "h"}, {"file_hash": "g"}], ids=["1", "2"])

        store.prune_missing(set())

        self.assertEqual(store.collection.count(), 0)

    def test_prune_keeps_duplicate_content_when_first_copy_changes(self):
        store = self.make_store()
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.txt", Path(tmp) / "b.txt"
            a.write_text("same")
            b.write_text("same")
            self.assertEqual(store.add_document(str(a), ["s1", "s2"]), 2)
            self.assertEqual(store.add_document(str(b), ["s1", "s2"]), 0)
            a.write_text("changed")

            store.prune_missing({compute_hash(str(a)), compute_hash(str(b))})

        rows = self.client.collections["documents"].rows
        self.assertEqual(sorted(doc for doc, _meta in rows.values()), ["s1", "s2"])


if __name__ == "__main__":
    unittest.main()
