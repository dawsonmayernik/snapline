"""Forms used by suport reps to manage photo sessions."""

from django import forms

from .models import (
    PHONE_HINT_DIGITS,
    PHOTO_REQUEST_MAX_LENGTH,
    TICKET_REFERENCE_MAX_LENGTH,
)

# Fewest digits accepted for a phone number (a US number without country code).
PHONE_MIN_DIGITS = 10

# Most digits allowed in an E.164 phone number.
PHONE_MAX_DIGITS = 15


class NewSessionForm(forms.Form):
    """Form a CSR fills in to open a new support session.

    The phone number is used only to derive a short hint for the CSR's
    refernce. It is never saved in full.
    """

    # Optional ticket number from the organization's ticketing system.
    ticket_reference = forms.CharField(
        max_length=TICKET_REFERENCE_MAX_LENGTH,
        required=False,
        label="Ticket reference",
    )

    # Customer's phone number; only its last digits are kept.
    phone = forms.CharField(
        required=False,
        label="Customer phone",
        help_text=f"Only the last {PHONE_HINT_DIGITS} digits are stored.",
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}),
    )

    def clean_phone(self) -> str:
        """Normalize the phone number to digits and validate its length.

        Accepts common formatting such as "(555) 123-4567" or "+1 555 123 4567".

        Returns:
            The phone number as a string of digits, or "" if left blank.

        Throws:
            forms.ValidationError: If the number has too few or too many digits.
        """
        digits = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit())
        if digits and not PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS:
            raise forms.ValidationError(
                f"Enter a phone number with {PHONE_MIN_DIGITS} to "
                f"{PHONE_MAX_DIGITS} digits."
            )
        return digits

    @property
    def phone_hint(self) -> str:
        """The trailing digits of the phone number to store.

        Pre:
            The form has been validated with is_valid().

        Returns:
            The last PHONE_HINT_DIGITS digits, or "" if no phone was given.
        """
        return self.cleaned_data["phone"][-PHONE_HINT_DIGITS:]


class PhotoUploadForm(forms.Form):
    """Form carrying one photo from the customer's phone."""

    photo = forms.FileField()


class PhotoRequestForm(forms.Form):
    """Form a rep uses to ask the customer for a specific photo."""

    # The request text shown to the customer.
    text = forms.CharField(
        max_length=PHOTO_REQUEST_MAX_LENGTH,
        required=False,
        label="Request a photo",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Can you get a shot of the back of the switch?",
                "autocomplete": "off",
            }
        ),
    )
