import re


class MarkdownSplitter:
    """Split markdown documents at heading boundaries, then pieces over max_chunk_size characters."""

    def __init__(self, max_chunk_size: int):
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
        
        return self._apply_max_chunk_size(chunks)
    
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
