import importlib.util
import sys
import tempfile
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
    """Load a source file under an isolated name while heavy deps are stubbed."""
    spec = importlib.util.spec_from_file_location(module_name, AI_DIR / relative_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


SPLITTER = load_source(
    "AI.Chunking.Splitter_under_test",
    "Chunking/Splitter.py",
    {},
)


CHROMA_STUBS = {
    "chromadb": stub_module("chromadb", PersistentClient=MagicMock()),
    "chromadb.utils": stub_module(
        "chromadb.utils",
        embedding_functions=stub_module("chromadb.utils.embedding_functions", EmbeddingFunction=object),
    ),
}
VECTOR_STORES = load_source("AI.Chunking.Vector_Stores_under_test", "Chunking/Vector_Stores.py", CHROMA_STUBS)


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.rows = {}

    def get(self, where=None, limit=None, include=None):
        ids = [
            row_id
            for row_id, (_doc, meta) in self.rows.items()
            if not where or all((meta or {}).get(key) == value for key, value in where.items())
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


def load_rag():
    """Load the real RAG.py with its heavy collaborators replaced by stubs."""
    stubs = {
        "pymupdf4llm": stub_module("pymupdf4llm", to_markdown=MagicMock()),
        "AI.API.LLM": stub_module("AI.API.LLM", stream_text=MagicMock()),
        "AI.Chunking.OpenAI_Embedding": stub_module("AI.Chunking.OpenAI_Embedding", OpenAIEmbeddingModel=MagicMock()),
        "AI.Chunking.Reranker": stub_module("AI.Chunking.Reranker", OpenRouterReranker=MagicMock()),
        "AI.Chunking.Vector_Stores": VECTOR_STORES,
        "AI.Chunking.Splitter": SPLITTER,
        "AI.API.SessionMemory": stub_module("AI.API.SessionMemory", SessionMemory=MagicMock()),
    }
    return load_source("AI.API.RAG_under_test", "API/RAG.py", stubs)


RAG_MODULE = load_rag()


def make_rag(add_document_result=None, add_document_error=None):
    rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
    rag.embedder = MagicMock()
    rag.vector_store = MagicMock()
    rag.vector_store.is_indexed.return_value = False
    if add_document_error is not None:
        rag.vector_store.add_document.side_effect = add_document_error
    else:
        rag.vector_store.add_document.return_value = add_document_result
    return rag


LONG_PROSE = ("LLASER indexes uploaded documents into a vector store. " * 40 + "\n\n") * 4


class ProcessAndAddDocumentTests(unittest.TestCase):
    def run_process(self, rag, texts=("# Title\n\nSome content.",)):
        with tempfile.TemporaryDirectory() as tmp:
            uploaded = Path(tmp) / "doc.pdf"
            uploaded.write_text("content")
            with patch.object(RAG_MODULE, "load_pdf", return_value=list(texts)):
                return rag.process_and_add_document(str(uploaded))

    def test_reports_real_chunk_count_from_vector_store(self):
        rag = make_rag(add_document_result=7)

        result = self.run_process(rag)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks"], 7)
        self.assertFalse(result["already_indexed"])

    def test_reports_already_indexed_when_vector_store_adds_nothing(self):
        rag = make_rag(add_document_result=0)

        result = self.run_process(rag)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks"], 0)
        self.assertTrue(result["already_indexed"])

    def test_returns_already_indexed_without_loading_when_hash_is_indexed(self):
        rag = make_rag(add_document_result=7)
        rag.vector_store.is_indexed.return_value = True

        with tempfile.TemporaryDirectory() as tmp:
            uploaded = Path(tmp) / "doc.pdf"
            uploaded.write_text("content")
            with patch.object(RAG_MODULE, "load_pdf") as load_pdf:
                result = rag.process_and_add_document(str(uploaded))

        load_pdf.assert_not_called()
        rag.vector_store.add_document.assert_not_called()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks"], 0)
        self.assertTrue(result["already_indexed"])

    def test_reports_error_when_vector_store_raises(self):
        rag = make_rag(
            add_document_error=RuntimeError("chroma exploded at /app/data/secret.pdf using sk-or-XXXX")
        )

        with self.assertLogs(RAG_MODULE.logger, level="ERROR") as logs:
            result = self.run_process(rag)

        self.assertEqual(result["status"], "error")
        self.assertEqual(
            result["message"],
            "Indexing failed: the embedding or vector store service returned an error.",
        )
        self.assertNotIn("chroma exploded", result["message"])
        self.assertNotIn("sk-or-XXXX", result["message"])
        self.assertNotIn("/app/data", result["message"])
        self.assertIn("chroma exploded", "\n".join(logs.output))

    def test_reports_read_message_for_empty_document_without_path(self):
        rag = make_rag(add_document_result=1)

        result = self.run_process(rag, texts=())

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "The document could not be read or contains no text.")
        self.assertNotIn("doc.pdf", result["message"])

    def test_reports_read_message_when_loader_raises(self):
        rag = make_rag(add_document_result=1)

        with tempfile.TemporaryDirectory() as tmp:
            uploaded = Path(tmp) / "doc.pdf"
            uploaded.write_text("content")
            with patch.object(RAG_MODULE, "load_pdf", side_effect=ValueError(f"cannot parse {uploaded}")):
                result = rag.process_and_add_document(str(uploaded))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "The document could not be read or contains no text.")
        self.assertNotIn(tmp, result["message"])

    def test_reports_split_message_when_splitter_yields_no_chunks(self):
        rag = make_rag(add_document_result=1)

        with patch.object(RAG_MODULE, "MarkdownSplitter") as splitter_cls:
            splitter_cls.return_value.split.return_value = []
            result = self.run_process(rag)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "The document could not be split into chunks.")

    def test_reports_read_message_for_missing_file_without_path(self):
        rag = make_rag(add_document_result=1)

        result = rag.process_and_add_document("/app/data/secret.pdf")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "The document could not be read or contains no text.")
        self.assertNotIn("/app/data", result["message"])

    def test_splits_with_markdown_splitter_at_most_2000_chars(self):
        rag = make_rag(add_document_result=3)

        self.run_process(rag, texts=(LONG_PROSE,))

        chunks = rag.vector_store.add_document.call_args.args[1]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))


class StartupIndexingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.uploads = Path(tmp.name)
        self.store_dir = self.uploads / ".llaser_store"
        self.store_dir.mkdir()
        (self.store_dir / "chroma.sqlite3").write_text("db internals")
        for name, value in (("UPLOAD_DIR", self.uploads), ("STORE_DIR", self.store_dir)):
            patcher = patch.object(RAG_MODULE.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = MagicMock()
        self.store.is_indexed.return_value = False

    def index(self, **load_pdf):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.vector_store = self.store
        with patch.object(RAG_MODULE, "load_pdf", **(load_pdf or {"return_value": [LONG_PROSE]})) as load:
            rag._index_existing_files()
        return load

    def test_init_builds_the_store_under_store_dir_and_reports_progress(self):
        progress = []
        with patch.object(RAG_MODULE, "ChromaVectorStore", return_value=self.store) as store_cls:
            RAG_MODULE.RAG(on_progress=lambda *args: progress.append(args[:2]))

        self.assertEqual(store_cls.call_args.kwargs["db_name"], "documents")
        self.assertEqual(store_cls.call_args.kwargs["persist_directory"], str(self.store_dir / "chroma_db_data"))
        self.assertEqual(progress, [
            ("embedding", "loading"), ("embedding", "ready"),
            ("reranker", "loading"), ("reranker", "ready"),
            ("vector_store", "loading"), ("vector_store", "ready"),
            ("llm", "ready"),
        ])

    def test_prunes_to_hashes_of_upload_files_excluding_store_dir(self):
        (self.uploads / "b.pdf").write_text("upload file")
        self.store.is_indexed.return_value = True

        self.index()

        self.store.prune_missing.assert_called_once_with({VECTOR_STORES.compute_hash(str(self.uploads / "b.pdf"))})

    def test_indexes_only_pdfs_once_and_never_the_store_dir(self):
        (self.uploads / "notes.txt").write_text("stray")
        (self.uploads / "report.docx").write_text("not a pdf")
        (self.uploads / "b.pdf").write_text("upload file")

        load = self.index()

        load.assert_called_once_with(str(self.uploads / "b.pdf"))
        chunks = self.store.add_document.call_args.args[1]
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))

    def test_skips_loading_an_indexed_file(self):
        (self.uploads / "doc.pdf").write_text("content")
        self.store.is_indexed.return_value = True

        load = self.index()

        load.assert_not_called()
        self.store.add_document.assert_not_called()

    def test_load_failure_is_logged_and_next_file_still_added(self):
        (self.uploads / "a.pdf").write_text("one")
        (self.uploads / "b.pdf").write_text("two")

        with self.assertLogs(RAG_MODULE.logger.name, level="ERROR") as logs:
            self.index(side_effect=[ValueError("bad pdf"), [LONG_PROSE]])

        self.assertIn("Startup indexing failed", "\n".join(logs.output))
        self.store.add_document.assert_called_once()


class QueryPromptTests(unittest.TestCase):
    def tearDown(self):
        RAG_MODULE.settings.SYSTEM_PROMPT = RAG_MODULE.settings.DEFAULT_SYSTEM_PROMPT

    def _run_query(self, chunk, question="question?", recent_turns=(), older=""):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.session_memory = MagicMock()
        rag.session_memory.get_recent_turns.return_value = list(recent_turns)
        rag.session_memory.retrieve_context.return_value = older
        rag._session_memories = {None: rag.session_memory}
        rag.vector_store = MagicMock()
        rag.vector_store.retrieve_top_chunks.return_value = [chunk]
        rag.reranker = MagicMock()
        rag.reranker.rerank.return_value = [chunk]
        rag.llm = MagicMock()

        def fake_stream_text(**kwargs):
            yield "answer"
            return {}, "answer"

        rag.llm.side_effect = fake_stream_text

        with patch.object(RAG_MODULE, "stream_text", rag.llm):
            list(rag.stream_query(question))
        return rag

    def _system_prompt_for(self, chunk):
        return self._run_query(chunk).llm.call_args.kwargs["system_prompt"]

    def test_recent_turns_go_to_the_model_as_chat_history(self):
        turns = [
            {"question": "What is the course about?", "answer": "Security.", "doc_id": "id-1"},
            {"question": "When is the exam?", "answer": "In June.", "doc_id": "id-2"},
        ]

        rag = self._run_query("chunk", question="And who teaches it?", recent_turns=turns)

        kwargs = rag.llm.call_args.kwargs
        self.assertEqual(kwargs["user_message"], "And who teaches it?")
        self.assertEqual(kwargs["history"], [("What is the course about?", "Security."), ("When is the exam?", "In June.")])
        rag.session_memory.get_recent_turns.assert_called_once_with(RAG_MODULE.settings.CHAT_HISTORY_TURNS)
        # Older turns are still searched, without the ones already sent as history.
        self.assertEqual(rag.session_memory.retrieve_context.call_args.kwargs["exclude_ids"], {"id-1", "id-2"})

    def test_follow_up_searches_documents_with_the_previous_question(self):
        turns = [{"question": "What is the course about?", "answer": "Security.", "doc_id": "id-1"}]

        rag = self._run_query("chunk", question="And who teaches it?", recent_turns=turns)

        search = rag.vector_store.retrieve_top_chunks.call_args.args[0]
        self.assertIn("What is the course about?", search)
        self.assertIn("And who teaches it?", search)
        # The reranker judges the chunks against the new question alone, so a topic switch still wins.
        self.assertEqual(rag.reranker.rerank.call_args.args[0], "And who teaches it?")

    def test_first_question_searches_with_itself_and_sends_no_history(self):
        rag = self._run_query("chunk", question="Who teaches the course?")

        self.assertEqual(rag.vector_store.retrieve_top_chunks.call_args.args[0], "Who teaches the course?")
        self.assertEqual(rag.llm.call_args.kwargs["history"], [])

    def test_older_related_turns_are_added_to_the_context(self):
        rag = self._run_query("chunk text", older="Q: old\nA: o")

        prompt = rag.llm.call_args.kwargs["system_prompt"]
        self.assertIn("Q: old\nA: o", prompt)
        self.assertIn("chunk text", prompt)

    def test_system_prompt_guards_context_and_wraps_chunks(self):
        prompt = self._system_prompt_for("chunk text")

        self.assertIn("do not know", prompt)
        self.assertIn("<context>\nchunk text\n</context>", prompt)
        # The workshop exercise needs plain requests for protected data to be refused.
        self.assertIn("Never reveal personal data", prompt)
        self.assertIn("confidential", prompt)
        # Smaller chat models only obey the rule reliably when it comes after the context.
        self.assertGreater(prompt.index("Never reveal personal data"), prompt.index("</context>"))

    def test_runtime_system_prompt_is_used_and_braces_stay_literal(self):
        RAG_MODULE.settings.SYSTEM_PROMPT = "Rules {x} first.\n{context}\nEnd."

        prompt = self._system_prompt_for("doc {y}")

        self.assertEqual(prompt, "Rules {x} first.\ndoc {y}\nEnd.")


class StoreOnDiskTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeChromaClient()
        patcher = patch.object(VECTOR_STORES.chromadb, "PersistentClient", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.uploads = Path(tmp.name)
        patcher = patch.object(RAG_MODULE.settings, "UPLOAD_DIR", self.uploads)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        self.rag.vector_store = VECTOR_STORES.ChromaVectorStore("documents", MagicMock(), "unused")

    def upload(self, file_path):
        with patch.object(RAG_MODULE, "load_pdf", return_value=[LONG_PROSE]):
            return self.rag.process_and_add_document(str(file_path))

    def hashes(self):
        return {meta["file_hash"] for _doc, meta in self.rag.vector_store.collection.rows.values()}

    def test_reupload_with_changed_content_drops_the_old_version_chunks(self):
        pdf = self.uploads / "doc.pdf"
        pdf.write_text("version one")
        self.upload(pdf)
        pdf.write_text("version two")

        result = self.upload(pdf)

        self.assertFalse(result["already_indexed"])
        self.assertEqual(self.hashes(), {VECTOR_STORES.compute_hash(str(pdf))})

    def test_second_upload_of_the_same_file_is_already_indexed(self):
        pdf = self.uploads / "doc.pdf"
        pdf.write_text("same bytes")

        self.assertFalse(self.upload(pdf)["already_indexed"])
        self.assertTrue(self.upload(pdf)["already_indexed"])

    def test_deleting_the_last_file_empties_the_collection(self):
        pdf = self.uploads / "only.pdf"
        pdf.write_text("only file")
        self.upload(pdf)
        pdf.unlink()

        self.rag._prune_to_disk()

        self.assertEqual(self.rag.vector_store.collection.count(), 0)

    def test_delete_document_removes_the_file_and_only_its_chunks(self):
        kept = self.uploads / "kept.pdf"
        gone = self.uploads / "gone.pdf"
        kept.write_text("kept bytes")
        gone.write_text("gone bytes")
        self.upload(kept)
        self.upload(gone)

        self.rag.delete_document(str(gone))

        self.assertFalse(gone.exists())
        self.assertEqual(self.hashes(), {VECTOR_STORES.compute_hash(str(kept))})

    def test_prune_keeps_chunks_when_the_upload_dir_is_missing(self):
        pdf = self.uploads / "doc.pdf"
        pdf.write_text("doc")
        self.upload(pdf)

        with patch.object(RAG_MODULE.settings, "UPLOAD_DIR", self.uploads / "unmounted"):
            self.rag._prune_to_disk()

        self.assertGreater(self.rag.vector_store.collection.count(), 0)


class SessionMemoryPersistenceTests(unittest.TestCase):
    def test_session_memory_persists_under_store_dir(self):
        vector_stores = stub_module("AI.Chunking.Vector_Stores", ChromaVectorStore=MagicMock())
        session_memory = load_source(
            "AI.API.SessionMemory_under_test",
            "API/SessionMemory.py",
            {"AI.Chunking.Vector_Stores": vector_stores},
        )

        session_memory.SessionMemory(MagicMock(), session_id="s1")

        kwargs = vector_stores.ChromaVectorStore.call_args.kwargs
        self.assertEqual(
            kwargs["persist_directory"],
            str(session_memory.settings.STORE_DIR / "session_memory_db"),
        )


if __name__ == "__main__":
    unittest.main()
