"""Data model for Snapline photo support sessions.

A support rep (CSR) opens a SupportSession, which issues a single-use
JoinToken sent to the customer as a link. The customer accepts the privacy
terms (ConsentRecord) and then uploads Photos to the session.
"""

import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

# Random bytes in a raw join token
JOIN_TOKEN_BYTES = 32

# Length of a SHA-256 digest in hex characters.
SHA256_HEX_LENGTH = 64

# Digits in the verbal verification code the CSR reads to the customer.
VERIFICATION_CODE_DIGITS = 6

# Trailing phone digits kept so the CSR can tell sessions apart.
PHONE_HINT_DIGITS = 4

# Maximum length of the CSR's external ticket reference.
TICKET_REFERENCE_MAX_LENGTH = 64

# Maximum length of a privacy policy version label.
POLICY_VERSION_MAX_LENGTH = 32


def generate_verification_code() -> str:
    """Generates a zero-padded random numeric verification code.

    The code is not a secret. It is shown on both the CSR dashboard and the
    customer's landing page so the customer can confirm, over the phone,
    that the link really came from the repm they are talking to.

    Returns:
        A string of VERIFICATION_CODE_DIGITS random digits.
    """
    upper_bound = 10**VERIFICATION_CODE_DIGITS
    return f"{secrets.randbelow(upper_bound):0{VERIFICATION_CODE_DIGITS}d}"


def default_session_expiry():
    """Compute the default expiry time for a new support session.

    Returns:
        The current time plus settings.SNAPLINE_SESSION_TTL.
    """
    return timezone.now() + settings.SNAPLINE_SESSION_TTL


def photo_upload_path(instance: "Photo", filename: str) -> str:
    """Build the storage path for an uploaded photo.

    The client-supplied filename is discarded: it is untrusted input and may
    contain personal information. Photos are stored by UUID and always
    recorded to JPEG before saving.

    Params:
        instance: The photo being saved
        filename: The original client filename (ignored).

    Returns:
        A storage path of the form photos/<session id>/<photo id>.jpg.
    """
    del filename
    return f"photos/{instance.session_id}/{instance.id}.jpg"


class SupportSession(models.Model):
    """One troubleshotting session between a CSR and a customer.

    The customer's full phone number is never stored.. It is used only to
    send the SMS when a session is created; afterward only the last few
    digits are kept for the CSR's reference.
    """

    class Status(models.TextChoices):
        """Lifecycle states of a support session."""

        # Link sent; the customer has not opened it yet.
        PENDING = "pending", "Waiting for customer"

        # The Customer has joined and accepted the terms.
        ACTIVE = "active", "Customer connected"

        # The CSR ended the session; no further uploads are accepted.
        CLOSED = "closed", "Closed"

    # Random UUID so session IDs in URLs cannot be guessed or enumerated.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The CSR who opened the session. PROTECT: deactive users instead of
    # deleting them, so session history keeps its owner.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_sessions",
    )

    # Optional ticket number from the organization's own ticketing system.
    ticket_reference = models.CharField(
        max_length=TICKET_REFERENCE_MAX_LENGTH, blank=True
    )

    # Last digits of the customer's phone number, for display only.
    phone_hint = models.CharField(max_length=PHONE_HINT_DIGITS, blank=True)

    # Code read aloud to the customer to prove the link is legitimate.
    verification_code = models.CharField(
        max_length=VERIFICATION_CODE_DIGITS,
        default=generate_verification_code,
        editable=False,
    )

    # Current lifecycle state.
    status = models.CharField(
        max_length=max(len(value) for value in Status.values),
        choices=Status.choices,
        default=Status.PENDING,
    )

    # When the CSR opened the session.
    created_at = models.DateTimeField(auto_now_add=True)

    # Hard deadline after whcih the session accepts nothing.
    expires_at = models.DateTimeField(default=default_session_expiry)

    # When the session was closed, or null if still open.
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options for SupportSession."""

        ordering = ["-created_at"]
        indexes = [models.Index(fields=["expires_at"])]

    def __str__(self) -> str:
        """Human-readable label

        Returns:
            The ticket reference or a short ID, plus the status.
        """
        label = self.ticket_reference or str(self.id)[:8]
        return f"{label} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        """Whether the session can still accept customer activity.

        Returns:
            True if the session is not closed and has not expired.
        """
        return self.status != self.Status.CLOSED and timezone.now() < self.expires_at

    @property
    def verification_code_spoken(self) -> str:
        """The verification code with spaces between digits.

        Used as the code's accessible label so screen readers announce
        each digit separately instead of reading one large number.

        Returns:
            The code's digits separated by spaces, e.g. "1 2 3 4 5 6".
        """
        return " ".join(self.verification_code)

    def close(self) -> None:
        """Closes the session and revokes any outstanding join links."""
        now = timezone.now()
        with transaction.atomic():
            self.status = self.Status.CLOSED
            self.closed_at = now
            self.save(update_fields=["status", "closed_at"])
            self.join_tokens.filter(
                used_at__isnull=True, revoked_at__isnull=True
            ).update(revoked_at=now)


class JoinToken(models.Model):
    """A single-use secret that lets a customer join a session.

    Only the SHA-256 hash of the token is stored, so a database leak
    does not expose working links.
    """

    # The session this token grants access to.
    session = models.ForeignKey(
        SupportSession, on_delete=models.CASCADE, related_name="join_tokens"
    )

    # SHA-256 hex digest of the raw token sent to the customer.
    token_hash = models.CharField(
        max_length=SHA256_HEX_LENGTH, unique=True, editable=False
    )

    # When the token was issued.
    created_at = models.DateTimeField(auto_now_add=True)

    # When th elink stops working if unused.
    expires_at = models.DateTimeField()

    # When the customer used the link, or null if unused.
    used_at = models.DateTimeField(null=True, blank=True)

    # When the token was invalidated (resend or session close), or null.
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        """Human-readable label.

        Returns:
            The session label and token issue time; never the token.
        """
        return f"Token for {self.session} issued {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def is_usable(self) -> bool:
        """Whether the token can still be used to join its session.

        Returns:
            True if the token is unused, unrevoked, and unexpired.
        """
        return (
            self.used_at is None
            and self.revoked_at is None
            and timezone.now() < self.expires_at
        )

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Hash a raw token for storage or lookup.

        Params:
            raw_token: The token string from the customer's link.

        Returns:
            Its SHA-256 hex digest.
        """
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @classmethod
    def issue(cls, session: SupportSession) -> tuple["JoinToken", str]:
        """Creates a new join token, revoking any earlier unused ones.

        The raw token is returned exactly once, to be placed in the SMS link.
        It is not stored and cannot be recovered later.

        Params:
            session: The session the customer will join.

        Returns:
            A tuple of the saved JoinToken and the raw token string.
        """
        raw_token = secrets.token_urlsafe(JOIN_TOKEN_BYTES)
        now = timezone.now()
        with transaction.atomic():
            cls.objects.filter(
                session=session, used_at__isnull=True, revoked_at__isnull=True
            ).update(revoked_at=now)
            token = cls.objects.create(
                session=session,
                token_hash=cls.hash_token(raw_token),
                expires_at=now + settings.SNAPLINE_JOIN_TOKEN_TTL,
            )
        return token, raw_token

    def consume(self) -> bool:
        """Mark the token as used, if it is still valid.

        Uses a single conditional UPDATE so two simultaneous requests with
        the same link cannot both succeed.

        Returns:
            True if this call consumed the token; False if it was
            already used, revoked, or expired.
        """
        now = timezone.now()
        consumed = (
            type(self)
            .objects.filter(
                pk=self.pk,
                used_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=now,
            )
            .update(used_at=now)
        )
        if consumed:
            self.used_at = now
        return consumed == 1


class ConsentRecord(models.Model):
    """Proof that the customer accepted the privacy terms.

    Records which version of the policy was accepted, when, and through
    which join link, so the organization can show what the customer agreed
    to. A session can have several consents if the rep issued a new link.
    """

    # The session the consent applies to.
    session = models.OneToOneField(
        SupportSession, on_delete=models.CASCADE, related_name="consent"
    )

    # The join link the customer accepted through, each link is used once.
    join_token = models.OneToOneField(
        JoinToken, on_delete=models.CASCADE, related_name="consent"
    )

    # Version label of the privacy policy shown to the customer.
    policy_version = models.CharField(max_length=POLICY_VERSION_MAX_LENGTH)

    # When the customer accepted.
    accepted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """Human-readable label.

        Returns:
            The session, policy version, and acceptance time.
        """
        return f"Consent for {self.session} (policy {self.policy_version})"


class Photo(models.Model):
    """A photo the customer sent to a session.

    Deleting a Photo removes its file from storage after the database
    transaction commits, so a customer's "delete" is a real delete.
    """

    # Random UUID; also used as the stored file name.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The session the photo belings to.
    session = models.ForeignKey(
        SupportSession, on_delete=models.CASCADE, related_name="photos"
    )

    # The re-encoded, metadata-free image file.
    image = models.ImageField(
        upload_to=photo_upload_path, width_field="width", height_field="height"
    )

    # Image width in pixels, filled in automatically.
    width = models.PositiveIntegerField(editable=False)

    # Image height in pixels, filled in automatically.
    height = models.PositiveIntegerField(editable=False)

    # When the customer uploaded the photo.
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model options for Photo."""

        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        """Human-readable label

        Returns:
            The session and upload time.
        """
        return f"Photo in {self.session} at {self.uploaded_at:%H:%M:%S}"

    def delete(self, *args, **kwargs):
        """Delete the photo row and its stored file.

        The file is only removed after the transaction commits, so a rolled
        back delete never leaves a row pointing at a missing file.

        Returns:
            The result of Model.delete().
        """
        storage, name = self.image.storage, self.image.name
        result = super().delete(*args, **kwargs)
        if name:
            transaction.on_commit(lambda: storage.delete(name))
        return result
