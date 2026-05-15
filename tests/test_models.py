from models import Contractor


def test_quality_score_zero():
    c = Contractor(name="Acme")
    assert c.quality_score == 0


def test_quality_score_phone_only():
    c = Contractor(name="Acme", phone="(313) 555-0100")
    assert c.quality_score == 1


def test_quality_score_phone_and_email():
    c = Contractor(name="Acme", phone="(313) 555-0100", email="a@b.com")
    assert c.quality_score == 2


def test_quality_score_full():
    c = Contractor(
        name="Acme",
        phone="(313) 555-0100",
        email="a@b.com",
        website="https://acme.com",
    )
    assert c.quality_score == 3
