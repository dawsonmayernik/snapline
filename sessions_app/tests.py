"""Tests for support session views and the customer join page."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import JoinToken, SupportSession

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
