"""
ASTRA Knowledge (RAG) Architecture

Manages personal document ingestion and retrieval.

Pipeline (Future):
Document -> Ingestion -> Extraction -> Chunking -> Embedding -> Vector DB -> Retrieval -> Reranking
"""

from enum import Enum


class PipelineStage(str, Enum):
    INGESTION = "ingestion"
    EXTRACTION = "extraction"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
