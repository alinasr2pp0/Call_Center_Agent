"""RAG: everything that finds knowledge for the Agent.

knowledge.py  entry point: cached index + ``search``     text.py       Arabic/English normalisation, tokens
bm25.py       keyword index + coverage score             retrieval.py  BM25 + vectors fused (RRF) + reranker
documents.py  PDF/DOCX/TXT -> chunks -> KB articles      semantic/     embeddings, vector stores (SQLite/Qdrant)
"""
