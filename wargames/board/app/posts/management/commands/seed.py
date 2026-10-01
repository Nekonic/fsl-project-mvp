from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from posts.models import Post

USERS = [
    ("admin", "admin1234", True),
    ("jiwoo", "jiwoo1234", False),
    ("minseo", "minseo1234", False),
]

POSTS = [
    ("공지: 커뮤니티 게시판을 열었습니다", "자유롭게 글을 올리고 댓글을 달아 주세요."),
    ("점심 메뉴 추천 받습니다", "회사 근처 맛집 아시는 분 댓글 부탁드려요."),
    ("주말 스터디 모집", "토요일 오전에 모여서 같이 공부하실 분 구합니다."),
]


class Command(BaseCommand):
    def handle(self, *args, **options):
        authors = {}
        for username, password, is_admin in USERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"is_staff": is_admin, "is_superuser": is_admin}
            )
            if created:
                user.set_password(password)
                user.save()
            authors[username] = user

        if not Post.objects.exists():
            admin = authors["admin"]
            for title, body in POSTS:
                Post.objects.create(title=title, body=body, author=admin)

        self.stdout.write("seeded")
