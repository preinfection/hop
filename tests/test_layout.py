"""The island's layout (clean_layout): whatever is stored or sent, the island
gets a complete, valid layout. Exhaustive over page orders and hidden sets."""
import itertools

import pytest

import host

PAGES = host.PAGE_IDS


# ---- every order of the four pages (24)
@pytest.mark.parametrize("order", list(itertools.permutations(PAGES)))
def test_page_order_kept(order):
    L = host.clean_layout({"pages": list(order)})
    assert L["pages"] == list(order)


# ---- every set of hidden pages (16): at least one page always stays
@pytest.mark.parametrize("hidden", [list(c) for n in range(5) for c in itertools.combinations(PAGES, n)])
def test_hidden_pages(hidden):
    L = host.clean_layout({"hidden": hidden})
    assert len(L["hidden"]) < len(PAGES)
    assert set(L["hidden"]) <= set(hidden)
    if len(hidden) < len(PAGES):
        assert L["hidden"] == list(dict.fromkeys(hidden))
    else:
        assert "music" not in L["hidden"]          # all four hidden: the player comes back


# ---- order x hidden together (24 x 16 = 384)
@pytest.mark.parametrize("order", list(itertools.permutations(PAGES)))
@pytest.mark.parametrize("hidden", [list(c) for n in range(5) for c in itertools.combinations(PAGES, n)])
def test_order_and_hidden(order, hidden):
    L = host.clean_layout({"pages": list(order), "hidden": hidden})
    assert L["pages"] == list(order)
    visible = [p for p in L["pages"] if p not in L["hidden"]]
    assert len(visible) >= 1


# ---- partial / junk page lists are completed, never lost
@pytest.mark.parametrize("pages", [[], ["pc"], ["today", "music"], ["nope", "pc", "pc", "music"],
                                   ["music", "music", "music"], [1, 2, None], ["clips", "PC", "Music"]])
def test_page_list_completed(pages):
    L = host.clean_layout({"pages": pages})
    assert sorted(L["pages"]) == sorted(PAGES)
    assert len(L["pages"]) == 4


# ---- slot choices
@pytest.mark.parametrize("v", ["rec", "art", "none"])
def test_left_slot(v):
    assert host.clean_layout({"musicLeft": v})["musicLeft"] == v


@pytest.mark.parametrize("v", ["prayer", "bars", "clock", "none"])
def test_right_slot(v):
    assert host.clean_layout({"musicRight": v})["musicRight"] == v


@pytest.mark.parametrize("v", ["system", "light", "dark"])
def test_theme(v):
    assert host.clean_layout({"appTheme": v})["appTheme"] == v


@pytest.mark.parametrize("key,bad", [("musicLeft", "cover"), ("musicLeft", None), ("musicLeft", 3),
                                     ("musicRight", "weather"), ("musicRight", ""), ("appTheme", "blue"),
                                     ("appTheme", True)])
def test_bad_choice_falls_back(key, bad):
    assert host.clean_layout({key: bad})[key] == host.LAYOUT_DEFAULTS[key]


# ---- every on/off switch, both ways, and junk values
@pytest.mark.parametrize("key", host.BOOL_KEYS)
@pytest.mark.parametrize("value", [True, False])
def test_switch(key, value):
    assert host.clean_layout({key: value})[key] is value


@pytest.mark.parametrize("key", host.BOOL_KEYS)
@pytest.mark.parametrize("junk", ["false", 0, 1, None, [], "yes"])
def test_switch_junk_ignored(key, junk):
    assert host.clean_layout({key: junk})[key] is host.LAYOUT_DEFAULTS[key]


# ---- size: clamped to 70-150 %
@pytest.mark.parametrize("given,expected", [(1.0, 1.0), (0.7, 0.7), (1.5, 1.5), (0.1, 0.7), (9, 1.5), (-3, 0.7),
                                            ("1.2", 1.2), ("big", 1.0), (None, 1.0), (1.234, 1.23)])
def test_scale(given, expected):
    assert host.clean_layout({"scale": given})["scale"] == expected


# ---- nothing stored at all
@pytest.mark.parametrize("raw", [None, "junk", 5, [], {}])
def test_empty_or_junk(raw):
    L = host.clean_layout(raw)
    assert set(L) == set(host.LAYOUT_DEFAULTS)


def test_old_pages34_off_hides_pages_3_and_4():
    assert host.clean_layout(None, legacy_pages34=False)["hidden"] == ["clips", "pc"]


def test_unknown_keys_dropped():
    assert "evil" not in host.clean_layout({"evil": "<script>"})
