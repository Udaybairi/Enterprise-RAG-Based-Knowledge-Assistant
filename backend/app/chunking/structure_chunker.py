"""Structure-aware chunking.

Chunks never cross a section boundary; headings are kept with their content,
tables/lists are kept whole where they fit (tables are split on row boundaries
with the header repeated), small sibling sections are merged, and overlap is
taken from whole sentences of the previous chunk within the same section.
"""
from __future__ import annotations

from app.chunking.base import Chunker, Unit, blocks_to_units, group_by_section, make_chunk, overlap_tail
from app.ingestion.types import ChunkData, ExtractedDocument


class StructureChunker(Chunker):
    name = "structure"

    def split(self, doc: ExtractedDocument) -> list[ChunkData]:
        units = blocks_to_units(doc.blocks, self.chunk_size)
        groups = self._merge_small(group_by_section(units))
        chunks: list[ChunkData] = []
        for group in groups:
            chunks.extend(self._pack(group))
        return chunks

    def _merge_small(self, groups: list[list[Unit]]) -> list[list[Unit]]:
        """Merge heading-only groups into the following group, and tiny *sibling* sections
        (same parent heading) together. Unrelated sections are never merged."""
        min_size = self.chunk_size // 4
        out: list[list[Unit]] = []
        for g in groups:
            size = sum(len(u.text) for u in g)
            if out:
                prev = out[-1]
                prev_size = sum(len(u.text) for u in prev)
                only_heading = all(u.kind == "heading" for u in prev)
                siblings = bool(_common_prefix([_section_of(prev), _section_of(g)]))
                if prev_size + size <= self.chunk_size and (only_heading or (prev_size < min_size and siblings)):
                    prev.extend(g)
                    continue
            out.append(list(g))
        return out

    def _pack(self, group: list[Unit]) -> list[ChunkData]:
        heading = [u for u in group[:1] if u.kind == "heading"]
        body_sections = list(dict.fromkeys(u.section for u in group if u.kind != "heading" and u.section))
        if len(body_sections) > 1:  # merged siblings → label with the shared parent section
            section = " > ".join(_common_prefix([s.split(" > ") for s in body_sections])) or body_sections[0]
        else:
            section = body_sections[0] if body_sections else (group[0].section if group else None)
        chunks: list[ChunkData] = []
        current: list[Unit] = []
        size = 0
        for u in group:
            if current and size + len(u.text) + 2 > self.chunk_size:
                chunks.append(make_chunk(current, section))
                tail = overlap_tail(current, self.chunk_overlap)
                # repeat the heading so every chunk is self-describing
                current = (heading if heading and heading[0] not in tail else []) + tail
                size = sum(len(x.text) + 2 for x in current)
            current.append(u)
            size += len(u.text) + 2
        if current and any(x.kind != "heading" for x in current):
            chunks.append(make_chunk(current, section))
        elif current and not chunks:
            chunks.append(make_chunk(current, section))
        return chunks


def _section_of(group: list[Unit]) -> list[str]:
    sec = next((u.section for u in group if u.kind != "heading" and u.section), None) or group[0].section or ""
    return sec.split(" > ") if sec else []


def _common_prefix(paths: list[list[str]]) -> list[str]:
    if not paths or any(not p for p in paths):
        return []
    out = []
    for parts in zip(*paths):
        if len(set(parts)) != 1:
            break
        out.append(parts[0])
    return out
