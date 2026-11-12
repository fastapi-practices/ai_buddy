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
