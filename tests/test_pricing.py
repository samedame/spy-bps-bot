import math, pytest
from bps_bot import pricing as P
from bps_bot.spec import SPEC

def test_ndtr_basic():
    assert abs(P.ndtr(0)-0.5)<1e-15 and abs(P.ndtr(1.959963984540054)-0.975)<1e-12 and P.ndtr(-40) < 1e-300 and P.ndtr(40)==1.0

def test_put_call_parity_like_bounds():
    S,K,T,r,q=100,95,30/365,0.04,0.015; sig=0.2
    p=P.put_price(S,K,T,r,q,sig); assert 0 < p < K*math.exp(-r*T)
    assert P.put_price(S,K,0,r,q,sig)==0.0 and P.put_price(S,110,0,r,q,sig)==10

def test_strike_for_delta_is_near_40_delta():
    S,vix,r,q=760.0,19.45,0.04988,0.015
    k=P.strike_for_delta(S,14,r,q,vix,0.40)
    d=abs(P.put_delta(S,k,14/365,r,q,P.sigma_k(S,k,14,vix)))
    assert 0.36 < d < 0.44 and k < S

def test_today_matches_published_deployability_before_fees():
    """results/deployability.json (research, 2026-10-23) is a simplified 1-lot illustration: 754/716, credit 7.2128/share and
    max loss 3078.72 are BEFORE the two $0.67 entry fees. The engine (and the bot) size on the after-fee numbers."""
    S,vix,tnx=759.969970703125,19.450000762939453,4.98799991607666
    r=max(tnx/100,0.0); q=SPEC.div_yield
    ks=P.strike_for_delta(S,14,r,q,vix,0.40); kl=max(round(ks-0.05*S),1)
    assert (ks,kl)==(754,716)
    cf=P.fill_cashflow([(-1,ks),(1,kl)],S,r,q,vix,[14,14],SPEC,True)
    fees=2*SPEC.fee_per_leg
    assert abs((cf+fees)/100-7.212799877564134)<1e-9                     # published credit, before fees
    assert abs(P.max_loss_with_credit([(-1,ks),(1,kl)],cf)-(3078.7200122435866+fees))<1e-8   # engine max loss = published + fees
