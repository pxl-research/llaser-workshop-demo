#!/usr/bin/env python3
# -----------------------------------------------------------------
# Splitter (used before ingestion)
# -----------------------------------------------------------------
import re
from typing import Optional
from abc import ABC, abstractmethod
from .Embedding_Provider import BaseEmbeddingModel
import numpy as np

class Splitter(ABC):
    @abstractmethod
    def split(self, docs: list[str]) -> list[str]:
        pass


class TokenBasedSplitter(Splitter):
    def __init__(self, embedding_model: BaseEmbeddingModel,
                 max_tokens: Optional[int]
    ):
        self.embedding_model = embedding_model
        self.max_tokens = (
            max_tokens if max_tokens is not None
            else self.embedding_model.get_max_token_count()
        )

    def split(self, docs: list[str]) -> list[str]:
        chunks = []
        max_chars = self.max_tokens
        for doc in docs:
            text = doc
            # Iterate over the text, splitting it into chunks of max_chars size
            for i in range(0, len(text), max_chars):
                chunk = text[i:i + max_chars]
                chunks.append(chunk)

        return chunks
    
class SemanticSplitter:
    def __init__(self, embedding_model, threshold_percentile=95, buffer_size=1):
        self.model = embedding_model 
        self.threshold_percentile = threshold_percentile
        # buffer_size adds surrounding sentences to the embedding to reduce noise
        self.buffer_size = buffer_size 

    def _cosine_similarity(self, a, b):
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        # Prevent division by zero errors
        if norm_a == 0 or norm_b == 0:
            return 0.0
            
        return np.dot(a, b) / (norm_a * norm_b)

    def split(self, text: str) -> list[str]:
        if isinstance(text, list):
            text = " ".join(text)
        
        # 1. Split into sentences and filter out empty strings
        # Note: Consider replacing this regex with a library like spaCy or NLTK for production
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

        if len(sentences) < 2:
           return sentences

        # 2. Create contextual buffers (sliding window)
        # This prevents the "noisy single sentence" problem
        combined_sentences = []
        for i in range(len(sentences)):
            start = max(0, i - self.buffer_size)
            end = min(len(sentences), i + self.buffer_size + 1)
            combined_sentences.append(" ".join(sentences[start:end]))

        # 3. Get embeddings for buffered sentences
        embeddings = self.model.embed_documents(combined_sentences)

        # 4. Calculate distances
        distances = []
        for i in range(len(embeddings) - 1):
            sim = self._cosine_similarity(embeddings[i], embeddings[i+1])
            distances.append(1 - sim)

        # 5. Determine meaning jumps
        if not distances:
            return [" ".join(sentences)]
            
        breakpoint_distance_threshold = np.percentile(distances, self.threshold_percentile)

        chunks = []
        current_chunk = [sentences[0]]
        
        for i, distance in enumerate(distances):
            if distance > breakpoint_distance_threshold:
                # Meaning changed significantly, start a new chunk
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentences[i + 1]]
            else:
                current_chunk.append(sentences[i + 1])
                
        # Append the final working chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks


class MarkdownSplitter(Splitter):
    """Split markdown documents at heading boundaries and optionally at code blocks."""
    
    def __init__(self, split_on_code_blocks: bool = False, max_chunk_size: Optional[int] = None):
        """
        Initialize the MarkdownSplitter.
        
        Args:
            split_on_code_blocks: If True, splits at code block boundaries (```...```)
            max_chunk_size: Optional maximum characters per chunk. If exceeded, will split further.
        """
        self.split_on_code_blocks = split_on_code_blocks
        self.max_chunk_size = max_chunk_size
    
    def split(self, docs: list[str]) -> list[str]:
        """
        Split markdown documents at heading boundaries.
        
        Args:
            docs: List of markdown documents
            
        Returns:
            List of markdown chunks
        """
        chunks = []
        
        for doc in docs:
            chunks.extend(self._split_single_document(doc))
        
        return chunks
    
    def _split_single_document(self, doc: str) -> list[str]:
        """Split a single markdown document."""
        if self.split_on_code_blocks:
            doc = self._preserve_code_blocks(doc)
        
        # Split on markdown headings (# ## ### etc.)
        # Pattern matches lines that start with one or more # followed by space
        heading_pattern = r'^(#{1,6})\s+'
        
        # Split while keeping the heading with the content that follows
        chunks = []
        current_chunk = []
        
        lines = doc.split('\n')
        
        for line in lines:
            if re.match(heading_pattern, line):
                # Found a heading
                if current_chunk:
                    chunk_text = '\n'.join(current_chunk).strip()
                    if chunk_text:
                        chunks.append(chunk_text)
                    current_chunk = []
                current_chunk.append(line)
            else:
                current_chunk.append(line)
        
        # Append the last chunk
        if current_chunk:
            chunk_text = '\n'.join(current_chunk).strip()
            if chunk_text:
                chunks.append(chunk_text)
        
        # Split chunks further if they exceed max_chunk_size
        if self.max_chunk_size:
            chunks = self._apply_max_chunk_size(chunks)
        
        return chunks
    
    def _apply_max_chunk_size(self, chunks: list[str]) -> list[str]:
        """Split chunks that exceed max_chunk_size."""
        result = []
        
        for chunk in chunks:
            if len(chunk) <= self.max_chunk_size:
                result.append(chunk)
            else:
                heading, _, body = chunk.partition('\n')
                if re.match(r'^#{1,6}\s+', heading) and len(heading) < self.max_chunk_size / 2:
                    # Repeat the heading on every piece so each keeps its topic
                    full_limit = self.max_chunk_size
                    self.max_chunk_size = full_limit - len(heading) - 1
                    try:
                        sub_chunks = self._split_by_sentences(body.strip())
                    finally:
                        self.max_chunk_size = full_limit
                    result.extend(f"{heading}\n{piece}" for piece in sub_chunks)
                else:
                    # Split large chunks by sentences
                    result.extend(self._split_by_sentences(chunk))
        
        return result
    
    def _split_by_sentences(self, text: str) -> list[str]:
        """Split text by sentences, hard-wrapping any piece still over max_chunk_size."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return self._pack(sentences, ' ', lambda piece: self._wrap(piece, 0))

    def _pack(self, parts: list[str], separator: str, fallback) -> list[str]:
        """Greedily join parts with separator into chunks <= max_chunk_size.

        A part longer than max_chunk_size is flushed on its own via fallback(part).
        """
        result = []
        current = []
        current_length = 0

        for part in parts:
            if len(part) > self.max_chunk_size:
                if current:
                    result.append(separator.join(current))
                    current, current_length = [], 0
                result.extend(fallback(part))
                continue

            added_length = len(part) + (len(separator) if current else 0)
            if current_length + added_length <= self.max_chunk_size:
                current.append(part)
                current_length += added_length
            else:
                result.append(separator.join(current))
                current, current_length = [part], len(part)

        if current:
            result.append(separator.join(current))

        return result

    def _wrap(self, text: str, level: int) -> list[str]:
        """Split an oversized piece on newlines, then whitespace, then a hard cut."""
        if len(text) <= self.max_chunk_size:
            return [text]
        if level == 0:
            lines = [line for line in text.split('\n') if line.strip()]
            return self._pack(lines, '\n', lambda piece: self._wrap(piece, 1))
        if level == 1:
            return self._pack(text.split(), ' ', lambda piece: self._wrap(piece, 2))
        size = self.max_chunk_size
        return [text[i:i + size] for i in range(0, len(text), size)]

    def _preserve_code_blocks(self, doc: str) -> str:
        """
        Temporarily replace code blocks with placeholders to prevent
        splitting within code sections.
        """
        code_blocks = []
        pattern = r'```[\s\S]*?```'
        
        def replace_code_block(match):
            code_blocks.append(match.group(0))
            return f"[CODE_BLOCK_{len(code_blocks) - 1}]"
        
        doc = re.sub(pattern, replace_code_block, doc)
        
        # Restore code blocks (optional, could keep as placeholders)
        # For now we're just removing them from heading-based splitting
        
        return doc