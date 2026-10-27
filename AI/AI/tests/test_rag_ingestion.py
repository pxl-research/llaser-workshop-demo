import importlib.util
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
        self.add_sizes = []

    def get(self, where=None, limit=None, include=None, ids=None, offset=0):
        ids = [
            row_id
            for row_id, (_doc, meta) in self.rows.items()
            if (ids is None or row_id in ids)
            and (not where or all((meta or {}).get(key) == value for key, value in where.items()))
        ][offset:]
        ids = ids[:limit]
        return {
            "ids": ids,
            "documents": [self.rows[i][0] for i in ids],
            "metadatas": [self.rows[i][1] for i in ids],
        }

    def add(self, documents, metadatas, ids):
        self.add_sizes.append(len(ids))
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

    def list_collections(self):
        return list(self.collections.values())

    def delete_collection(self, name):
        self.deleted.append(name)
        self.collections.pop(name, None)


def load_rag():
    """Load the real RAG.py with its heavy collaborators replaced by stubs."""
    stubs = {
        "AI.Chunking.PyMuPDF4LLM_Loader": stub_module(
            "AI.Chunking.PyMuPDF4LLM_Loader", PyMuPDF4LLMLoader=MagicMock()
        ),
        "AI.Chunking.AzureDocument_Loader": stub_module(
            "AI.Chunking.AzureDocument_Loader", AzureDocumentIntelligenceLoader=MagicMock()
        ),
        "AI.Chunking.LlamaParse_Loader": stub_module("AI.Chunking.LlamaParse_Loader", LlamaParseLoader=MagicMock()),
        "AI.API.LLM": stub_module("AI.API.LLM", LLM=MagicMock()),
        "AI.API.embeddings": stub_module(
            "AI.API.embeddings",
            DEFAULT_EMBEDDING_MODEL="baai/bge-m3",
            create_embedding_model=MagicMock(),
        ),
        "AI.Chunking.Vector_Stores": VECTOR_STORES,
        "AI.Chunking.Splitter": SPLITTER,
        "AI.API.rerankers": stub_module(
            "AI.API.rerankers",
            DEFAULT_RERANKER="qwen/qwen3-reranker-8b",
            create_reranker_model=MagicMock(),
        ),
        "AI.API.SessionMemory": stub_module("AI.API.SessionMemory", SessionMemory=MagicMock()),
    }
    return load_source("AI.API.RAG_under_test", "API/RAG.py", stubs)


RAG_MODULE = load_rag()


class FakeLoader:
    def __init__(self, texts):
        self.texts = texts

    def load_document(self, file_path):
        return self.texts


def make_rag(add_document_result=None, add_document_error=None):
    rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
    rag.embedder = MagicMock()
    rag.vector_store = MagicMock()
    rag.vector_store.is_indexed.return_value = False
    rag._data_path = RAG_MODULE.settings.UPLOAD_DIR
    if add_document_error is not None:
        rag.vector_store.add_document.side_effect = add_document_error
    else:
        rag.vector_store.add_document.return_value = add_document_result
    return rag


LONG_PROSE = ("LLASER indexes uploaded documents into a vector store. " * 40 + "\n\n") * 4


class CreateDocumentLoaderTests(unittest.TestCase):
    def test_empty_or_unset_name_defaults_to_azure_document_intelligence(self):
        for name in ("", None):
            with self.subTest(name=name), patch.object(RAG_MODULE, "AzureDocumentIntelligenceLoader") as azure:
                loader = RAG_MODULE.create_document_loader(name)

                self.assertIs(loader, azure.return_value)

    def test_docling_is_not_a_loader(self):
        with self.assertRaises(ValueError):
            RAG_MODULE.create_document_loader("docling")


class ProcessAndAddDocumentTests(unittest.TestCase):
    def run_process(self, rag, texts=("# Title\n\nSome content.",)):
        with tempfile.TemporaryDirectory() as tmp:
            uploaded = Path(tmp) / "doc.txt"
            uploaded.write_text("content")
            with patch.object(RAG_MODULE, "create_document_loader", return_value=FakeLoader(list(texts))):
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
            uploaded = Path(tmp) / "doc.txt"
            uploaded.write_text("content")
            with patch.object(RAG_MODULE, "create_document_loader") as create_loader:
                result = rag.process_and_add_document(str(uploaded))

        create_loader.assert_not_called()
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
        self.assertNotIn("doc.txt", result["message"])

    def test_reports_read_message_when_loader_raises(self):
        rag = make_rag(add_document_result=1)

        with tempfile.TemporaryDirectory() as tmp:
            uploaded = Path(tmp) / "doc.txt"
            uploaded.write_text("content")
            loader = MagicMock()
            loader.load_document.side_effect = ValueError(f"cannot parse {uploaded}")
            with patch.object(RAG_MODULE, "create_document_loader", return_value=loader):
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


class SetupVectorStoreTests(unittest.TestCase):
    def setUp(self):
        # Startup indexes UPLOAD_DIR too; other test modules leave it pointing at real files.
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        patcher = patch.object(RAG_MODULE.settings, "UPLOAD_DIR", Path(empty.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_legacy_migration_runs_after_create_and_before_file_loop(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = False
        calls = []
        store.create.side_effect = lambda: calls.append("create")
        store.add_document.side_effect = lambda *a, **k: calls.append("add")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.pdf").write_text("content")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=tmp
            ), patch.object(
                RAG_MODULE, "create_document_loader", return_value=FakeLoader([LONG_PROSE])
            ), patch.object(RAG_MODULE, "ChromaVectorStore", return_value=store), patch.object(
                RAG_MODULE, "migrate_legacy_collection", side_effect=lambda *a: calls.append("migrate")
            ) as migrate, patch.object(
                RAG_MODULE, "drop_legacy_collections", side_effect=lambda *a: calls.append("drop")
            ) as drop:
                rag._setup_vector_store()

        migrate.assert_called_once_with(store, "rag", "baai/bge-m3")
        drop.assert_called_once_with(store.client)
        self.assertEqual(calls, ["create", "migrate", "drop", "add"])

    def test_migration_failure_is_logged_and_startup_continues(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.pdf").write_text("content")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=tmp
            ), patch.object(
                RAG_MODULE, "create_document_loader", return_value=FakeLoader([LONG_PROSE])
            ), patch.object(RAG_MODULE, "ChromaVectorStore", return_value=store), patch.object(
                RAG_MODULE, "migrate_legacy_collection", side_effect=RuntimeError("boom")
            ), patch.object(RAG_MODULE, "drop_legacy_collections") as drop:
                with self.assertLogs(RAG_MODULE.logger.name, level="ERROR"):
                    result = rag._setup_vector_store()

        self.assertIs(result, store)
        drop.assert_not_called()
        store.add_document.assert_called_once()

    def test_startup_prunes_to_hashes_of_data_and_upload_files_excluding_store_dir(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = True
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as uploads:
            store_dir = Path(uploads) / ".llaser_store"
            store_dir.mkdir()
            (Path(data) / "a.pdf").write_text("data file")
            (Path(uploads) / "b.pdf").write_text("upload file")
            (store_dir / "chroma.sqlite3").write_text("db internals")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=data
            ), patch.object(RAG_MODULE, "create_document_loader"), patch.object(
                RAG_MODULE, "ChromaVectorStore", return_value=store
            ), patch.object(RAG_MODULE.settings, "UPLOAD_DIR", Path(uploads)), patch.object(
                RAG_MODULE.settings, "STORE_DIR", store_dir
            ):
                rag._setup_vector_store()
            expected = {
                VECTOR_STORES.compute_hash(str(Path(data) / "a.pdf")),
                VECTOR_STORES.compute_hash(str(Path(uploads) / "b.pdf")),
            }

        store.prune_missing.assert_called_once_with(expected)

    def test_local_startup_indexes_uploads_once_and_never_the_store_dir(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = False
        loader = MagicMock()
        loader.load_document.return_value = [LONG_PROSE]
        with tempfile.TemporaryDirectory() as uploads:
            store_dir = Path(uploads) / ".llaser_store"
            store_dir.mkdir()
            (Path(uploads) / "b.pdf").write_text("upload file")
            (store_dir / "chroma.sqlite3").write_text("db internals")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "local", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "create_document_loader", return_value=loader
            ), patch.object(RAG_MODULE, "ChromaVectorStore", return_value=store), patch.object(
                RAG_MODULE.settings, "UPLOAD_DIR", Path(uploads)
            ), patch.object(RAG_MODULE.settings, "STORE_DIR", store_dir):
                rag._setup_vector_store()

            loader.load_document.assert_called_once_with(str(Path(uploads) / "b.pdf"))

    def test_startup_never_loads_or_keeps_files_the_loader_cannot_read(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = False
        loader = MagicMock()
        loader.load_document.return_value = [LONG_PROSE]
        with tempfile.TemporaryDirectory() as uploads:
            (Path(uploads) / "notes.txt").write_text("stray")
            (Path(uploads) / "report.docx").write_text("not for pymupdf4llm")
            (Path(uploads) / "b.pdf").write_text("upload file")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "local", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "create_document_loader", return_value=loader
            ), patch.object(RAG_MODULE, "ChromaVectorStore", return_value=store), patch.object(
                RAG_MODULE.settings, "UPLOAD_DIR", Path(uploads)
            ):
                rag._setup_vector_store()

            loader.load_document.assert_called_once_with(str(Path(uploads) / "b.pdf"))
            store.prune_missing.assert_called_once_with({VECTOR_STORES.compute_hash(str(Path(uploads) / "b.pdf"))})

    def test_startup_skips_loader_for_indexed_file(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = True
        loader = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.pdf").write_text("content")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=tmp
            ), patch.object(RAG_MODULE, "create_document_loader", return_value=loader) as create_loader, patch.object(
                RAG_MODULE, "ChromaVectorStore", return_value=store
            ):
                rag._setup_vector_store()

        create_loader.assert_not_called()
        loader.load_document.assert_not_called()
        store.add_document.assert_not_called()

    def test_startup_survives_loader_creation_failure(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.pdf").write_text("content")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "llama_parse"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=tmp
            ), patch.object(
                RAG_MODULE, "create_document_loader", side_effect=RuntimeError("LLAMA_KEY is not set")
            ), patch.object(RAG_MODULE, "ChromaVectorStore", return_value=store):
                with self.assertLogs(RAG_MODULE.logger.name, level="ERROR"):
                    result = rag._setup_vector_store()

        self.assertIs(result, store)
        store.add_document.assert_not_called()

    def test_startup_loader_failure_is_logged_and_next_file_still_added(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "baai/bge-m3"
        store = MagicMock()
        store.is_indexed.return_value = False
        loader = MagicMock()
        loader.load_document.side_effect = [ValueError("bad pdf"), [LONG_PROSE]]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.pdf").write_text("one")
            (Path(tmp) / "b.pdf").write_text("two")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=tmp
            ), patch.object(RAG_MODULE, "create_document_loader", return_value=loader), patch.object(
                RAG_MODULE, "ChromaVectorStore", return_value=store
            ):
                with self.assertLogs(RAG_MODULE.logger.name, level="ERROR") as logs:
                    rag._setup_vector_store()

        self.assertIn("Startup indexing failed", "\n".join(logs.output))
        store.add_document.assert_called_once()

    def test_startup_ingestion_persists_under_store_dir_and_uses_markdown_chunks(self):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.embedder = MagicMock()
        rag.current_embedding_model = "openai/text-embedding-3-small"
        store = MagicMock()
        store.is_indexed.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.pdf").write_text("content")
            env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
            with patch.dict("os.environ", env), patch.object(
                RAG_MODULE, "download_container_documents", create=True, return_value=tmp
            ), patch.object(
                RAG_MODULE, "create_document_loader", return_value=FakeLoader([LONG_PROSE])
            ), patch.object(RAG_MODULE, "ChromaVectorStore", return_value=store) as store_cls:
                result = rag._setup_vector_store()

        self.assertIs(result, store)
        self.assertEqual(store_cls.call_args.kwargs["db_name"], "rag_v2_openai-text-embedding-3-small")
        self.assertEqual(
            store_cls.call_args.kwargs["persist_directory"],
            str(RAG_MODULE.settings.STORE_DIR / "chroma_db_data"),
        )
        chunks = store.add_document.call_args.args[1]
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))


class QueryPromptTests(unittest.TestCase):
    def tearDown(self):
        RAG_MODULE.settings.SYSTEM_PROMPT = RAG_MODULE.settings.DEFAULT_SYSTEM_PROMPT

    def _system_prompt_for(self, chunk):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.session_memory = MagicMock()
        rag.session_memory.get_most_recent_message.return_value = ""
        rag.session_memory.retrieve_context.return_value = ""
        rag.vector_store = MagicMock()
        rag.vector_store.retrieve_top_chunks.return_value = [chunk]
        rag.reranker = MagicMock()
        rag.reranker.rerank.return_value = [chunk]
        rag.llm = MagicMock()

        def fake_stream_text(**kwargs):
            yield "answer"
            return {}, "answer"

        rag.llm.stream_text.side_effect = fake_stream_text

        list(rag.stream_query("question?"))

        return rag.llm.stream_text.call_args.kwargs["system_prompt"]

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


MODEL_A = "openai/text-embedding-3-small"
MODEL_B = "baai/bge-m3"


class FlakyCollection(FakeCollection):
    """Fails its second add, like an embedding API error partway through a copy."""

    def __init__(self, name):
        super().__init__(name)
        self.fail_on_add: int | None = 2

    def add(self, documents, metadatas, ids):
        if len(self.add_sizes) + 1 == self.fail_on_add:
            raise RuntimeError("embedding API down")
        super().add(documents, metadatas, ids)


class PerModelCollectionTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeChromaClient()
        patcher = patch.object(VECTOR_STORES.chromadb, "PersistentClient", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()

    def make_rag(self, model_name):
        rag = RAG_MODULE.RAG.__new__(RAG_MODULE.RAG)
        rag.device = "cpu"
        rag.embedder = MagicMock()
        rag.current_embedding_model = model_name
        rag.session_memory = MagicMock()
        env = {"AI_NAME": "demo", "DEPLOYMENT_ENV": "container", "DOCUMENT_LOADER": "pymupdf4llm"}
        with patch.dict("os.environ", env), patch.object(
            RAG_MODULE, "download_container_documents", create=True, return_value=str(self.data_dir)
        ):
            rag.vector_store = rag._setup_vector_store()
        return rag

    def upload(self, rag, file_path):
        # Real uploads land in UPLOAD_DIR, which the post-upload prune treats as on disk.
        with patch.object(RAG_MODULE, "create_document_loader", return_value=FakeLoader([LONG_PROSE])), patch.object(
            RAG_MODULE.settings, "UPLOAD_DIR", Path(file_path).parent
        ):
            return rag.process_and_add_document(str(file_path))

    def test_reupload_with_changed_content_drops_the_old_version_chunks(self):
        pdf = Path(self.tmp.name) / "doc.pdf"
        pdf.write_text("version one")
        rag = self.make_rag(MODEL_A)
        self.upload(rag, pdf)
        pdf.write_text("version two")

        result = self.upload(rag, pdf)

        self.assertFalse(result["already_indexed"])
        hashes = {meta["file_hash"] for _doc, meta in rag.vector_store.collection.rows.values()}
        self.assertEqual(hashes, {VECTOR_STORES.compute_hash(str(pdf))})

    def switch_model(self, rag, model_name):
        env = {"RERANKER": "qwen/qwen3-reranker-8b"}
        with patch.dict("os.environ", env), patch.object(
            RAG_MODULE, "create_embedding_model", return_value=MagicMock()
        ), patch.object(RAG_MODULE, "create_reranker_model", return_value=MagicMock()), patch.object(
            RAG_MODULE.settings, "UPLOAD_DIR", Path(self.tmp.name)
        ):
            return rag.update_embedding_model(model_name)

    def test_switch_drops_chunks_of_files_deleted_from_disk(self):
        kept = Path(self.tmp.name) / "kept.pdf"
        gone = Path(self.tmp.name) / "gone.pdf"
        kept.write_text("kept bytes")
        gone.write_text("gone bytes")
        rag = self.make_rag(MODEL_A)
        self.upload(rag, kept)
        self.upload(rag, gone)
        gone.unlink()

        result = self.switch_model(rag, MODEL_B)

        self.assertEqual(result["status"], "success")
        hashes = {meta["file_hash"] for _doc, meta in rag.vector_store.collection.rows.values()}
        self.assertEqual(hashes, {VECTOR_STORES.compute_hash(str(kept))})

    def test_deleting_the_last_file_empties_the_collection(self):
        pdf = Path(self.tmp.name) / "only.pdf"
        pdf.write_text("only file")
        rag = self.make_rag(MODEL_A)
        self.upload(rag, pdf)
        pdf.unlink()

        with patch.object(RAG_MODULE.settings, "UPLOAD_DIR", Path(self.tmp.name)):
            rag._prune_to_disk()

        self.assertEqual(rag.vector_store.collection.count(), 0)

    def test_prune_keeps_chunks_when_a_source_root_is_missing(self):
        pdf = Path(self.tmp.name) / "doc.pdf"
        pdf.write_text("doc")
        rag = self.make_rag(MODEL_A)
        self.upload(rag, pdf)

        with patch.object(RAG_MODULE.settings, "UPLOAD_DIR", Path(self.tmp.name) / "unmounted"):
            rag._prune_to_disk()

        self.assertGreater(rag.vector_store.collection.count(), 0)

    def on_disk_hash(self):
        """Hash of a file under the switch's UPLOAD_DIR, so the post-switch prune keeps its chunks."""
        pdf = Path(self.tmp.name) / "on_disk.pdf"
        pdf.write_text("on disk")
        return VECTOR_STORES.compute_hash(str(pdf))

    def test_failed_copy_keeps_the_old_model_active_and_a_retry_completes(self):
        rag = self.make_rag(MODEL_A)
        old_collection = self.client.collections["rag_v2_openai-text-embedding-3-small"]
        file_hash = self.on_disk_hash()
        for i in range(250):
            old_collection.rows[f"id{i}"] = ("doc", {"file_hash": file_hash})
        target = self.client.collections["rag_v2_baai-bge-m3"] = FlakyCollection("rag_v2_baai-bge-m3")

        failed = self.switch_model(rag, MODEL_B)

        self.assertEqual(failed["status"], "error")
        self.assertEqual(rag.current_embedding_model, MODEL_A)
        self.assertIs(rag.vector_store.collection, old_collection)
        rag.session_memory.switch_embedding_model.assert_not_called()

        target.fail_on_add = None
        retried = self.switch_model(rag, MODEL_B)

        self.assertEqual(retried["status"], "success")
        self.assertIs(rag.vector_store.collection, target)
        self.assertEqual(target.count(), 250)

    def test_setup_uses_the_collection_of_the_current_embedding_model(self):
        rag = self.make_rag(MODEL_A)

        self.assertEqual(rag.vector_store.db_name, "rag_v2_openai-text-embedding-3-small")
        self.assertEqual(list(self.client.collections), ["rag_v2_openai-text-embedding-3-small"])

    def test_upload_under_model_b_is_not_already_indexed_because_of_model_a(self):
        pdf = Path(self.tmp.name) / "doc.pdf"
        pdf.write_text("same bytes")
        rag_a = self.make_rag(MODEL_A)
        rag_b = self.make_rag(MODEL_B)

        first_a = self.upload(rag_a, pdf)
        again_a = self.upload(rag_a, pdf)
        first_b = self.upload(rag_b, pdf)

        self.assertFalse(first_a["already_indexed"])
        self.assertTrue(again_a["already_indexed"])
        self.assertFalse(first_b["already_indexed"])
        self.assertGreater(first_b["chunks"], 0)
        self.assertEqual(
            sorted(self.client.collections),
            ["rag_v2_baai-bge-m3", "rag_v2_openai-text-embedding-3-small"],
        )

    def test_runtime_switch_uses_new_collection_and_keeps_the_old_one(self):
        pdf = Path(self.tmp.name) / "doc.pdf"
        pdf.write_text("same bytes")
        rag = self.make_rag(MODEL_A)
        self.upload(rag, pdf)
        old_collection = self.client.collections["rag_v2_openai-text-embedding-3-small"]
        old_rows = dict(old_collection.rows)
        cached_memory = MagicMock()
        rag._session_memories = {"s1": cached_memory}

        result = self.switch_model(rag, MODEL_B)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks_reembedded"], len(old_rows))
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(rag.vector_store.db_name, "rag_v2_baai-bge-m3")
        self.assertEqual(old_collection.rows, old_rows)
        self.assertEqual(self.client.collections["rag_v2_baai-bge-m3"].rows, old_rows)
        rag.session_memory.switch_embedding_model.assert_called_once_with(rag.embedder, MODEL_B)
        cached_memory.switch_embedding_model.assert_called_once_with(rag.embedder, MODEL_B)

    def test_runtime_switch_copies_large_collections_in_batches(self):
        rag = self.make_rag(MODEL_A)
        old_collection = self.client.collections["rag_v2_openai-text-embedding-3-small"]
        for i in range(250):
            old_collection.rows[f"id{i}"] = ("doc", {"file_hash": "h"})

        result = self.switch_model(rag, MODEL_B)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks_reembedded"], 250)
        self.assertEqual(self.client.collections["rag_v2_baai-bge-m3"].add_sizes, [100, 100, 50])

    def test_reranker_failure_leaves_the_previous_model_fully_active(self):
        rag = self.make_rag(MODEL_A)
        old_embedder = rag.embedder
        old_store_collection = rag.vector_store.collection
        with patch.dict("os.environ", {"EMBEDDING_MODEL": MODEL_A, "RERANKER": "qwen/qwen3-reranker-8b"}):
            with patch.object(RAG_MODULE, "create_embedding_model", return_value=MagicMock()), patch.object(
                RAG_MODULE, "create_reranker_model", side_effect=RuntimeError("no reranker")
            ):
                result = rag.update_embedding_model(MODEL_B)
            env_model = os.environ["EMBEDDING_MODEL"]

        self.assertEqual(result["status"], "error")
        self.assertEqual(rag.current_embedding_model, MODEL_A)
        self.assertIs(rag.embedder, old_embedder)
        self.assertIs(rag.vector_store.collection, old_store_collection)
        self.assertEqual(rag.vector_store.db_name, "rag_v2_openai-text-embedding-3-small")
        self.assertEqual(env_model, MODEL_A)
        rag.session_memory.switch_embedding_model.assert_not_called()

    def test_runtime_switch_completes_a_partly_filled_target(self):
        rag = self.make_rag(MODEL_A)
        old_collection = self.client.collections["rag_v2_openai-text-embedding-3-small"]
        file_hash = self.on_disk_hash()
        for i in range(3):
            old_collection.rows[f"id{i}"] = ("doc", {"file_hash": file_hash})
        partial = self.client.collections.setdefault("rag_v2_baai-bge-m3", FakeCollection("rag_v2_baai-bge-m3"))
        partial.rows["id0"] = ("kept", {"file_hash": file_hash})

        result = self.switch_model(rag, MODEL_B)

        self.assertEqual(result["chunks_reembedded"], 2)
        self.assertEqual(sorted(partial.rows), ["id0", "id1", "id2"])
        self.assertEqual(partial.rows["id0"][0], "kept")
        self.assertEqual(partial.add_sizes, [2])

    def test_switch_without_reranker_update_does_not_build_a_reranker(self):
        rag = self.make_rag(MODEL_A)
        old_reranker = rag.reranker = MagicMock()
        with patch.dict("os.environ", {"RERANKER": "qwen/qwen3-reranker-8b"}), patch.object(
            RAG_MODULE, "create_embedding_model", return_value=MagicMock()
        ), patch.object(RAG_MODULE, "create_reranker_model", side_effect=RuntimeError("no reranker")):
            result = rag.update_embedding_model(MODEL_B, update_reranker=False)

        self.assertEqual(result["status"], "success")
        self.assertEqual(rag.current_embedding_model, MODEL_B)
        self.assertIs(rag.reranker, old_reranker)

    def test_use_collection_failure_leaves_session_memories_untouched(self):
        rag = self.make_rag(MODEL_A)
        cached_memory = MagicMock()
        rag._session_memories = {"s1": cached_memory}
        with patch.object(rag.vector_store, "use_collection", side_effect=RuntimeError("boom")):
            result = self.switch_model(rag, MODEL_B)

        self.assertEqual(result["status"], "error")
        rag.session_memory.switch_embedding_model.assert_not_called()
        cached_memory.switch_embedding_model.assert_not_called()

    def test_re_embed_error_makes_the_switch_report_error_and_keeps_the_old_model(self):
        rag = self.make_rag(MODEL_A)
        failure = {"status": "error", "message": "Failed to re-embed documents: boom", "documents_processed": 0}
        with patch.object(rag, "re_embed_all_documents", return_value=failure):
            result = self.switch_model(rag, MODEL_B)

        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to re-embed documents: boom", result["message"])
        self.assertIsNone(result["embedding_model"])
        self.assertEqual(rag.current_embedding_model, MODEL_A)
        self.assertEqual(rag.vector_store.db_name, "rag_v2_openai-text-embedding-3-small")

    def test_switching_back_reuses_the_old_collection_as_is(self):
        pdf = Path(self.tmp.name) / "doc.pdf"
        pdf.write_text("same bytes")
        rag = self.make_rag(MODEL_A)
        self.upload(rag, pdf)
        self.switch_model(rag, MODEL_B)
        reused = self.client.collections["rag_v2_openai-text-embedding-3-small"]
        reused_rows = dict(reused.rows)

        result = self.switch_model(rag, MODEL_A)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunks_reembedded"], 0)
        self.assertEqual(rag.vector_store.db_name, "rag_v2_openai-text-embedding-3-small")
        self.assertEqual(reused.rows, reused_rows)
        self.assertEqual(self.client.deleted, [])


class MarkdownSplitterTests(unittest.TestCase):
    def test_long_paragraphs_without_headings_stay_within_max_chunk_size(self):
        splitter = SPLITTER.MarkdownSplitter(max_chunk_size=2000)

        chunks = splitter.split([LONG_PROSE])

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))


class StoreDirTests(unittest.TestCase):
    def load_settings(self, env):
        with patch.dict("os.environ", env, clear=True):
            return load_source("AI.API.settings_under_test", "API/settings.py", {})

    def test_store_dir_defaults_under_upload_dir(self):
        loaded = self.load_settings({"UPLOAD_DIR": "/srv/uploads"})

        self.assertEqual(loaded.STORE_DIR, Path("/srv/uploads") / ".llaser_store")

    def test_store_dir_can_be_overridden(self):
        loaded = self.load_settings({"UPLOAD_DIR": "/srv/uploads", "STORE_DIR": "/srv/elsewhere"})

        self.assertEqual(loaded.STORE_DIR, Path("/srv/elsewhere"))


class SessionMemoryPersistenceTests(unittest.TestCase):
    def test_session_memory_persists_under_store_dir(self):
        vector_stores = stub_module(
            "AI.Chunking.Vector_Stores",
            ChromaVectorStore=MagicMock(),
            collection_name=VECTOR_STORES.collection_name,
            drop_legacy_collections=VECTOR_STORES.drop_legacy_collections,
        )
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
