from functools import wraps

from django.contrib.auth import get_user_model
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from api import views
from api.models import Detection, Session, SignInBlock
from api.refusals import Conflict


READS = frozenset({"GET", "HEAD", "OPTIONS"})


def not_theirs(request):
    if request.path.startswith("/api/"):
        return JsonResponse({"detail": "no such session of yours"}, status=404)
    return HttpResponseNotFound()


class OwnSessionsOnly:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view, args, kwargs):
        user = request.user
        if not user.is_authenticated or user.is_staff:
            return None
        if request.path.startswith("/api/range/") and request.method not in READS:
            return JsonResponse({"detail": "only an admin changes the range"}, status=403)
        if "session_id" in kwargs and not Session.objects.filter(pk=kwargs["session_id"], owner=user).exists():
            return not_theirs(request)
        if "detection_id" in kwargs and not Detection.objects.filter(
                pk=kwargs["detection_id"], session__owner=user).exists():
            return not_theirs(request)
        return None


def staff_only(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse({"detail": "only an admin manages accounts"}, status=403)
        return view(request, *args, **kwargs)
    return guarded


def _account(user):
    return {
        "id": user.pk,
        "username": user.get_username(),
        "active": user.is_active,
        "staff": user.is_staff,
        "joined": user.date_joined.isoformat(),
    }


@require_GET
@staff_only
def users(request):
    every = get_user_model().objects.order_by("is_active", "-date_joined")
    return JsonResponse({"users": [_account(user) for user in every]})


@require_POST
@staff_only
def approve(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    return JsonResponse(_account(user))


@require_POST
@staff_only
def reject(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    if user.is_active:
        return JsonResponse({"detail": "only an account waiting for approval can be rejected"}, status=409)
    user.delete()
    return JsonResponse({"id": user_id, "rejected": True})


@require_POST
@staff_only
def delete(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    if user.pk == request.user.pk:
        return JsonResponse({"detail": "an admin cannot delete their own account"}, status=409)
    if user.is_staff:
        return JsonResponse({"detail": "an admin account cannot be deleted here"}, status=409)
    closed = []
    for session in Session.objects.filter(owner=user, ended_at=None):
        try:
            views.close_session(request, session.pk)
        except Conflict:
            pass
        closed.append(session.pk)
    user.delete()
    return JsonResponse({"id": user_id, "deleted": True, "closed_sessions": closed})


def _shown_block(block):
    return {
        "id": block.pk, "kind": block.kind, "value": block.value, "username": block.username,
        "reason": block.reason, "failures": block.failures,
        "created_at": block.created_at.isoformat(), "until": block.until.isoformat(),
    }


@require_GET
@staff_only
def sign_in_blocks(request):
    standing = SignInBlock.objects.filter(until__gt=timezone.now())
    return JsonResponse({"blocks": [_shown_block(block) for block in standing]})


@require_POST
@staff_only
def unblock(request, block_id):
    get_object_or_404(SignInBlock, pk=block_id).delete()
    return JsonResponse({"id": block_id, "unblocked": True})
