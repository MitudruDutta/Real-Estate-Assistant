"""Vector store - optimized ChromaDB wrapper"""
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)


class VectorStore:
    _instance = None
    _embedder = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        from src.config import get_global_settings
        settings = get_global_settings()
        
        Path(settings.chroma_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=settings.chroma_dir)
        self._collection = self._client.get_or_create_collection(
            "articles", 
            metadata={"hnsw:space": "cosine"}
        )
        
        # Lazy load embedder (heavy)
        if VectorStore._embedder is None:
            VectorStore._embedder = SentenceTransformer(settings.embedding_model)
        
        self._initialized = True
        logger.info(f"VectorStore initialized with {self.count()} chunks")
    
    def add(self, content: str, metadata: dict, doc_id: str) -> int:
        """Chunk and add document. Returns chunk count."""
        chunks = self._chunk_text(content)
        if not chunks:
            return 0
        
        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        embeddings = VectorStore._embedder.encode(chunks, show_progress_bar=False).tolist()
        metadatas = [{**metadata, "chunk_idx": i} for i in range(len(chunks))]
        
        try:
            self._collection.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
            return len(chunks)
        except Exception as e:
            logger.error(f"Failed to add chunks for doc {doc_id}: {e}")
            raise  # Re-raise so callers can distinguish failure from zero-chunk result
    
    def search(self, query: str, k: int = 5) -> list[dict]:
        """Semantic search."""
        if self._collection.count() == 0:
            return []
        
        embedding = VectorStore._embedder.encode([query], show_progress_bar=False).tolist()
        results = self._collection.query(
            query_embeddings=embedding, 
            n_results=min(k, self._collection.count()),
            include=["documents", "metadatas", "distances"]
        )
        
        docs = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 1.0
                
                # Convert cosine distance [0,2] to similarity [0,1]
                # ChromaDB cosine distance: dist = 1 - cos_sim, so dist in [0, 2]
                # Similarity = 1 - dist/2 maps [0,2] -> [1,0]
                similarity = 1 - dist / 2
                similarity = min(1.0, max(0.0, similarity))  # Clamp to [0,1]
                
                docs.append({
                    "content": doc,
                    "title": meta.get("title", "Unknown"),
                    "url": meta.get("url", ""),
                    "relevance": round(similarity, 3)
                })
        return docs
    
    def delete_by_article(self, article_id: str):
        """Delete all chunks for an article."""
        try:
            self._collection.delete(where={"article_id": article_id})
        except Exception as e:
            logger.error(f"Failed to delete chunks for article {article_id}: {e}")
            raise  # Re-raise so deletions are not silently ignored
    
    def count(self) -> int:
        return self._collection.count()
    
    def _chunk_text(self, text: str) -> list[str]:
        """Sentence-aware chunking with overlap."""
        from src.config import get_global_settings
        settings = get_global_settings()
        
        # Validate chunk settings to ensure forward progress
        if settings.chunk_overlap >= settings.chunk_size:
            raise ValueError(
                f"chunk_overlap ({settings.chunk_overlap}) must be less than "
                f"chunk_size ({settings.chunk_size})"
            )
        
        text = text[:settings.max_content_length]
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + settings.chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                for sep in ['. ', '.\n', '! ', '? ', '\n\n']:
                    last_sep = text[start:end].rfind(sep)
                    if last_sep > settings.chunk_size // 2:
                        end = start + last_sep + len(sep)
                        break
            
            chunk = text[start:end].strip()
            if len(chunk) > 50:  # Skip tiny chunks
                chunks.append(chunk)
            
            # Ensure forward progress: start must strictly increase
            new_start = end - settings.chunk_overlap
            start = max(new_start, start + 1)  # Guarantee at least 1 char progress
        
        return chunks
