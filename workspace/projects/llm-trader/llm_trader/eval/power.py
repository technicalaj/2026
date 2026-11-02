from __future__ import annotations

import numpy as np

from llm_trader.eval.metrics import t_quantile_975

EDGES_R = (0.02, 0.05, 0.1, 0.2)
TRADE_COUNTS = (30, 100, 300, 600)


def gate_power(
    edges=EDGES_R, trade_counts=TRADE_COUNTS, sims: int = 4000, runs: int = 1000, max_p: float = 0.05, seed: int = 7,
) -> list[dict]:
    # A 1:1 rule: each trade ends at +1R or -1R, so a true edge of e R means winning (1 + e) / 2 of trades.
    # Random entry times with the same geometry have no edge, so their replicas average 0R.
    rng = np.random.default_rng(seed)
    rows = []
    for n in trade_counts:
        if n < 2:
            raise ValueError("gate power needs at least 2 trades per test")
        null = np.sort(2.0 * rng.binomial(n, 0.5, size=runs) / n - 1.0)
        t = t_quantile_975(n - 1)
        for edge in edges:
            mean = 2.0 * rng.binomial(n, (1.0 + edge) / 2.0, size=sims) / n - 1.0
            sd = np.sqrt(np.maximum(1.0 - mean**2, 0.0) * n / (n - 1))
            lower = mean - t * sd / np.sqrt(n)
            p = (1 + runs - np.searchsorted(null, mean, side="left")) / (runs + 1)
            passed = (mean > 0) & (lower > 0) & (p <= max_p)
            rows.append({"edge_r": float(edge), "trades": int(n), "pass_rate": round(float(passed.mean()), 3)})
    return rows
