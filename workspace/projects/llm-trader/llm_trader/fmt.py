from __future__ import annotations

P_FLOOR = 0.001


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{digits}%}"


def r_value(x: float | None) -> str:
    if x is None:
        return "n/a"
    value = round(x, 2)
    return "0.00R" if value == 0 else f"{value:+.2f}R"


def p_text(p: float) -> str:
    return f"p < {P_FLOOR:g}" if p < P_FLOOR else f"p = {p:.3f}"


def threshold(x: float) -> str:
    return f"{x:.3g}"


def times(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") + "×"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n:,} {word if n == 1 else (many or word + 's')}"
