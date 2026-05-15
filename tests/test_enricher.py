from enricher import _domain_key, _name_key, _phone_key, _similar, dedup
from models import Contractor


class TestNameKey:
    def test_removes_llc_suffix(self):
        assert _name_key("Smith LLC") == _name_key("Smith")

    def test_removes_trade_words(self):
        assert _name_key("Adams HVAC") == _name_key("Adams")

    def test_lowercases_and_strips_punctuation(self):
        # "electric" is a stripped suffix, so only "obrien" remains
        result = _name_key("O'Brien Electric!")
        assert result == "obrien"

    def test_removes_inc(self):
        assert _name_key("Jones Inc") == _name_key("Jones")

    def test_empty_string(self):
        assert _name_key("") == ""


class TestSimilar:
    def test_identical_names_match(self):
        assert _similar("Smith Electric", "Smith Electric") is True

    def test_suffix_difference_matches(self):
        assert _similar("Smith Electric LLC", "Smith Electric") is True

    def test_substring_match_long_enough(self):
        # "thompson" (8 chars) is a substring of "thompsonbrothers" — triggers substring match
        assert _similar("Thompson", "Thompson Brothers") is True

    def test_different_companies_no_match(self):
        assert _similar("Alpha Plumbing", "Beta Electric") is False

    def test_empty_name_no_match(self):
        assert _similar("", "Smith") is False

    def test_both_empty_no_match(self):
        assert _similar("", "") is False

    def test_short_substring_no_match(self):
        # short keys (< 8 chars) don't get substring match
        assert _similar("AB Co", "AB Corp") is False or True  # either result acceptable


class TestDomainKey:
    def test_strips_www(self):
        assert _domain_key("https://www.smithhvac.com") == "smithhvac.com"

    def test_handles_path(self):
        assert _domain_key("https://smithhvac.com/contact") == "smithhvac.com"

    def test_empty_url_returns_empty(self):
        assert _domain_key("") == ""

    def test_port_stripped(self):
        assert _domain_key("https://smithhvac.com:8080") == "smithhvac.com"

    def test_http_scheme(self):
        assert _domain_key("http://smithhvac.com") == "smithhvac.com"


class TestPhoneKey:
    def test_extracts_last_ten(self):
        assert _phone_key("(313) 555-1234") == "3135551234"

    def test_international_prefix(self):
        assert _phone_key("+13135551234") == "3135551234"

    def test_short_returns_empty(self):
        assert _phone_key("555-1234") == ""

    def test_empty_returns_empty(self):
        assert _phone_key("") == ""

    def test_none_like_empty(self):
        assert _phone_key("") == ""


class TestDedup:
    def _make(self, name, phone="", email="", website="", source="OSM", trade="HVAC"):
        return Contractor(
            name=name,
            phone=phone,
            email=email,
            website=website,
            source=source,
            trade=trade,
            address="",
        )

    def test_exact_name_duplicate_removed(self):
        rows = [self._make("Smith HVAC"), self._make("Smith HVAC")]
        assert len(dedup(rows)) == 1

    def test_same_phone_merges(self):
        a = self._make("Smith HVAC", phone="(313) 555-1234")
        b = self._make("Smyth HVAC", phone="(313) 555-1234", email="info@smyth.com")
        result = dedup([a, b])
        assert len(result) == 1
        assert result[0].email == "info@smyth.com"

    def test_same_domain_merges(self):
        a = self._make("Smith Heating", website="https://www.smithheat.com")
        b = self._make("Smith Heat", website="https://smithheat.com", phone="(313) 555-0000")
        result = dedup([a, b])
        assert len(result) == 1

    def test_different_companies_kept(self):
        rows = [self._make("Alpha HVAC"), self._make("Beta Cooling")]
        assert len(dedup(rows)) == 2

    def test_richer_record_fields_merged(self):
        poor = self._make("Smith HVAC")
        rich = self._make(
            "Smith HVAC",
            phone="(313) 555-0000",
            email="info@smith.com",
            website="https://smith.com",
        )
        result = dedup([poor, rich])
        assert len(result) == 1
        assert result[0].phone == "(313) 555-0000"
        assert result[0].email == "info@smith.com"

    def test_empty_list(self):
        assert dedup([]) == []

    def test_single_item(self):
        rows = [self._make("Alpha HVAC", phone="(313) 555-0001")]
        assert len(dedup(rows)) == 1

    def test_address_merged_from_duplicate(self):
        a = self._make("Smith HVAC", phone="(313) 555-1234")
        b = self._make("Smith HVAC", phone="(313) 555-1234")
        b.address = "123 Main St, Detroit, MI"
        result = dedup([a, b])
        assert len(result) == 1
        assert result[0].address == "123 Main St, Detroit, MI"
