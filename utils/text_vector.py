import hashlib
import math

from collections.abc import Sequence

_HASH_DIMS = 256


def split_chunks(text: str, *, chunk_chars: int, overlap: int) -> list[str]:
    """
    按字符窗口切分文本

    :param text: 原始文本
    :param chunk_chars: 切片长度
    :param overlap: 相邻切片重叠长度
    :return:
    """
    normalized = text.strip()
    if not normalized:
        return []
    if chunk_chars <= 0 or len(normalized) <= chunk_chars:
        return [normalized]
    step = max(chunk_chars - max(overlap, 0), 1)
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        piece = normalized[start : start + chunk_chars].strip()
        if piece:
            chunks.append(piece)
        if start + chunk_chars >= len(normalized):
            break
        start += step
    return chunks


def hash_embed(text: str, *, dims: int = _HASH_DIMS) -> list[float]:
    """
    生成可复现的局部哈希向量，供记忆检索使用

    :param text: 文本
    :param dims: 向量维度
    :return:
    """
    vector = [0.0] * dims
    normalized = ' '.join(text.lower().split())
    if not normalized:
        return vector
    grams = [normalized[index : index + 2] for index in range(len(normalized) - 1)] or [normalized]
    for gram in grams:
        digest = hashlib.md5(gram.encode(), usedforsecurity=False).digest()
        first = int.from_bytes(digest[:4], 'little')
        second = int.from_bytes(digest[4:8], 'little')
        vector[first % dims] += 1.0
        vector[second % dims] -= 0.35
    return _l2_normalize(vector)


def _l2_normalize(vector: Sequence[float]) -> list[float]:
    """
    对向量做 L2 归一化

    :param vector: 原始向量
    :return:
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]
