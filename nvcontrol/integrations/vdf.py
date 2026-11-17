"""Minimal, order-preserving Valve KeyValues (text VDF) parser/serializer.

Steam's localconfig.vdf / config.vdf / libraryfolders.vdf are text KeyValues.
Unknown content is preserved because dicts keep insertion order.
"""
from __future__ import annotations

from typing import Any

VdfDict = dict[str, Any]

_ESC_IN = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
_ESC_OUT = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}


class VdfError(ValueError):
    pass


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif c in "{}":
            yield c
            i += 1
        elif c == "[":  # conditional like [$WIN32] — skipped
            j = text.find("]", i)
            if j < 0:
                raise VdfError("unterminated conditional")
            i = j + 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(_ESC_IN.get(text[i + 1], "\\" + text[i + 1]))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            if i >= n:
                raise VdfError("unterminated string")
            i += 1
            yield ("s", "".join(buf))
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n{}"':
                j += 1
            yield ("s", text[i:j])
            i = j


def loads(text: str) -> VdfDict:
    root: VdfDict = {}
    stack = [root]
    key = None
    for tok in _tokens(text):
        if tok == "{":
            if key is None:
                raise VdfError("block without key")
            new: VdfDict = {}
            stack[-1][key] = new
            stack.append(new)
            key = None
        elif tok == "}":
            if len(stack) == 1:
                raise VdfError("unbalanced }")
            stack.pop()
        else:
            val = tok[1]
            if key is None:
                key = val
            else:
                stack[-1][key] = val
                key = None
    if len(stack) != 1:
        raise VdfError("unbalanced {")
    return root


def _q(s: str) -> str:
    return '"' + "".join(_ESC_OUT.get(c, c) for c in s) + '"'


def dumps(data: VdfDict, indent: int = 0) -> str:
    out = []
    pad = "\t" * indent
    for k, v in data.items():
        if isinstance(v, dict):
            out.append(f"{pad}{_q(k)}\n{pad}{{\n{dumps(v, indent + 1)}{pad}}}\n")
        else:
            out.append(f"{pad}{_q(k)}\t\t{_q(str(v))}\n")
    return "".join(out)


def get_ci(d: VdfDict, *path: str, create: bool = False) -> Any:
    """Case-insensitive path lookup (Steam mixes 'apps' / 'Apps')."""
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        match = next((k for k in cur if k.lower() == p.lower()), None)
        if match is None:
            if not create:
                return None
            cur[p] = {}
            match = p
        cur = cur[match]
    return cur
