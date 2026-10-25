from datetime import date
from bps_bot import calendar_nyse as C

def test_known_holidays():
    for d in [date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),date(2026,5,25),date(2026,6,19),date(2026,7,3),
              date(2026,9,7),date(2026,11,26),date(2026,12,25),date(2027,1,1),date(2027,3,26),date(2022,6,20),date(2021,12,24)]:
        assert not C.is_trading_day(d), d

def test_saturday_new_year_is_not_observed_on_friday():
    assert C.is_trading_day(date(2021,12,31))

def test_special_closures():
    assert not C.is_trading_day(date(2025,1,9)); assert not C.is_trading_day(date(2012,10,29))

def test_navigation():
    assert C.next_trading_day(date(2026,10,23)) == date(2026,10,26)
    assert C.prev_trading_day(date(2026,10,26)) == date(2026,10,23)
    assert C.on_or_after(date(2026,10,24)) == date(2026,10,26)
    assert C.prev_trading_day(date(2026,9,8)) == date(2026,9,4)      # after Labor Day
