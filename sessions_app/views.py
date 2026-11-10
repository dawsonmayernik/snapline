"""Views for support reps (dashboard, sessions) and the customer join page."""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from .forms import NewSessionForm
from .models import ConsentRecord, JoinToken, SupportSession

# Prefix for the server-side session key holding a link not yet shown.
_PENDING_LINK_KEY_PREFIX = "snapline_pending_link:"

## Server-side session key holding the ID of the join token a customer redeemed.
_CUSTOMER_TOKEN_KEY = "snapline_customer_join_token"


def _pending_link_key(support_session: SupportSession) -> str:
    """Builds the server-side session key for a session's fresh link.

    Params:
        support_session: The support session the link belongs to.

    Returns:
        The key under which the raw join token is briefly stored.
    """
    return f"{_PENDING_LINK_KEY_PREFIX}{support_session.pk}"


def _build_join_url(raw_token: str) -> str:
    """Builds the absolute URL the customer opens.

    Uses the configured public base URL rather than the request's Host
    header, so a forged Host header can never alter the link sent out.

    Params:
        raw_token: The raw join token.

    Returns:
        The full join URL.
    """
    path = reverse("sessions_app:customer_join", args=[raw_token])
    return settings.SNAPLINE_PUBLIC_BASE_URL.rstrip("/") + path


def _issue_link(request, support_session: SupportSession) -> None:
    """Issues a new join token and hold it for one-time display.

    The raw token is kept in the CSR's server-side Django session only until
    the session detail page displays it once.

    Params:
        request: The current request from the CSR.
        support_session: The support session to issue a link for.
    """
    _, raw_token = JoinToken.issue(support_session)
    request.session[_pending_link_key(support_session)] = raw_token


def _get_own_session(request, pk) -> SupportSession:
    """Fetches a support session owned by the logged-in CSR.

    Returns 404 (not 403) for other reps' sessions so their existence is
    not revealed.

    Params:
        request: The current request from the CSR.
        pk: The support session's UUID.

    Returns:
        The matching SupportSession.

    Throws:
        Http404: If no such session belongs to this CSR.
    """
    return get_object_or_404(SupportSession, pk=pk, created_by=request.user)


def _open_sessions(user):
    """Lists a CSR's sessions that are neither closed nor expired.

    Params:
        user: The logged-in CSR.

    Returns:
        A QuerySet of open SupportSession objects, newest first.
    """
    return SupportSession.objects.filter(
        created_by=user, expires_at__gt=timezone.now()
    ).exclude(status=SupportSession.Status.CLOSED)


@login_required
@require_GET
def dashboard(request):
    """Show the CSR's open sessions and the new-session form.

    Params:
        request: The current request.

    Returns:
        The rendered dashboard.
    """
    return render(
        request,
        "sessions_app/dashboard.html",
        {"open_sessions": _open_sessions(request.user), "form": NewSessionForm()},
    )


@login_required
@require_POST
def create_session(request):
    """Create a support session and issue its first join link.

    Params:
        request: The current request containing NewSessionForm data.

    Returns:
        A redirect to the new session, or the dashboard with errors.
    """
    form = NewSessionForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "sessions_app/dashboard.html",
            {"open_sessions": _open_sessions(request.user), "form": form},
            status=400,
        )
    support_session = SupportSession.objects.create(
        created_by=request.user,
        ticket_reference=form.cleaned_data["ticket_reference"],
        phone_hint=form.phone_hint,
    )
    _issue_link(request, support_session)
    return redirect("sessions_app:session_detail", pk=support_session.pk)


@login_required
@require_GET
@never_cache
def session_detail(request, pk):
    """Show one session's code, status, and (once) its join link.

    A freshly issued link is popped from the server-side session, so it is
    displayed exactly once. Reloading the page will not show it again.

    Params:
        request: The current request.
        pk: The support session's UUID.

    Returns:
        The rendered session detail page.
    """
    support_session = _get_own_session(request, pk)
    raw_token = request.session.pop(_pending_link_key(support_session), None)
    join_url = _build_join_url(raw_token) if raw_token else None
    return render(
        request,
        "sessions_app/session_detail.html",
        {"support_session": support_session, "join_url": join_url},
    )


@login_required
@require_POST
def reissue_link(request, pk):
    """Issue a replacement join link, revoking the previous one.

    Params:
        request: The current request.
        pk: The support session's UUID.

    Returns:
        A redirect to the session detail page showing the new link.
    """
    support_session = _get_own_session(request, pk)
    if support_session.is_open:
        _issue_link(request, support_session)
    return redirect("sessions_app:session_detail", pk=support_session.pk)


@login_required
@require_POST
def close_session(request, pk):
    """Close a session and revoke any outstanding join links.

    Params:
        request: The current request.
        pk: The support session's UUID.

    Returns:
        A redirect to the dashboard.
    """
    support_session = _get_own_session(request, pk)
    if support_session.status != SupportSession.Status.CLOSED:
        support_session.close()
    return redirect("sessions_app:dashboard")


def _find_join_token(raw_token: str):
    """Look up a join token by the raw value from the customer's link.

    Params:
        raw_token: The raw token from the URL.

    Returns:
        The matching JoinToken with its session loaded, or None.
    """
    return (
        JoinToken.objects.select_related("session")
        .filter(token_hash=JoinToken.hash_token(raw_token))
        .first()
    )


def _customer_session(request):
    """Find the support session this customer's browser has joined.

    Params:
        request: The current request from the customer.
    Returns:
        The joined SupportSession, or None if this browser has no access.
    """
    token_id = request.session.get(_CUSTOMER_TOKEN_KEY)
    if token_id is None:
        return None
    join_token = (
        JoinToken.objects.select_related("session")
        .filter(pk=token_id, used_at__isnull=False, revoked_at__isnull=True)
        .first()
    )
    return join_token.session if join_token else None


def _grant_customer_access(request, join_token: JoinToken) -> None:
    """Give this browser access to the session it just joined.

    Params:
        request: The current request from the customer.
        join_token: The join token the customer just redeemed.
    """
    request.session.cycle_key()
    request.session[_CUSTOMER_TOKEN_KEY] = join_token.pk
    request.session.set_expiry(join_token.session.expires_at)


@require_http_methods(["GET", "POST"])
@never_cache
def customer_join(request, token):
    """Landing page the customer reaches from the SMS link.

    Params:
        request: The current request from the customer.
        token: The raw join token from the URL.

    Returns:
        The landing page, a redirect to the session, or a 410 page if
        the link is no longer valid.
    """
    join_token = _find_join_token(token)
    if join_token is not None and _customer_session(request) == join_token.session:
        return redirect("sessions_app:customer_capture")
    if join_token is None or not join_token.is_usable or not join_token.session.is_open:
        return render(request, "customer/link_invalid.html", status=410)
    if request.method == "GET":
        return render(
            request, "customer/join.html", {"support_session": join_token.session}
        )

    with transaction.atomic():
        if not join_token.consume():
            return render(request, "customer/link_invalid.html", status=410)
        ConsentRecord.objects.create(
            session=join_token.session,
            join_token=join_token,
            policy_version=settings.SNAPLINE_PRIVACY_POLICY_VERSION,
        )
        SupportSession.objects.filter(
            pk=join_token.session.pk, status=SupportSession.Status.PENDING
        ).update(status=SupportSession.Status.ACTIVE)
    _grant_customer_access(request, join_token)
    return redirect("sessions_app:customer_capture")


@require_GET
@never_cache
def customer_capture(request):
    """The customer's page for their joined support session.

    Params:
        request: The current request from the customer.

    Returns:
        The session page; the ended page if the rep closed the session
        or it expired; or a 403 page if this browser never joined a session.
    """
    support_session = _customer_session(request)
    if support_session is None:
        return render(request, "customer/link_invalid.html", status=403)
    if not support_session.is_open:
        return render(request, "customer/ended.html", status=410)
    return render(
        request, "customer/capture.html", {"support_session": support_session}
    )
