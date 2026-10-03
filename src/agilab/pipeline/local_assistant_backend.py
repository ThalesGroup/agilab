"""PDF retrieval and Ollama adapters for the optional local assistant.

The adapters match AGILAB's existing seven-part retrieval contract. Dependencies
are imported only when a user requests retrieval, keeping bare installs small.
The local vector index stores document metadata as JSON rather than pickle.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

CUSTOM_PROMPT_TEMPLATE = (
    "Answer the question using the following document excerpts. "
    "If the excerpts do not contain the answer, say so.\n\n"
    "{context}\n\nQuestion: {question}\nAnswer:"
)


class RetrievalChain:
    def __init__(self, llm: Any, db: Any, prompt: str) -> None:
        self.llm, self.db, self.prompt = llm, db, prompt

    def invoke(self, request: str | dict[str, Any]) -> dict[str, Any]:
        question = request if isinstance(request, str) else str(request.get("query", ""))
        documents = self.db.similarity_search(question, k=4)
        context = "\n\n".join(document.page_content for document in documents)
        response = self.llm.invoke(self.prompt.format(context=context, question=question))
        answer = response.content if hasattr(response, "content") else response
        return {"result": str(answer), "source_documents": documents}


def load_adapters(*, import_module: Callable[[str], Any] = importlib.import_module) -> tuple[Any, ...]:
    """Load the explicitly declared retrieval libraries, with actionable errors."""
    try:
        Document = import_module("langchain_core.documents").Document
        splitter_class = import_module("langchain_text_splitters").RecursiveCharacterTextSplitter
        embeddings_class = import_module("langchain_huggingface").HuggingFaceEmbeddings
        ollama_class = import_module("langchain_ollama").OllamaLLM
        faiss_class = import_module("langchain_community.vectorstores").FAISS
        docstore_class = import_module("langchain_community.docstore.in_memory").InMemoryDocstore
        faiss = import_module("faiss")
        reader_class = import_module("pypdf").PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Install the local assistant dependencies with `uv pip install \"agilab[local-llm]\"` "
            f"to enable PDF retrieval ({exc})."
        ) from exc

    def create_chunks(documents: list[Any]) -> list[Any]:
        return splitter_class(chunk_size=1000, chunk_overlap=200).split_documents(documents)

    def load_embedding_model() -> Any:
        return embeddings_class(
            model_name=os.getenv("UOAIC_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
            model_kwargs={"device": os.getenv("UOAIC_EMBEDDING_DEVICE", "cpu")},
        )

    def load_pdf_files(directory: str) -> list[Any]:
        documents = []
        for path in sorted(Path(directory).rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            for page_number, page in enumerate(reader_class(str(path)).pages):
                text = page.extract_text() or ""
                if text.strip():
                    documents.append(Document(page_content=text, metadata={"source": str(path), "page": page_number}))
        return documents

    model_configuration = {}

    def configure_model(configuration: dict[str, str]) -> None:
        model_configuration.update(configuration)

    def configured(name: str, default: str) -> str:
        return str(model_configuration.get(name) or os.getenv(name, default))

    def load_llm() -> Any:
        endpoint = configured("UOAIC_OLLAMA_ENDPOINT", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        return ollama_class(
            model=configured("UOAIC_MODEL", "mistral"),
            base_url=endpoint.rstrip("/"),
            temperature=float(configured("UOAIC_TEMPERATURE", "0.1")),
        )

    def build_vector_db(documents: list[Any], embeddings: Any, directory: str) -> Any:
        db = faiss_class.from_documents(documents, embeddings)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        records = {
            str(index): {
                "id": identifier,
                "content": db.docstore.search(identifier).page_content,
                "metadata": db.docstore.search(identifier).metadata,
            }
            for index, identifier in db.index_to_docstore_id.items()
        }
        faiss.write_index(db.index, str(target / "index.faiss"))
        (target / "documents.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        return db

    def load_vector_db(directory: str, embeddings: Any) -> Any:
        target = Path(directory)
        try:
            records = json.loads((target / "documents.json").read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("Rebuild the local assistant index to create its JSON document store.") from exc
        if not isinstance(records, dict):
            raise ValueError("Invalid local assistant document store")
        mapping, documents = {}, {}
        for raw_index, record in records.items():
            index = int(raw_index)
            if index < 0 or not isinstance(record, dict):
                raise ValueError("Invalid local assistant document record")
            identifier, content, metadata = record.get("id"), record.get("content"), record.get("metadata")
            if not isinstance(identifier, str) or not isinstance(content, str) or not isinstance(metadata, dict):
                raise ValueError("Invalid local assistant document record")
            if identifier in documents or index in mapping:
                raise ValueError("Duplicate local assistant document record")
            mapping[index] = identifier
            documents[identifier] = Document(page_content=content, metadata=metadata)
        index = faiss.read_index(str(target / "index.faiss"))
        if set(mapping) != set(range(index.ntotal)):
            raise ValueError("Local assistant vector index and documents do not match; rebuild the index.")
        return faiss_class(embeddings, index, docstore_class(documents), mapping)

    return (
        SimpleNamespace(create_chunks=create_chunks),
        SimpleNamespace(get_embedding_model=load_embedding_model),
        SimpleNamespace(load_pdf_files=load_pdf_files),
        SimpleNamespace(load_llm=load_llm, configure_model=configure_model),
        SimpleNamespace(CUSTOM_PROMPT_TEMPLATE=CUSTOM_PROMPT_TEMPLATE, set_custom_prompt=lambda text: text),
        SimpleNamespace(setup_qa_chain=RetrievalChain),
        SimpleNamespace(build_vector_db=build_vector_db, load_vector_db=load_vector_db),
    )
