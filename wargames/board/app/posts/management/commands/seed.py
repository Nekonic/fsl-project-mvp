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
    ("공지: 커뮤니티 게시판을 열었습니다", "자유롭게 글 올리고 댓글 달아 주세요. 광고나 욕설 글은 안내 없이 정리됩니다.", "admin", 27, "10:12"),
    ("점심 메뉴 추천 받습니다", "회사 근처에서 점심 먹을 데 추천해 주세요. 일주일째 같은 식당만 가서 이제 좀 질려요 ㅠㅠ", "jiwoo", 25, "11:48"),
    ("주말 스터디 모집", "토요일 오전에 모여서 같이 공부하실 분 구해요. 강남역 근처 스터디 카페에서 하고, 각자 공부하는 분위기라 편하게 오셔도 됩니다.", "minseo", 23, "20:35"),
    ("노트북 추천 부탁드립니다", "개발 공부용으로 쓸 가벼운 노트북을 찾고 있어요. 예산은 150만 원 정도 생각하고 있습니다.", "jiwoo", 21, "22:07"),
    ("강남역 카페 괜찮은 데 있나요", "노트북 들고 가서 몇 시간 앉아 있어도 눈치 안 보이는 곳을 찾고 있어요. 콘센트 있으면 더 좋고요.", "minseo", 19, "14:26"),
    ("서울 맛집 추천 모음", "다녀와서 괜찮았던 식당 있으면 댓글로 남겨 주세요. 모이면 정리해서 따로 올리겠습니다.", "admin", 17, "09:41"),
    ("파이썬 입문 책 추천", "프로그래밍은 완전 처음이에요. 혼자 보기 괜찮은 입문서 있으면 추천 부탁드려요.", "minseo", 15, "21:19"),
    ("이번 주말 모임 장소 변경 안내", "토요일 모임 장소가 강남역에서 역삼역 2번 출구 앞 카페로 바뀌었습니다. 시간은 그대로 오전 10시입니다.", "admin", 13, "18:03"),
    ("주말에 다녀온 북한산 후기", "날씨가 좋아서 정상까지 올라갔어요. 사진은 다음 모임 때 보여드릴게요.", "jiwoo", 11, "19:52"),
    ("스터디 모집 (2기)", "1기 반응이 좋아서 한 번 더 엽니다. 이번엔 평일 저녁 8시에 모여요. 관심 있으신 분 댓글 남겨 주세요.", "minseo", 9, "23:14"),
    ("모니터 암 쓰시는 분 계신가요", "책상이 좁아서 모니터 암을 사려고 하는데, 써 보신 분 후기가 궁금해요.", "jiwoo", 7, "13:37"),
    ("도시락 싸 다니시는 분 계신가요", "한 달째 도시락 싸 다니는데 생각보다 오래 안 걸리네요. 요즘은 계란말이랑 볶음밥을 번갈아 싸요. 다른 분들 메뉴도 궁금합니다.", "minseo", 5, "12:05"),
    ("공지: 게시판 점검 안내", "다음 주 화요일 새벽에 짧게 점검이 있습니다. 그 시간에는 글쓰기가 되지 않을 수 있습니다.", "admin", 4, "17:30"),
    ("연휴에 다들 뭐 하세요", "긴 연휴인데 계획 있으신 분 있나요? 저는 집에서 쉴 예정이에요.", "jiwoo", 2, "21:44"),
    ("이번 주 모임 후기", "오랜만에 다 같이 모여서 좋았어요. 다음 모임 날짜는 투표로 정할게요.", "minseo", 1, "16:58"),
]

COMMENTS = [
    (1, "jiwoo", "게시판 열어 주셔서 감사합니다", 95),
    (1, "minseo", "오 드디어 열렸네요. 자주 들를게요", 310),
    (2, "minseo", "칼국수 어때요? 12시 넘으면 줄이 길어서 11시 반쯤 가야 해요.", 52),
    (2, "admin", "저는 백반집을 자주 가요. 반찬이 매일 바뀌어서 안 질립니다.", 180),
    (2, None, "칼국수에 한 표요 ㅎㅎ", 600),
    (3, "jiwoo", "저도 참여하고 싶어요!", 33),
    (3, "admin", "혹시 몇 시에 모이나요?", 90),
    (3, "minseo", "오전 10시예요. 두세 시간 정도 하려고 합니다.", 130),
    (4, "minseo", "가벼운 걸 원하시면 13인치 쪽이 좋아요. 저도 쓰는데 매일 들고 다녀도 부담이 없어요.", 70),
    (5, "jiwoo", "역 뒤편 골목 안쪽에 조용한 데 하나 있어요. 콘센트도 넉넉합니다.", 41),
    (5, None, "저도 거기 가 봤는데 괜찮았어요. 오래 앉아 있기 좋아요", 1500),
    (6, "jiwoo", "성수동 국숫집이요. 웨이팅이 좀 있는데 기다릴 만해요.", 120),
    (6, "minseo", "홍대입구역 근처 덮밥집도 좋았어요 ㅎㅎ", 240),
    (7, "admin", "처음엔 얇은 책 하나를 끝까지 보는 게 좋아요. 여러 권 사면 앞부분만 읽게 되더라고요.", 88),
    (7, "jiwoo", "저는 예제를 직접 따라 치면서 봤어요. 그게 제일 빨리 늘었어요", 150),
    (8, "minseo", "역삼역이면 저는 더 가깝네요 ㅎㅎ", 25),
    (8, "jiwoo", "역삼이면 걸어가도 되겠네요. 토요일에 봬요!", 140),
    (9, "minseo", "부럽네요. 저는 이번 주말에 가 보려고요.", 200),
    (9, None, "사진 기대할게요", 480),
    (10, "jiwoo", "저도 신청하고 싶어요", 18),
    (10, "admin", "평일 저녁이면 몇 시까지 하나요?", 75),
    (10, "minseo", "10시까지요. 두 시간만 하고 끝내려고요.", 112),
    (11, "minseo", "한 달째 쓰고 있는데 책상이 훨씬 넓어졌어요. 높이 맞추기도 편하고요.", 64),
    (12, "jiwoo", "계란말이 도시락 좋네요. 저도 해 보고 싶은데 아침에 일어나는 게 문제예요 ㅠㅠ", 55),
    (13, "jiwoo", "몇 시쯤 끝나나요?", 37),
    (13, "admin", "새벽 4시 전에는 끝날 예정입니다.", 60),
    (14, "minseo", "저도 집에서 쉴 것 같아요", 22),
    (14, "admin", "푹 쉬세요", 71),
    (15, "jiwoo", "저도 즐거웠어요. 다음에도 꼭 갈게요", 15),
    (15, "admin", "투표 올라오면 공지에도 걸어 둘게요.", 93),
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
