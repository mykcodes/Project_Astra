# Knowledge (RAG) Architecture

This directory contains documentation for ASTRA's document ingestion and Retrieval-Augmented Generation (RAG) pipeline.

## Pipeline Stages

1. **Ingestion**: Reading files from disk/web.
2. **Extraction**: Converting PDF/HTML/etc to markdown.
3. **Chunking**: Splitting text into semantic blocks.
4. **Embedding**: Converting text to vectors.
5. **Retrieval**: Vector similarity + BM25 hybrid search.
6. **Reranking**: Cross-encoder reordering for relevance.

For code, see `backend/app/knowledge/`.
