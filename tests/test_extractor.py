from extractor import _clean_email, _ok_email, _parse_phone, extract_contacts


class TestOkEmail:
    def test_valid_email(self):
        assert _ok_email("info@hvacpro.com") is True

    def test_empty_string(self):
        assert _ok_email("") is False

    def test_no_at_sign(self):
        assert _ok_email("notanemail") is False

    def test_bad_domain_no_dot(self):
        assert _ok_email("user@nodot") is False

    def test_too_short(self):
        assert _ok_email("a@b.c") is False

    def test_too_long(self):
        assert _ok_email("a" * 70 + "@example.com") is False

    def test_noreply_rejected(self):
        assert _ok_email("noreply@example.com") is False

    def test_bad_email_domain_cloudflare(self):
        assert _ok_email("user@cloudflare.com") is False

    def test_image_extension_in_local(self):
        assert _ok_email("logo.png@example.com") is False

    def test_role_email_passes_ok_check(self):
        # info@ passes _ok_email — role warning is a separate concern
        assert _ok_email("info@contractor.com") is True

    def test_valid_subdomain_email(self):
        assert _ok_email("contact@mail.hvacpro.com") is True


class TestCleanEmail:
    def test_strips_whitespace(self):
        assert _clean_email("  hello@example.com  ") == "hello@example.com"

    def test_strips_trailing_punctuation(self):
        assert _clean_email("hello@example.com.") == "hello@example.com"

    def test_strips_angle_brackets(self):
        assert _clean_email("<hello@example.com>") == "hello@example.com"

    def test_lowercases(self):
        assert _clean_email("HELLO@EXAMPLE.COM") == "hello@example.com"

    def test_url_decodes_percent40(self):
        assert _clean_email("hello%40example.com") == "hello@example.com"

    def test_strips_parens(self):
        assert _clean_email("(hello@example.com)") == "hello@example.com"


class TestParsePhone:
    def test_ten_digit_plain(self):
        assert _parse_phone("3135551234") == "(313) 555-1234"

    def test_with_dashes(self):
        assert _parse_phone("313-555-1234") == "(313) 555-1234"

    def test_with_parens_and_space(self):
        assert _parse_phone("(313) 555-1234") == "(313) 555-1234"

    def test_too_short_returns_empty(self):
        assert _parse_phone("12345") == ""

    def test_eleven_digit_leading_1(self):
        # 11 digits — last 10 used, leading 1 stripped
        assert _parse_phone("13135551234") == "(313) 555-1234"

    def test_with_dots(self):
        assert _parse_phone("313.555.1234") == "(313) 555-1234"


class TestExtractContactsJsonLd:
    def test_email_and_phone_from_jsonld(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "email": "contact@hvacpro.com", "telephone": "313-555-0001"}
        </script>
        </head><body></body></html>
        """
        email, phone = extract_contacts(html)
        assert email == "contact@hvacpro.com"
        assert phone == "(313) 555-0001"

    def test_empty_html_returns_blanks(self):
        email, phone = extract_contacts("")
        assert email == ""
        assert phone == ""

    def test_no_contacts_in_plain_html(self):
        email, phone = extract_contacts("<html><body><p>Hello world</p></body></html>")
        assert email == ""
        assert phone == ""

    def test_regex_fallback_finds_email(self):
        html = "<html><body>Email us at sales@mycontractor.com today</body></html>"
        email, phone = extract_contacts(html)
        assert email == "sales@mycontractor.com"

    def test_regex_fallback_finds_phone(self):
        html = "<html><body>Call (313) 555-9999 now</body></html>"
        _, phone = extract_contacts(html)
        assert phone == "(313) 555-9999"

    def test_bytes_input_decoded(self):
        html = b"<html><body>info@testco.com</body></html>"
        email, _ = extract_contacts(html)
        assert email == "info@testco.com"

    def test_malformed_jsonld_skipped_falls_to_regex(self):
        html = """
        <script type="application/ld+json">{not valid json}</script>
        <html><body>backup@fallback.com</body></html>
        """
        email, _ = extract_contacts(html)
        assert email == "backup@fallback.com"

    def test_jsonld_graph_structure(self):
        html = """
        <script type="application/ld+json">
        {"@graph": [{"@type": "LocalBusiness", "email": "graph@hvac.com"}]}
        </script>
        """
        email, _ = extract_contacts(html)
        assert email == "graph@hvac.com"

    def test_bad_email_in_jsonld_ignored(self):
        html = """
        <script type="application/ld+json">
        {"email": "noreply@example.com", "telephone": "313-555-0002"}
        </script>
        <body>real@contractor.com</body>
        """
        email, _ = extract_contacts(html)
        # noreply is filtered; regex fallback finds real@contractor.com
        assert email == "real@contractor.com"
