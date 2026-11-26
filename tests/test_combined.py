import pytest

from coldmap.combined import detect_all

from .test_scan import _state


@pytest.fixture(scope="module")
def planted():
    return _state(True)


def test_modes_switch(planted):
    kw = {"scan_kw": {"reps": 499}, "levels": ("county",)}
    both = detect_all(planted, "both", **kw)
    scan_only = detect_all(planted, "scan", **kw)
    window_only = detect_all(planted, "window", **kw)
    assert all(f.found_by == ("scan",) for f in scan_only)
    assert all(f.found_by == ("window",) for f in window_only)
    assert len(both) >= max(len(scan_only), 1)


def test_agreement_is_high_confidence(planted):
    flags = detect_all(planted, "both", scan_kw={"reps": 499}, levels=("county",))
    top = flags[0]
    assert top.place == "A, TL" and top.confidence == "high" and set(top.found_by) == {"scan", "window"}


def test_kind_filter(planted):
    flags = detect_all(planted, "both", scan_kw={"reps": 199}, levels=("county",), kind="accountability")
    assert all(f.kind == "accountability" for f in flags)


def test_bad_mode():
    with pytest.raises(ValueError):
        detect_all(_state(False), "nope")
