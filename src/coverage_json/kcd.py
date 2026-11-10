"""KCD 범위(C00~C14, D47.1) → kcd_code_patterns 정규식."""

import re

_CODE = re.compile(r"^([A-Z])(\d{2})(?:\.(\d{1,2}))?$")
_SUB = r"(\.[0-9]{1,2})?"


def _num_range(lo: int, hi: int) -> str:
    """두 자리 숫자 범위 lo~hi 를 정규식으로 (00~99)."""
    parts = []
    a = lo
    while a <= hi:
        tens, ones = divmod(a, 10)
        end = min(hi, tens * 10 + 9)
        if a % 10 == 0 and end == tens * 10 + 9:
            parts.append(f"{tens}[0-9]")
        elif a == end:
            parts.append(f"{a:02d}")
        else:
            parts.append(f"{tens}[{ones}-{end % 10}]")
        a = end + 1
    return parts[0] if len(parts) == 1 else "(" + "|".join(parts) + ")"


def range_to_patterns(start: str, end: str) -> list[str]:
    """C00~C14 → ['^C(0[0-9]|1[0-4])(\\.[0-9]{1,2})?$'], D47.1 → ['^D47\\.1[0-9]?$']."""
    s, e = _CODE.match(start.strip().upper()), _CODE.match(end.strip().upper())
    if not s or not e:
        raise ValueError(f"KCD 형식이 아닙니다: {start}~{end}")
    if s.group(3) or e.group(3):  # 세분류 코드 (D47.1, N39.3~N39.4)
        if (s.group(1), s.group(2)) != (e.group(1), e.group(2)):
            raise ValueError(f"세분류 범위는 같은 3자리 안에서만: {start}~{end}")
        lo, hi = int(s.group(3) or 0), int(e.group(3) or 9)
        head = f"{s.group(1)}{s.group(2)}"
        if lo == hi:
            return [f"^{head}\\.{lo}[0-9]?$"]
        return [f"^{head}\\.[{lo}-{hi}][0-9]?$"]
    if s.group(1) != e.group(1):
        raise ValueError(f"알파벳이 다른 범위는 나눠서 주세요: {start}~{end}")
    lo, hi = int(s.group(2)), int(e.group(2))
    return [f"^{s.group(1)}{_num_range(lo, hi)}{_SUB}$"]


def matches(code: str, patterns: list[str]) -> bool:
    return any(re.match(p, code.strip().upper()) for p in patterns)
