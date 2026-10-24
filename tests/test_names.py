import pytest

from fuel_route.infrastructure.names import census_name_variants, normalize_state, place_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Mc Calla", "McCalla"),
        ("De Forest", "DeForest"),
        ("Saint Johns", "St. Johns"),
        ("Fort Worth", "Ft. Worth"),
        ("Mount Vernon", "Mt Vernon"),
        ("  Effingham   ", "effingham"),
    ],
)
def test_place_key_unifies_spellings(a, b):
    assert place_key(a) == place_key(b)


def test_census_variants_strip_legal_suffixes():
    assert "Oklahoma City" in census_name_variants("Oklahoma City city")
    assert "Nashville" in census_name_variants("Nashville-Davidson metropolitan government (balance)")
    assert "Big Cabin" in census_name_variants("Big Cabin town")
    # Only one suffix is stripped: "Oklahoma City city" must not become "Oklahoma".
    assert "Oklahoma" not in census_name_variants("Oklahoma City city")


def test_normalize_state():
    assert normalize_state("tx") == "TX"
    assert normalize_state("New Mexico") == "NM"
    assert normalize_state("ON") is None
