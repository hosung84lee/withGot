# 보장잇 팀 개발

세 사람 모두 같은 비공개 GitHub 저장소를 복제하고 `main`에서 작업을 시작합니다. Node.js와 Python 버전은 저장소의 `.node-version`과 `.python-version`을 확인합니다.

```bash
uv sync --locked
npm --prefix apps/web ci
```

Windows에서는 `scripts/start-api.cmd`와 `scripts/start-ui.cmd`를 각각 실행합니다. macOS와 Linux에서는 `bash scripts/dev.sh`로 실행합니다. 웹은 http://127.0.0.1:5173 에서 확인합니다. [로컬 실행 안내](../LOCAL_SETUP.md)

1. 최신 `main`을 받아 작업별 브랜치를 만듭니다. 첫 작업은 서류 화면, 약관·계산, 조회 API·검증으로 나눌 수 있습니다.
2. 브랜치를 올리고 `main` 대상 PR에 변경 이유, 재현 방법, 테스트 결과를 적습니다.
3. 다른 팀원 한 명이 검토하고 GitHub Actions의 `Verify Bojangit`이 통과하면 병합합니다. 저장소에서 승인 강제 설정을 사용할 수 없는 경우에도 같은 팀 규칙을 적용합니다.
4. 배포 담당자가 시연 사이트에 반영한 `main` 커밋을 기록합니다. GitHub 병합과 OpenAI Sites 배포는 각각 진행합니다.

테스트에는 `apps/web/public/samples`와 `data/synthetic`의 가상 서류를 사용합니다. 실제 의료서류와 비밀키는 개인 PC에 보관합니다.
