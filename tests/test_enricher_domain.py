from enricher import _build_domain_candidates


def test_includes_net_variant():
    candidates = _build_domain_candidates("acme", "detroit")
    assert any(".net" in c for c in candidates)


def test_includes_trade_suffix():
    candidates = _build_domain_candidates("acme", "detroit", trade_suffix="plumbing")
    assert any("acmeplumbing" in c for c in candidates)


def test_no_short_names():
    candidates = _build_domain_candidates("ab", "detroit")
    assert candidates == []
