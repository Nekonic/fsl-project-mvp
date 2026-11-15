from functools import wraps

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST


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
