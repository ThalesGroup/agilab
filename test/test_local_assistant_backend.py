"""Behavior coverage for the local assistant after retiring its UI wrapper."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from agilab.pipeline.local_assistant_backend import CUSTOM_PROMPT_TEMPLATE, RetrievalChain, load_adapters


@dataclass
class Document:
    page_content: str
    metadata: dict = field(default_factory=dict)


@pytest.fixture
def libraries():
    calls = {}

    class Splitter:
        def __init__(self, **kwargs):
            calls["splitter"] = kwargs
        def split_documents(self, documents):
            calls["split_documents"] = documents
            return documents

    class Embeddings:
        def __init__(self, **kwargs):
            calls["embedding"] = kwargs

    class Ollama:
        def __init__(self, **kwargs):
            calls["ollama"] = kwargs

    class Store:
        def __init__(self, documents):
            self.documents = documents
        def search(self, identifier):
            return self.documents[identifier]

    class FAISS:
        def __init__(self, embeddings, index, store, mapping):
            self.embedding_function = embeddings
            self.index = index
            self.docstore = store
            self.index_to_docstore_id = mapping
        @classmethod
        def from_documents(cls, documents, embeddings):
            mapping = {index: f"doc-{index}" for index in range(len(documents))}
            return cls(embeddings, SimpleNamespace(ntotal=len(documents)), Store(dict(zip(mapping.values(), documents))), mapping)

    def reader(path):
        calls.setdefault("pdf_files", []).append(Path(path).name)
        return SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: "A document"), SimpleNamespace(extract_text=lambda: "")])

    def write_index(index, path):
        Path(path).write_text(json.dumps({"count": index.ntotal}))

    def read_index(path):
        return SimpleNamespace(ntotal=json.loads(Path(path).read_text())["count"])

    modules = {
        "langchain_core.documents": SimpleNamespace(Document=Document),
        "langchain_text_splitters": SimpleNamespace(RecursiveCharacterTextSplitter=Splitter),
        "langchain_huggingface": SimpleNamespace(HuggingFaceEmbeddings=Embeddings),
        "langchain_ollama": SimpleNamespace(OllamaLLM=Ollama),
        "langchain_community.vectorstores": SimpleNamespace(FAISS=FAISS),
        "langchain_community.docstore.in_memory": SimpleNamespace(InMemoryDocstore=Store),
        "faiss": SimpleNamespace(write_index=write_index, read_index=read_index),
        "pypdf": SimpleNamespace(PdfReader=reader),
    }
    return modules, calls


def adapters(libraries):
    return load_adapters(import_module=libraries[0].__getitem__)


def test_pdf_loading_preserves_source_and_page_and_ignores_empty_pages(libraries, tmp_path):
    for name in ("b.pdf", "a.PDF", "ignored.txt"):
        (tmp_path / name).write_text("fixture")
    documents = adapters(libraries)[2].load_pdf_files(str(tmp_path))
    assert libraries[1]["pdf_files"] == ["a.PDF", "b.pdf"]
    assert [doc.page_content for doc in documents] == ["A document", "A document"]
    assert documents[0].metadata == {"source": str(tmp_path / "a.PDF"), "page": 0}


def test_chunks_and_embedding_model_use_explicit_options(libraries, monkeypatch):
    monkeypatch.setenv("UOAIC_EMBEDDING_MODEL", "local-model")
    monkeypatch.setenv("UOAIC_EMBEDDING_DEVICE", "cpu")
    chunker, embedding, *_ = adapters(libraries)
    documents = [Document("example")]
    assert chunker.create_chunks(documents) == documents
    embedding.get_embedding_model()
    assert libraries[1]["splitter"] == {"chunk_size": 1000, "chunk_overlap": 200}
    assert libraries[1]["embedding"] == {"model_name": "local-model", "model_kwargs": {"device": "cpu"}}


def test_ollama_adapter_preserves_model_endpoint_and_temperature(libraries, monkeypatch):
    monkeypatch.setenv("UOAIC_MODEL", "qwen")
    monkeypatch.setenv("UOAIC_OLLAMA_ENDPOINT", "http://localhost:9999/")
    monkeypatch.setenv("UOAIC_TEMPERATURE", "0.3")
    adapters(libraries)[3].load_llm()
    assert libraries[1]["ollama"] == {"model": "qwen", "base_url": "http://localhost:9999", "temperature": 0.3}


def test_saved_configuration_overrides_process_environment(libraries, monkeypatch):
    monkeypatch.setenv("UOAIC_MODEL", "old-model")
    model_loader = adapters(libraries)[3]
    model_loader.configure_model({"UOAIC_MODEL": "selected-model", "UOAIC_TEMPERATURE": "0.2"})
    model_loader.load_llm()
    assert libraries[1]["ollama"]["model"] == "selected-model"
    assert libraries[1]["ollama"]["temperature"] == 0.2


def test_document_store_round_trip_preserves_records_and_embeddings(libraries, tmp_path):
    vectorstore = adapters(libraries)[6]
    embedding = object()
    documents = [Document("one", {"source": "guide.pdf", "page": 1}), Document("two")]
    vectorstore.build_vector_db(documents, embedding, str(tmp_path))
    restored = vectorstore.load_vector_db(str(tmp_path), embedding)
    assert restored.embedding_function is embedding
    assert restored.docstore.search("doc-0") == documents[0]
    assert restored.docstore.search("doc-1") == documents[1]
    assert restored.index_to_docstore_id == {0: "doc-0", 1: "doc-1"}
    assert not list(tmp_path.glob("*.pkl"))


@pytest.mark.parametrize("records", [[], {"0": None}, {"0": {"id": 2, "content": "a", "metadata": {}}}, {"0": {"id": "a", "content": "a", "metadata": []}}, {"-1": {"id": "a", "content": "a", "metadata": {}}}, {"0": {"id": "a", "content": "a", "metadata": {}}, "1": {"id": "a", "content": "b", "metadata": {}}}])
def test_loading_rejects_invalid_document_records(libraries, tmp_path, records):
    (tmp_path / "documents.json").write_text(json.dumps(records))
    with pytest.raises(ValueError):
        adapters(libraries)[6].load_vector_db(str(tmp_path), object())


def test_loading_rejects_vector_document_mismatch(libraries, tmp_path):
    vectorstore = adapters(libraries)[6]
    vectorstore.build_vector_db([Document("one")], object(), str(tmp_path))
    (tmp_path / "index.faiss").write_text('{"count": 2}')
    with pytest.raises(ValueError, match="do not match"):
        vectorstore.load_vector_db(str(tmp_path), object())


def test_previous_pickle_index_requires_rebuild(libraries, tmp_path):
    (tmp_path / "index.pkl").write_bytes(b"old index")
    with pytest.raises(ValueError, match="Rebuild"):
        adapters(libraries)[6].load_vector_db(str(tmp_path), object())


@pytest.mark.parametrize("missing", ["langchain_core.documents", "langchain_text_splitters", "langchain_huggingface", "langchain_ollama", "langchain_community.vectorstores", "langchain_community.docstore.in_memory", "faiss", "pypdf"])
def test_missing_backend_dependency_has_actionable_install_hint(libraries, missing):
    def importer(name):
        if name == missing:
            raise ModuleNotFoundError(name, name=name)
        return libraries[0][name]
    with pytest.raises(RuntimeError, match=r"agilab\[local-llm\]"):
        load_adapters(import_module=importer)


@pytest.mark.parametrize("question_request", ["question", {"query": "question"}])
def test_retrieval_chain_returns_answer_and_source_documents(question_request):
    documents = [Document("reference")]
    seen = {}
    db = SimpleNamespace(similarity_search=lambda query, **kwargs: seen.update(query=query, **kwargs) or documents)
    llm = SimpleNamespace(invoke=lambda prompt: seen.update(prompt=prompt) or SimpleNamespace(content="answer"))
    result = RetrievalChain(llm, db, CUSTOM_PROMPT_TEMPLATE).invoke(question_request)
    assert result == {"result": "answer", "source_documents": documents}
    assert seen["query"] == "question" and seen["k"] == 4
    assert "reference" in seen["prompt"] and "Question: question" in seen["prompt"]


def test_real_faiss_index_round_trip_without_model_download(tmp_path):
    pytest.importorskip("faiss")
    community = pytest.importorskip("langchain_community.vectorstores")
    from langchain_core.documents import Document as RealDocument
    from langchain_core.embeddings import Embeddings
    import importlib

    class TinyEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [[float("cat" in text), float("dog" in text)] for text in texts]
        def embed_query(self, text):
            return self.embed_documents([text])[0]

    def importer(name):
        if name == "langchain_huggingface":
            return SimpleNamespace(HuggingFaceEmbeddings=object)
        if name == "langchain_ollama":
            return SimpleNamespace(OllamaLLM=object)
        return importlib.import_module(name)

    vectorstore = load_adapters(import_module=importer)[6]
    embedding = TinyEmbeddings()
    vectorstore.build_vector_db([RealDocument(page_content="cat", metadata={"source": "cats.pdf"}), RealDocument(page_content="dog")], embedding, str(tmp_path))
    restored = vectorstore.load_vector_db(str(tmp_path), embedding)
    assert isinstance(restored, community.FAISS)
    assert restored.similarity_search("cat", k=1)[0].metadata == {"source": "cats.pdf"}
