"""
文本分割规则（用于把一个字段写入两个单元格，例如 I21+I22 / I23+I24）。

当前策略（按用户需求）：
- 中文：只能在“右侧字符为中文(CJK)”的位置断开，尽量靠近中点；禁止在纯英文/数字/符号序列中间断开。
  允许：左侧非中文、右侧中文（例如 "...-12.500m这里是中文" 可以在 '这' 之前断开）。
- 英文：只能在空白处（完整单词之间）断开，尽量靠近中点；优先让右侧以字母开头。
"""

from __future__ import annotations

import re
from typing import Tuple


def _is_cjk(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def split_cn_two_cells(text: str) -> Tuple[str, str]:
    """
    中文两格分割：
    - 选择一个切分点 idx，使得 text[idx] 是中文(CJK)
    - 尽量靠近字符串中点
    - 若找不到任何中文字符，退化为不分割（全放第一格）
    """
    s = (text or "").strip()
    if not s:
        return "", ""

    mid = len(s) // 2
    cands: list[int] = [i for i in range(1, len(s)) if _is_cjk(s[i])]
    if not cands:
        return s, ""

    # choose nearest to mid
    idx = min(cands, key=lambda i: abs(i - mid))
    left, right = s[:idx].rstrip(), s[idx:].lstrip()
    return left, right


def split_en_two_cells(text: str) -> Tuple[str, str]:
    """
    英文两格分割：
    - 只能在空白处分割（完整单词之间）
    - 尽量靠近中点
    - 优先：分割后右侧以字母开头（A-Z/a-z）
    """
    s = _normalize_spaces(text or "")
    if not s:
        return "", ""

    mid = len(s) // 2

    # whitespace split points (index points into string)
    cands = [m.start() for m in re.finditer(r"\s+", s)]
    if not cands:
        return s, ""

    def score(i: int) -> tuple[int, int]:
        # primary: whether right side begins with a letter (0 best, 1 worse)
        right = s[i:].lstrip()
        right_ok = 0 if (right and right[0].isalpha()) else 1
        return (right_ok, abs(i - mid))

    idx = min(cands, key=score)
    left, right = s[:idx].rstrip(), s[idx:].lstrip()
    return left, right


__all__ = ["split_cn_two_cells", "split_en_two_cells"]
