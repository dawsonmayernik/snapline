"""Views for support reps (dashboard, sessions) and the customer join page."""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .forms import NewSessionForm
from .models import JoinToken, SupportSession

# Prefix for the server-side session key holding a link not yet shown.
_PENDING_LINK_KEY_PREFIX = "snapline_pending_link:"


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


@require_GET
@never_cache
def customer_join(request, token):
    """Landing page the customer reaches from the SMS link.

    Params:
        request: The current request from the customer.
        token: The raw join token from the URL.

    Returns:
        The landing page, or a 410 page if the link is no longer valid.
    """
    join_token = (
        JoinToken.objects.select_related("session")
        .filter(token_hash=JoinToken.hash_token(token))
        .first()
    )
    if join_token is None or not join_token.is_usable or not join_token.session.is_open:
        return render(request, "customer/link_invalid.html", status=410)
    return render(
        request, "customer/join.html", {"support_session": join_token.session}
    )
