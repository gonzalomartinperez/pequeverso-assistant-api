"""Contact-data removal."""

from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.redaction import EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER, redact_contact_data

EMAILS = st.builds(
    lambda local, host, tld: f"{local}@{host}.{tld}",
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789._+-", min_size=1, max_size=20),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=15),
    st.sampled_from(["com", "org", "test", "es"]),
)
PHONES = st.builds(
    lambda digits, separator, plus: plus + separator.join(digits),
    st.text(alphabet="0123456789", min_size=8, max_size=15),
    st.sampled_from(["", " ", "-", "."]),
    st.sampled_from(["", "+"]),
)


@given(email=EMAILS, phone=PHONES)
@example(email="familia@example.test", phone="+54 11 2345 6789")
def test_redaction_is_idempotent_and_removes_contacts(email, phone):
    """Row 7: generated contacts disappear and redacting again changes no text."""
    result = redact_contact_data(f"Correo: {email}; teléfono: {phone}.")
    assert email not in result.text
    assert phone not in result.text
    assert EMAIL_PLACEHOLDER in result.text
    assert PHONE_PLACEHOLDER in result.text
    assert result.redactions == 2
    again = redact_contact_data(result.text)
    assert again.text == result.text
    assert again.redactions == 0
