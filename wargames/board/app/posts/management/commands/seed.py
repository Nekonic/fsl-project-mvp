from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from posts.models import Comment, Post

USERS = [
    ("admin", "admin1234", True),
    ("jiwoo", "jiwoo1234", False),
    ("minseo", "minseo1234", False),
]

POSTS = [
    ("공지: 커뮤니티 게시판을 열었습니다", "자유롭게 글을 올리고 댓글을 달아 주세요. 광고와 욕설은 안내 없이 정리됩니다.", "admin", 27, "10:12"),
    ("점심 메뉴 추천 받습니다", "회사 근처 맛집 아시는 분 댓글 부탁드려요. 일주일째 같은 식당만 가고 있어요.", "jiwoo", 25, "11:48"),
    ("주말 스터디 모집", "토요일 오전에 모여서 같이 공부하실 분 구합니다. 장소는 강남역 근처 스터디 카페입니다.", "minseo", 23, "20:35"),
    ("노트북 추천 부탁드립니다", "개발 공부용으로 쓸 가벼운 노트북을 찾고 있습니다. 예산은 150만 원 정도입니다.", "jiwoo", 21, "22:07"),
    ("강남역 근처 조용한 카페 있나요", "노트북 들고 몇 시간 앉아 있어도 눈치 안 보이는 카페를 찾습니다.", "minseo", 19, "14:26"),
    ("서울 맛집 추천 모음", "각자 다녀온 곳 중에 괜찮았던 식당을 댓글로 남겨 주세요. 모이면 정리해서 올리겠습니다.", "admin", 17, "09:41"),
    ("파이썬 입문 책 추천", "프로그래밍이 처음인데 처음 읽기 좋은 책이 있을까요?", "minseo", 15, "21:19"),
    ("이번 주말 모임 장소 변경 안내", "토요일 모임 장소를 한 정거장 옆 역으로 바꿉니다. 시간은 그대로 오전 10시입니다.", "admin", 13, "18:03"),
    ("주말에 다녀온 북한산 후기", "날씨가 좋아서 정상까지 올라갔습니다. 사진은 다음 모임 때 보여드릴게요.", "jiwoo", 11, "19:52"),
    ("스터디 모집 두 번째 기수", "지난 스터디가 반응이 좋아서 한 번 더 엽니다. 이번에는 평일 저녁 8시입니다.", "minseo", 9, "23:14"),
    ("모니터 암 쓰시는 분 계신가요", "책상이 좁아서 모니터 암을 사려는데 써 보신 분 후기가 궁금합니다.", "jiwoo", 7, "13:37"),
    ("점심 도시락 싸 다니는 분", "한 달째 도시락을 싸 다니는데 생각보다 오래 걸리지는 않네요. 메뉴 공유해 봅니다.", "minseo", 5, "12:05"),
    ("공지: 게시판 점검 안내", "다음 주 화요일 새벽에 짧게 점검이 있습니다. 그 시간에는 글쓰기가 되지 않을 수 있습니다.", "admin", 4, "17:30"),
    ("연휴에 다들 뭐 하세요", "긴 연휴인데 계획 있으신 분들 있나요? 저는 집에서 쉴 예정입니다.", "jiwoo", 2, "21:44"),
    ("이번 주 모임 후기", "오랜만에 다 같이 모여서 좋았습니다. 다음 모임 날짜는 투표로 정하겠습니다.", "minseo", 1, "16:58"),
]

COMMENTS = [
    (1, "jiwoo", "게시판 열어 주셔서 감사합니다", 95),
    (1, "minseo", "공지 확인했습니다", 310),
    (2, "minseo", "회사 앞 칼국수집 괜찮아요. 점심시간에는 줄이 길어서 조금 일찍 가세요.", 52),
    (2, "admin", "저는 지하 푸드코트 쪽 백반집을 자주 갑니다.", 180),
    (2, None, "저도 그 근처에서 먹어 봤는데 괜찮았어요", 600),
    (3, "jiwoo", "저도 참여하고 싶어요", 33),
    (3, "admin", "혹시 몇 시에 모이나요?", 90),
    (3, "minseo", "오전 10시입니다. 장소는 곧 다시 안내드릴게요.", 130),
    (4, "minseo", "가벼운 쪽이면 13인치 모델을 보세요. 오래 들고 다니기에 편합니다.", 70),
    (5, "jiwoo", "역 뒤편 골목 안쪽에 조용한 곳이 하나 있습니다. 콘센트도 넉넉해요.", 41),
    (5, None, "여기 가 봤는데 괜찮았어요", 1500),
    (6, "jiwoo", "저는 성수동 쪽 국숫집을 추천합니다.", 120),
    (6, "minseo", "홍대입구역 근처 덮밥집도 좋았어요.", 240),
    (7, "admin", "처음에는 얇은 입문서 하나를 끝까지 읽는 편이 좋습니다.", 88),
    (8, "minseo", "변경 안내 확인했습니다", 25),
    (8, "jiwoo", "한 정거장이면 걸어갈 수 있겠네요.", 140),
    (9, "minseo", "부럽습니다. 저는 이번 주말에 가 보려고요.", 200),
    (9, None, "사진 기대할게요", 480),
    (10, "jiwoo", "저도 신청하고 싶어요", 18),
    (10, "admin", "평일 저녁이면 몇 시까지 진행하나요?", 75),
    (10, "minseo", "10시까지입니다. 늦게 끝나지 않게 하겠습니다.", 112),
    (11, "minseo", "저는 한 달째 쓰고 있는데 책상이 훨씬 넓어졌어요.", 64),
    (12, "jiwoo", "메뉴 공유 감사합니다. 다음 주에 따라 해 볼게요.", 55),
    (13, "jiwoo", "점검 안내 확인했습니다", 37),
    (14, "minseo", "저도 집에서 쉴 것 같아요", 22),
    (14, "admin", "푹 쉬세요", 71),
    (15, "jiwoo", "좋은 후기 감사합니다", 15),
    (15, "admin", "다음 모임 투표는 내일 올리겠습니다.", 93),
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
            now = timezone.now()
            today = timezone.localtime(now).replace(second=0, microsecond=0)
            posted = []
            for title, body, username, days_ago, clock in POSTS:
                hour, minute = clock.split(":")
                when = today.replace(hour=int(hour), minute=int(minute)) - timedelta(days=days_ago)
                post = Post.objects.create(title=title, body=body, author=authors[username])
                Post.objects.filter(pk=post.pk).update(created_at=when)
                posted.append((post, when))
            for number, username, body, minutes_after in COMMENTS:
                post, when = posted[number - 1]
                comment = Comment.objects.create(post=post, author=authors.get(username), body=body)
                Comment.objects.filter(pk=comment.pk).update(
                    created_at=min(when + timedelta(minutes=minutes_after), now - timedelta(minutes=1))
                )

        self.stdout.write("seeded")
