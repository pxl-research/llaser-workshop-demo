import re
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
from AI.Chunking.Vector_Stores import (  # noqa: E402
    ChromaVectorStore,
    collection_name,
    compute_hash,
    drop_legacy_collections,
    exact_terms,
    migrate_legacy_collection,
)

CHROMA_NAME_RULE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]{1,510})[a-zA-Z0-9]$")


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
        self.deleted = []

    def get_or_create_collection(self, name, embedding_function=None):
        return self.collections.setdefault(name, FakeCollection(name))

    def delete_collection(self, name):
        self.deleted.append(name)
        self.collections.pop(name, None)


class CollectionNameTests(unittest.TestCase):
    def test_slug_for_openai_model(self):
        self.assertEqual(
            collection_name("rag", "openai/text-embedding-3-small"),
            "rag_v2_openai-text-embedding-3-small",
        )

    def test_slug_for_bge_model(self):
        self.assertEqual(collection_name("rag", "baai/bge-m3"), "rag_v2_baai-bge-m3")

    def test_session_memory_prefix(self):
        self.assertEqual(
            collection_name("session_memory", "baai/bge-m3"), "session_memory_v2_baai-bge-m3"
        )

    def test_weird_name_collapses_runs_and_strips_dashes(self):
        name = collection_name("rag", "  --BAAI//BGE_M3 v1.5!!  ")

        self.assertEqual(name, "rag_v2_baai-bge-m3-v1-5")
        self.assertRegex(name, CHROMA_NAME_RULE)

    def test_very_long_name_still_satisfies_chroma_rules(self):
        name = collection_name("session_memory", "a-" * 400)

        self.assertLessEqual(len(name), 512)
        self.assertRegex(name, CHROMA_NAME_RULE)

    def test_name_without_usable_characters_is_rejected(self):
        for bad in ("", None, "///", " -- "):
            with self.assertRaises(ValueError):
                collection_name("rag", bad)


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
        store = ChromaVectorStore(db_name="docs", embedding_model=MagicMock())
        store.collection = FakeCollection("docs")
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
        self.store = ChromaVectorStore(db_name="docs", embedding_model=MagicMock())
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


class PerModelCollectionTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeChromaClient()
        patcher = patch.object(Vector_Stores.chromadb, "PersistentClient", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_store(self, model_name):
        store = ChromaVectorStore(
            db_name=collection_name("rag", model_name), embedding_model=MagicMock()
        )
        store.connect()
        store.create()
        return store

    def test_same_file_is_indexed_again_under_another_model(self):
        store_a = self.make_store("openai/text-embedding-3-small")
        store_b = self.make_store("baai/bge-m3")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "doc.txt")
            Path(path).write_text("hello world")

            self.assertEqual(store_a.add_document(path, ["a", "b"]), 2)
            self.assertEqual(store_a.add_document(path, ["a", "b"]), 0)
            self.assertEqual(store_b.add_document(path, ["a", "b"]), 2)

        self.assertEqual(
            sorted(self.client.collections),
            ["rag_v2_baai-bge-m3", "rag_v2_openai-text-embedding-3-small"],
        )
        self.assertEqual(self.client.collections["rag_v2_baai-bge-m3"].count(), 2)
        self.assertEqual(self.client.collections["rag_v2_openai-text-embedding-3-small"].count(), 2)

    def test_is_indexed_false_on_empty_true_after_add_false_for_missing_file(self):
        store = self.make_store("baai/bge-m3")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "doc.txt")
            Path(path).write_text("hello world")

            self.assertFalse(store.is_indexed(path))
            store.add_document(path, ["a", "b"])
            self.assertTrue(store.is_indexed(path))
            self.assertFalse(store.is_indexed(str(Path(tmp) / "missing.txt")))

    def test_changed_content_at_same_path_is_replaced_after_prune(self):
        store = self.make_store("baai/bge-m3")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "doc.txt")
            Path(path).write_text("version one")
            self.assertEqual(store.add_document(path, ["a", "b", "c"]), 3)
            Path(path).write_text("version two")

            store.prune_missing({compute_hash(path)})
            self.assertEqual(store.add_document(path, ["x", "y"]), 2)

        rows = self.client.collections["rag_v2_baai-bge-m3"].rows
        self.assertEqual(sorted(doc for doc, _meta in rows.values()), ["x", "y"])

    def test_prune_missing_with_empty_set_empties_the_collection(self):
        store = self.make_store("baai/bge-m3")
        store.collection.add(documents=["a", "b"], metadatas=[{"file_hash": "h"}, {"file_hash": "g"}], ids=["1", "2"])

        store.prune_missing(set())

        self.assertEqual(store.collection.count(), 0)

    def test_prune_keeps_duplicate_content_when_first_copy_changes(self):
        store = self.make_store("baai/bge-m3")
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.txt", Path(tmp) / "b.txt"
            a.write_text("same")
            b.write_text("same")
            self.assertEqual(store.add_document(str(a), ["s1", "s2"]), 2)
            self.assertEqual(store.add_document(str(b), ["s1", "s2"]), 0)
            a.write_text("changed")

            store.prune_missing({compute_hash(str(a)), compute_hash(str(b))})

        rows = self.client.collections["rag_v2_baai-bge-m3"].rows
        self.assertEqual(sorted(doc for doc, _meta in rows.values()), ["s1", "s2"])

    def test_use_collection_switches_without_resetting_the_previous_one(self):
        store = self.make_store("openai/text-embedding-3-small")
        store.collection.add(documents=["doc"], metadatas=[{"file_hash": "h"}], ids=["1"])
        new_embedder = MagicMock()

        store.use_collection(collection_name("rag", "baai/bge-m3"), new_embedder)

        self.assertEqual(store.db_name, "rag_v2_baai-bge-m3")
        self.assertEqual(store.collection.name, "rag_v2_baai-bge-m3")
        self.assertIs(store.embedding_model, new_embedder)
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.client.collections["rag_v2_openai-text-embedding-3-small"].count(), 1)


class LegacyFakeCollection:
    def __init__(self, name, ids=(), docs=(), metas=()):
        self.name, self.ids, self.docs, self.metas = name, list(ids), list(docs), list(metas)
        self.add_sizes = []
        self.fail_on_add_call = None

    def count(self):
        return len(self.ids)

    def get(self, ids=None, include=None, limit=None, offset=0):
        idx = [i for i, row_id in enumerate(self.ids) if ids is None or row_id in ids]
        idx = idx[offset:]
        if limit is not None:
            idx = idx[:limit]
        return {
            "ids": [self.ids[i] for i in idx],
            "documents": [self.docs[i] for i in idx],
            "metadatas": [self.metas[i] for i in idx],
        }

    def add(self, ids, documents, metadatas):
        self.add_sizes.append(len(ids))
        if self.fail_on_add_call == len(self.add_sizes):
            raise RuntimeError("add failed")
        self.ids += ids
        self.docs += documents
        self.metas += metadatas


class LegacyFakeClient:
    def __init__(self, *collections):
        self.collections = {c.name: c for c in collections}

    def list_collections(self):
        return list(self.collections.values())

    def get_collection(self, name, **kwargs):
        return self.collections[name]

    def delete_collection(self, name):
        del self.collections[name]


class LegacyMigrationTests(unittest.TestCase):
    def make_store(self, client, target):
        return types.SimpleNamespace(client=client, collection=target, db_name=target.name)

    def test_copies_legacy_chunks_into_empty_v2_collection(self):
        legacy = LegacyFakeCollection("rag_baai-bge-m3", ["f1_0"], ["chunk"], [{"file_hash": "h"}])
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(legacy, target), target)

        moved = migrate_legacy_collection(store, "rag", "baai/bge-m3")

        self.assertEqual(moved, 1)
        self.assertEqual(target.docs, ["chunk"])
        self.assertEqual(target.metas, [{"file_hash": "h"}])

    def test_copies_only_ids_missing_from_v2(self):
        legacy = LegacyFakeCollection(
            "rag_baai-bge-m3", ["a", "b", "c"], ["x", "y", "z"], [{}, {}, {}]
        )
        target = LegacyFakeCollection("rag_v2_baai-bge-m3", ["b"], ["y"], [{}])
        store = self.make_store(LegacyFakeClient(legacy, target), target)

        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 2)
        self.assertEqual(sorted(target.ids), ["a", "b", "c"])
        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 0)
        self.assertEqual(len(target.ids), 3)

    def test_large_legacy_collection_is_copied_in_batches(self):
        ids = [f"id{i}" for i in range(250)]
        legacy = LegacyFakeCollection("rag_baai-bge-m3", ids, ["d"] * 250, [{}] * 250)
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(legacy, target), target)

        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 250)
        self.assertEqual(target.add_sizes, [100, 100, 50])
        self.assertEqual(sorted(target.ids), sorted(ids))

    def test_failure_propagates_and_rerun_resumes(self):
        ids = [f"id{i}" for i in range(250)]
        legacy = LegacyFakeCollection("rag_baai-bge-m3", ids, ["d"] * 250, [{}] * 250)
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        target.fail_on_add_call = 2
        store = self.make_store(LegacyFakeClient(legacy, target), target)

        with self.assertRaises(RuntimeError):
            migrate_legacy_collection(store, "rag", "baai/bge-m3")
        self.assertEqual(len(target.ids), 100)

        target.fail_on_add_call = None
        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 150)
        self.assertEqual(sorted(target.ids), sorted(ids))

    def test_none_metadata_is_preserved(self):
        legacy = LegacyFakeCollection("rag_baai-bge-m3", ["a"], ["x"], [None])
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(legacy, target), target)

        migrate_legacy_collection(store, "rag", "baai/bge-m3")

        self.assertEqual(target.metas, [None])

    def test_chunk_without_document_text_is_skipped_with_warning(self):
        legacy = LegacyFakeCollection("rag_baai-bge-m3", ["a", "b"], [None, "y"], [{}, {}])
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(legacy, target), target)

        with self.assertLogs("AI.Chunking.Vector_Stores", level="WARNING"):
            moved = migrate_legacy_collection(store, "rag", "baai/bge-m3")

        self.assertEqual(moved, 1)
        self.assertEqual(target.ids, ["b"])

    def test_no_legacy_collection_is_noop(self):
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(target), target)

        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 0)

    def test_migrates_every_legacy_rag_collection_current_model_first(self):
        current = LegacyFakeCollection("rag_baai-bge-m3", ["a", "b"], ["a-cur", "b-cur"], [{"m": "cur"}, {"m": "cur"}])
        other = LegacyFakeCollection(
            "rag_openai-text-embedding-3-small", ["b", "c"], ["b-old", "c-old"], [{"m": "old"}, {"m": "old"}]
        )
        ada = LegacyFakeCollection("rag_openai-ada-002", ["d"], ["d-ada"], [{"m": "ada"}])
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(other, ada, current, target), target)

        moved = migrate_legacy_collection(store, "rag", "baai/bge-m3")

        self.assertEqual(moved, 4)
        self.assertEqual(sorted(target.ids), ["a", "b", "c", "d"])
        self.assertEqual(target.docs[target.ids.index("b")], "b-cur")

    def test_session_memory_legacy_collections_are_not_migrated_into_rag(self):
        legacy_memory = LegacyFakeCollection("session_memory_baai-bge-m3", ["m1"], ["chat"], [{}])
        legacy_rag = LegacyFakeCollection("rag_baai-bge-m3", ["a"], ["x"], [{}])
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(legacy_memory, legacy_rag, target), target)

        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 1)
        self.assertEqual(target.ids, ["a"])

    def test_versioned_collections_are_not_treated_as_legacy_sources(self):
        other_v2 = LegacyFakeCollection("rag_v2_openai-ada-002", ["z"], ["z"], [{}])
        target = LegacyFakeCollection("rag_v2_baai-bge-m3")
        store = self.make_store(LegacyFakeClient(other_v2, target), target)

        self.assertEqual(migrate_legacy_collection(store, "rag", "baai/bge-m3"), 0)

    def test_drops_only_unversioned_collections_and_logs(self):
        client = LegacyFakeClient(
            LegacyFakeCollection("rag_baai-bge-m3"),
            LegacyFakeCollection("rag_openai-text-embedding-3-small"),
            LegacyFakeCollection("session_memory_baai-bge-m3"),
            LegacyFakeCollection("rag_v2_baai-bge-m3"),
            LegacyFakeCollection("session_memory_v2_baai-bge-m3"),
            LegacyFakeCollection("something_else"),
        )
        with self.assertLogs("AI.Chunking.Vector_Stores", level="WARNING") as logs:
            dropped = drop_legacy_collections(client)

        self.assertEqual(
            sorted(dropped),
            ["rag_baai-bge-m3", "rag_openai-text-embedding-3-small", "session_memory_baai-bge-m3"],
        )
        self.assertEqual(
            sorted(client.collections),
            ["rag_v2_baai-bge-m3", "session_memory_v2_baai-bge-m3", "something_else"],
        )
        self.assertEqual(len(logs.output), 3)

    def test_accepts_collection_names_as_strings(self):
        class NameClient(LegacyFakeClient):
            def list_collections(self):
                return list(self.collections)

        client = NameClient(LegacyFakeCollection("rag_baai-bge-m3"))

        self.assertEqual(drop_legacy_collections(client), ["rag_baai-bge-m3"])


if __name__ == "__main__":
    unittest.main()
