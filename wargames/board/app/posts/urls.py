from django.urls import path

from . import views

urlpatterns = [
    path("internal/auth-users", views.auth_users, name="auth_users"),
    path("", views.post_list, name="post_list"),
    path("search/", views.search, name="search"),
    path("posts/new/", views.post_new, name="post_new"),
    path("posts/<int:pk>/", views.post_detail, name="post_detail"),
    path("posts/<int:pk>/comments/", views.add_comment, name="add_comment"),
]
