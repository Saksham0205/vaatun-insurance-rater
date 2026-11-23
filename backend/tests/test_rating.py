from app.rating import resolve
from app.schemas import PolicyFacts

def test_standalone_tp_od_is_not_applicable():
    facts=PolicyFacts(insurer="Go Digit",policy_type="Standalone TP")
    result=resolve(facts,"policy.pdf")
    assert result.od.status=="not_applicable"
    assert result.od.applicable is False
    assert result.od.rate_percent is None

def test_missing_insurer_is_ambiguous():
    result=resolve(PolicyFacts(),"policy.pdf")
    assert result.status=="ambiguous"
    assert result.tp.rate_percent is None

def test_unknown_insurer_fails_closed():
    result=resolve(PolicyFacts(insurer="Unknown Insurance"),"policy.pdf")
    assert result.status=="unsupported"
    assert result.od.rate_percent is None
    assert result.tp.rate_percent is None
