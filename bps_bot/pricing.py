"""Black-Scholes proxy pricing, written to mirror research/code/01_engine.py operation-for-operation.
Standard library only (math.erf/erfc instead of scipy). The verification suite checks it against the research engine."""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from .spec import SPEC, Spec

Leg = Tuple[int, float]  # (signed contracts, strike); puts only
_SQRT1_2 = 0.7071067811865476


def ndtr(x: float) -> float:
    """Standard normal CDF, same branch structure as scipy.special.ndtr (cephes)."""
    z = x * _SQRT1_2
    if abs(z) < _SQRT1_2:
        return 0.5 + 0.5 * math.erf(z)
    y = 0.5 * math.erfc(abs(z))
    return 1.0 - y if z > 0 else y


def sigma_k(S: float, K: float, Td: float, vix: float, sp: Spec = SPEC) -> float:
    a = max(vix / 100.0, sp.vix_floor) * (1 + sp.iv_term_slope * math.log(max(Td, 1) / 30.0))
    a = max(a, sp.iv_floor)
    lm = math.log(S / K)
    return a * (1 + sp.skew_down * max(lm, 0.0) - sp.skew_up * max(-lm, 0.0))


def put_price(S: float, K: float, T: float, r: float, q: float, sig: float) -> float:
    if T <= 0:
        return max(K - S, 0.0)
    sq = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / sq
    d2 = d1 - sq
    return K * math.exp(-r * T) * ndtr(-d2) - S * math.exp(-q * T) * ndtr(-d1)


def put_delta(S: float, K: float, T: float, r: float, q: float, sig: float) -> float:
    if T <= 0:
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    return -math.exp(-q * T) * ndtr(-d1)


def strike_for_delta(S: float, Td: float, r: float, q: float, vix: float, target_abs_delta: float, sp: Spec = SPEC) -> int:
    """Bisection on BS put delta, then round to the nearest $1 (Python round, as in the research)."""
    lo, hi = S * sp.bisect_lo, S * sp.bisect_hi
    T = Td / 365.0
    for _ in range(sp.bisect_iters):
        mid = 0.5 * (lo + hi)
        dl = abs(put_delta(S, mid, T, r, q, sigma_k(S, mid, Td, vix, sp)))
        if dl > target_abs_delta:
            hi = mid
        else:
            lo = mid
    return round(0.5 * (lo + hi))


def half_spread(mid: float, far: bool, sp: Spec = SPEC) -> float:
    hs = max(sp.hs_floor, sp.hs_pct * mid + sp.hs_add)
    if far:
        hs *= sp.hs_far_mult
    return hs * 1.0


def leg_mid(K: float, S: float, r: float, q: float, vix: float, days: float, sp: Spec = SPEC) -> float:
    return put_price(S, K, days / 365.0, r, q, sigma_k(S, K, max(days, 0.5), vix, sp))


def fill_cashflow(legs: Sequence[Leg], S: float, r: float, q: float, vix: float, days_list: Sequence[float],
                  sp: Spec = SPEC, opening: bool = True) -> float:
    """Cash flow TO the trader (+ credit) for opening (or, with opening=False, closing) the legs at modeled bid/ask."""
    cf = 0.0
    for (qty, K), dd in zip(legs, days_list):
        m = leg_mid(K, S, r, q, vix, dd, sp)
        far = abs(math.log(S / K)) > sp.far_log_moneyness
        hs = half_spread(m, far, sp)
        side = qty if opening else -qty  # > 0 = buying
        px = m + sp.slip_frac * hs if side > 0 else m - sp.slip_frac * hs
        px = max(px, 0.0)
        cf += (-side) * px * 100 - abs(qty) * sp.fee_per_leg
    return cf


def intrinsic_cashflow(legs: Sequence[Leg], S: float) -> float:
    cf = 0.0
    for qty, K in legs:
        cf += qty * max(K - S, 0.0) * 100
    return cf


def max_loss_with_credit(legs: Sequence[Leg], net_credit: float) -> float:
    """Worst expiry payoff over a strike grid, as in the research; > 0 means max loss including the credit."""
    Ks = sorted(set(K for _, K in legs))
    tests = [0.01] + Ks + [max(Ks) * 3]
    worst = 0.0
    for s in tests:
        v = sum(qty * max(K - s, 0.0) * 100 for qty, K in legs)
        worst = min(worst, v)
    return -(net_credit + worst)
