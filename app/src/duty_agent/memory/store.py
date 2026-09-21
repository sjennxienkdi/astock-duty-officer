"""研究记忆 KB 的索引与检索（plan §6）：BM25 + 向量，RRF 融合 top5。

向量侧优先 sqlite-vec，装不上则退回 numpy 余弦——语料只有几十块，两种都够快。
"""

from __future__ import annotations

import re
import sqlite3
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

DIM = 256
RRF_K = 60


def _digest_int(token: str) -> int:
    """跨进程稳定的整数摘要：`hash()` 会被 PYTHONHASHSEED 随机化，KB 不能依赖它。"""
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def _digest(text: str) -> str:
    return f"{_digest_int(text):08x}"


_TABLES = """
CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    code        TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    text        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_vecs (
    chunk_id   TEXT PRIMARY KEY,
    embedding  BLOB NOT NULL
);
"""
_TOKEN = re.compile(r"[a-z0-9_]+|[一-鿿]")


def tokenize(text: str) -> list[str]:
    """中文取单字并组 bigram，ASCII 取词——不引分词器依赖。"""
    chars = _TOKEN.findall(text.lower())
    unigrams = [c for c in chars if len(c) == 1 and "一" <= c <= "鿿"]
    bigrams = ["".join(pair) for pair in zip(unigrams, unigrams[1:], strict=False)]
    words = [c for c in chars if len(c) > 1]
    return words + unigrams + bigrams


def hash_embed(text: str, dim: int = DIM) -> np.ndarray:
    """确定性 hash embedding：同一个词永远落在同一维，展示模式不需要真实模型。"""
    vector = np.zeros(dim, dtype=np.float32)
    for index, token in enumerate(tokenize(text)):
        slot = _digest_int(token) % dim
        vector[slot] += 1.0 if index % 2 == 0 else -1.0
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0.0 else vector / norm


@dataclass(frozen=True)
class Chunk:
    """一个可召回的知识块。"""

    doc_id: str
    code: str
    doc_type: str
    as_of: str
    source_tier: str
    text: str

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}#{_digest(self.text)}"

    @property
    def citation(self) -> str:
        return f"[{self.doc_id}@{self.as_of}]"


@dataclass(frozen=True)
class Recalled:
    """一次召回结果。"""

    chunk: Chunk
    score: float


@dataclass
class KbStore:
    """KB 存储：SQLite 存块与向量，检索期在内存里建 BM25。"""

    db_path: Path
    _conn: sqlite3.Connection | None = None
    _vec_ready: bool | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # 工具在 langgraph 的工作线程里执行，连接必须允许跨线程使用
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_TABLES)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> KbStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def reset(self) -> None:
        self.conn.execute("DELETE FROM kb_chunks")
        self.conn.execute("DELETE FROM kb_vecs")
        self.conn.commit()

    def upsert(self, chunks: Iterable[Chunk]) -> int:
        """写入知识块与向量，返回写入数。"""
        count = 0
        for chunk in chunks:
            self.conn.execute(
                "INSERT OR REPLACE INTO kb_chunks"
                " (chunk_id, doc_id, code, doc_type, as_of, source_tier, text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.code,
                    chunk.doc_type,
                    chunk.as_of,
                    chunk.source_tier,
                    chunk.text,
                ),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO kb_vecs (chunk_id, embedding) VALUES (?, ?)",
                (chunk.chunk_id, hash_embed(chunk.text).tobytes()),
            )
            count += 1
        self.conn.commit()
        return count

    def chunks(self, doc_type: str = "", code: str = "") -> list[Chunk]:
        clauses, args = [], []
        if doc_type:
            clauses.append("doc_type = ?")
            args.append(doc_type)
        if code:
            clauses.append("code = ?")
            args.append(code)
        sql = "SELECT * FROM kb_chunks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(sql + " ORDER BY chunk_id", args).fetchall()
        return [
            Chunk(
                doc_id=r["doc_id"],
                code=r["code"],
                doc_type=r["doc_type"],
                as_of=r["as_of"],
                source_tier=r["source_tier"],
                text=r["text"],
            )
            for r in rows
        ]

    def search(
        self, query: str, *, doc_type: str = "", code: str = "", top_k: int = 5
    ) -> list[Recalled]:
        """BM25 与向量各出候选，RRF 融合。"""
        pool = self.chunks(doc_type=doc_type, code=code)
        if not pool:
            return []
        bm25 = BM25Okapi([tokenize(c.text) for c in pool])
        bm25_rank = {
            pool[i].chunk_id: rank
            for rank, i in enumerate(
                sorted(range(len(pool)), key=lambda i: -float(bm25.get_scores(tokenize(query))[i]))
            )
        }
        vec_rank = self._vector_rank(query, pool)
        fused = sorted(
            pool,
            key=lambda c: (
                -(
                    1 / (RRF_K + bm25_rank[c.chunk_id])
                    + 1 / (RRF_K + vec_rank.get(c.chunk_id, len(pool)))
                )
            ),
        )
        return [
            Recalled(
                chunk=c,
                score=1 / (RRF_K + bm25_rank[c.chunk_id])
                + 1 / (RRF_K + vec_rank.get(c.chunk_id, len(pool))),
            )
            for c in fused[:top_k]
        ]

    def _vector_rank(self, query: str, pool: Sequence[Chunk]) -> dict[str, int]:
        """sqlite-vec 可用则用之，否则 numpy 余弦。"""
        if self._vec_enabled():
            ordered = self._vec_query(query, len(pool))
            if ordered is not None:
                return {chunk_id: rank for rank, chunk_id in enumerate(ordered)}
        matrix = np.stack([hash_embed(c.text) for c in pool])
        scores = matrix @ hash_embed(query)
        order = np.argsort(-scores)
        return {pool[int(i)].chunk_id: rank for rank, i in enumerate(order)}

    def _vec_enabled(self) -> bool:
        if self._vec_ready is None:
            try:
                import sqlite_vec

                self.conn.enable_load_extension(True)
                sqlite_vec.load(self.conn)
                self.conn.enable_load_extension(False)
                self.conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_kb USING vec0(embedding float[?])",
                    (DIM,),
                )
                self.conn.execute("DELETE FROM vec_kb")
                for chunk in self.chunks():
                    self.conn.execute(
                        "INSERT INTO vec_kb (rowid, embedding) VALUES (?, ?)",
                        (
                            _digest_int(chunk.chunk_id),
                            sqlite_vec.serialize_float32(hash_embed(chunk.text).tolist()),
                        ),
                    )
                self.conn.commit()
                self._vec_ready = True
            except Exception:  # sqlite 构建不支持扩展则整体回退 numpy
                self._vec_ready = False
        return bool(self._vec_ready)

    def _vec_query(self, query: str, limit: int) -> list[str] | None:
        try:
            import sqlite_vec

            rows = self.conn.execute(
                "SELECT rowid FROM vec_kb WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (sqlite_vec.serialize_float32(hash_embed(query).tolist()), limit),
            ).fetchall()
        except Exception:
            return None
        known = {_digest_int(c.chunk_id): c.chunk_id for c in self.chunks()}
        return [known[r["rowid"]] for r in rows if r["rowid"] in known]
