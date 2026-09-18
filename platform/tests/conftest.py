import sys
from pathlib import Path

# redteam 은 저장소 루트의 형제 디렉터리다. 루트 자체를 sys.path 에 넣으면
# `platform` 이 표준 라이브러리를 가린다 — 하지만 platform/ 에는
# __init__.py 가 없고 우리는 늘 platform/ 을 작업 디렉터리로 두므로
# 루트를 얹어도 `import platform` 은 표준 라이브러리로 간다.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
