from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import Post


def post_list(request):
    sort = request.GET.get("sort", "-created_at")
    posts = Post.objects.select_related("author").order_by(sort)
    return render(request, "posts/post_list.html", {"posts": posts})


def search(request):
    query = request.GET.get("q", "")
    results = Post.objects.none()
    if query:
        results = Post.objects.filter(
            Q(title__icontains=query) | Q(body__icontains=query)
        ).select_related("author")
    return render(request, "posts/search.html", {"query": query, "results": results})


def post_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related("author"), pk=pk)
    comments = post.comments.select_related("author").all()
    return render(request, "posts/post_detail.html", {"post": post, "comments": comments})


def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            author = request.user if request.user.is_authenticated else None
            post.comments.create(body=body, author=author)
    return redirect("post_detail", pk=post.pk)


@login_required
def post_new(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()
        if title and body:
            post = Post.objects.create(title=title, body=body, author=request.user)
            return redirect("post_detail", pk=post.pk)
    return render(request, "posts/post_form.html", {})
