"""Tests for support session views and the customer join page."""

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ConsentRecord, JoinToken, SupportSession

## Placeholder password used for test accounts only.
TEST_PASSWORD = "test-password"


class CsrSessionViewTests(TestCase):
    """Tests for the support rep's dashboard and session pages."""

    def setUp(self):
        """Create two reps and log in as the first."""
        user_model = get_user_model()
        self.csr = user_model.objects.create_user("csr", password=TEST_PASSWORD)
        self.other_csr = user_model.objects.create_user("other", password=TEST_PASSWORD)
        self.client.login(username="csr", password=TEST_PASSWORD)

    def _create_session(self, **data):
        """Submit the new-session form.

        Params:
            data: Form fields to post.

        Returns:
            The HTTP response.
        """
        return self.client.post(reverse("sessions_app:create_session"), data)

    def test_dashboard_requires_login(self):
        """Anonymous users are redirected to the login page."""
        self.client.logout()
        response = self.client.get(reverse("sessions_app:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_create_session_stores_only_phone_hint(self):
        """Only the last four phone digits are saved."""
        self._create_session(ticket_reference="INC-1", phone="(555) 123-4567")
        support_session = SupportSession.objects.get()
        self.assertEqual(support_session.phone_hint, "4567")
        self.assertEqual(support_session.created_by, self.csr)

    def test_invalid_phone_is_rejected(self):
        """Phone numbers with too few digits are rejected."""
        response = self._create_session(phone="12345")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SupportSession.objects.exists())

    def test_join_link_is_shown_exactly_once(self):
        """The raw link appears on the first view and never again."""
        response = self._create_session()
        first = self.client.get(response.url)
        second = self.client.get(response.url)
        self.assertIsNotNone(first.context["join_url"])
        self.assertIsNone(second.context["join_url"])

    def test_other_csr_cannot_view_session(self):
        """Another rep's session returns 404, hiding its existence."""
        foreign = SupportSession.objects.create(created_by=self.other_csr)
        response = self.client.get(
            reverse("sessions_app:session_detail", args=[foreign.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_other_csr_cannot_close_session(self):
        """Another rep cannot close a session they do not own."""
        foreign = SupportSession.objects.create(created_by=self.other_csr)
        response = self.client.post(
            reverse("sessions_app:close_session", args=[foreign.pk])
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertNotEqual(foreign.status, SupportSession.Status.CLOSED)

    def test_close_requires_post(self):
        """A GET request cannot close a session."""
        support_session = SupportSession.objects.create(created_by=self.csr)
        response = self.client.get(
            reverse("sessions_app:close_session", args=[support_session.pk])
        )
        self.assertEqual(response.status_code, 405)


class CustomerJoinViewTests(TestCase):
    """Tests for the page the customer reaches from the SMS link."""

    def setUp(self):
        """Create a rep, an open session, and a fresh join token."""
        csr = get_user_model().objects.create_user("csr", password=TEST_PASSWORD)
        self.support_session = SupportSession.objects.create(created_by=csr)
        self.token, self.raw_token = JoinToken.issue(self.support_session)

    def _join(self, raw_token):
        """Request the join page for a raw token.

        Params:
            raw_token: The raw token to put in the URL.
        Returns:
            The HTTP response.
        """
        return self.client.get(reverse("sessions_app:customer_join", args=[raw_token]))

    def test_valid_link_shows_verification_code(self):
        """A valid link shows the session's verification code."""
        response = self._join(self.raw_token)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.support_session.verification_code_spoken)

    def test_viewing_link_does_not_consume_token(self):
        """Link-preview bots fetching the page must not burn the link."""
        self._join(self.raw_token)
        self._join(self.raw_token)
        self.token.refresh_from_db()
        self.assertIsNone(self.token.used_at)

    def test_unknown_token_is_rejected(self):
        """A made-up token gets the expired-link page."""
        self.assertEqual(self._join("not-a-real-token").status_code, 410)

    def test_replaced_link_stops_working(self):
        """Issuing a new link revokes the old one."""
        JoinToken.issue(self.support_session)
        self.assertEqual(self._join(self.raw_token).status_code, 410)

    def test_expired_link_is_rejected(self):
        """A link past its expiry time no longer works."""
        self.token.expires_at = timezone.now() - timedelta(seconds=1)
        self.token.save(update_fields=["expires_at"])
        self.assertEqual(self._join(self.raw_token).status_code, 410)

    def test_closed_session_link_is_rejected(self):
        """Closing the session kills its link."""
        self.support_session.close()
        self.assertEqual(self._join(self.raw_token).status_code, 410)

    def test_join_page_is_not_cached(self):
        """The join page tells browsers and proxies not to cache it."""
        response = self._join(self.raw_token)
        self.assertIn("no-store", response["Cache-Control"])


class CustomerConsentTests(TestCase):
    """Tests for the customer accepting terms and joining a session."""

    def setUp(self):
        """Create a rep, an open session, and a fresh join token."""
        csr = get_user_model().objects.create_user("csr", password=TEST_PASSWORD)
        self.support_session = SupportSession.objects.create(created_by=csr)
        self.token, self.raw_token = JoinToken.issue(self.support_session)
        self.join_url = reverse("sessions_app:customer_join", args=[self.raw_token])
        self.capture_url = reverse("sessions_app:customer_capture")

    def _consent(self, client=None):
        """Submit the consent form, as a given browser.

        Params:
            client: The test client to use; defaults to self.client.

        Returns:
            The HTTP response.
        """
        return (client or self.client).post(self.join_url)

    def test_consent_joins_session(self):
        """Consenting uses the link, records consent, and connects."""
        response = self._consent()
        self.assertRedirects(response, self.capture_url)
        self.token.refresh_from_db()
        self.support_session.refresh_from_db()
        self.assertIsNotNone(self.token.used_at)
        self.assertEqual(self.support_session.status, SupportSession.Status.ACTIVE)
        consent = ConsentRecord.objects.get()
        self.assertEqual(consent.join_token, self.token)
        self.assertEqual(
            consent.policy_version, settings.SNAPLINE_PRIVACY_POLICY_VERSION
        )

    def test_link_works_only_once(self):
        """A second browser cannot reuse a link that was already used."""
        self._consent()
        response = self._consent(client=Client())
        self.assertEqual(response.status_code, 410)
        self.assertEqual(ConsentRecord.objects.count(), 1)

    def test_retapping_link_returns_customer_to_session(self):
        """The customer who joined can reopen the link without error."""
        self._consent()
        response = self.client.get(self.join_url)
        self.assertRedirects(response, self.capture_url)

    def test_other_browser_cannot_open_used_link(self):
        """A used link shows "expired" to anyone but the customer."""
        self._consent()
        response = Client().get(self.join_url)
        self.assertEqual(response.status_code, 410)

    def test_capture_requires_joining(self):
        """The session page is blocked for browsers that never joined."""
        response = self.client.get(self.capture_url)
        self.assertEqual(response.status_code, 403)

    def test_capture_shows_session_after_joining(self):
        """A customer who joined can see their session page."""
        self._consent()
        response = self.client.get(self.capture_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "customer/capture.html")

    def test_closed_session_ends_customer_access(self):
        """When the rep closes the session, the customer is locked out."""
        self._consent()
        self.support_session.close()
        response = self.client.get(self.capture_url)
        self.assertEqual(response.status_code, 410)
        self.assertTemplateUsed(response, "customer/ended.html")

    def test_revoked_link_cannot_be_consented(self):
        """A link replaced by a newer one cannot be used to join."""
        JoinToken.issue(self.support_session)
        response = self._consent()
        self.assertEqual(response.status_code, 410)
        self.assertFalse(ConsentRecord.objects.exists())

    def test_consent_rotates_session_key(self):
        """Joining issues a fresh session ID (prevents session fixation)."""
        self.client.get(self.join_url)
        self.client.session.save()
        key_before = self.client.session.session_key
        self._consent()
        self.assertNotEqual(self.client.session.session_key, key_before)

    def test_customer_access_expires_with_session(self):
        """The customer's access ends when the support session expires."""
        self._consent()
        self.assertEqual(
            self.client.session.get_expiry_date(), self.support_session.expires_at
        )

    def test_consent_requires_csrf_token(self):
        """A forged consent POST from another site is rejected."""
        response = self._consent(client=Client(enforce_csrf_checks=True))
        self.assertEqual(response.status_code, 403)
        self.token.refresh_from_db()
        self.assertIsNone(self.token.used_at)

    def test_head_request_does_not_consume_link(self):
        """Link scanners sending HEAD requests must not burn the link."""
        response = self.client.head(self.join_url)
        self.assertEqual(response.status_code, 405)
        self.token.refresh_from_db()
        self.assertIsNone(self.token.used_at)

    def test_simultaneous_consents_only_one_wins(self):
        """If two taps race, only the first one joins the session."""
        stale_token = JoinToken.objects.get(pk=self.token.pk)
        self.token.consume()
        with mock.patch(
            "sessions_app.views._find_join_token", return_value=stale_token
        ):
            response = self._consent()
        self.assertEqual(response.status_code, 410)
        self.assertFalse(ConsentRecord.objects.exists())
