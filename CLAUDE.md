# withGot 작업 안내 (Claude Code)

- 먼저 읽을 문서: `docs/HACKATHON.md` (현재 상태, 환경 세팅, 다음 할 일)
- 해커톤에서는 이 코드를 쓰지 않고 새 저장소에 다시 만듦: 재구현 명세는 `docs/REBUILD_GUIDE.md`
- 세부: `docs/terms.md` (약관 구조화·검증), `docs/coverage_extract.md` (사고보장 추출), `docs/coverage_schema.md` (스키마)
- 패키지 관리: `uv` (`uv sync`, `uv run …`). Python 3.12.
- 테스트: `uv run pytest` (빠름). `src/terms/` 를 고쳤으면 `uv run pytest --pdf` 로 실제 약관 PDF 까지 확인.
- 린트: `uv run ruff check src tests tools`, 포맷: `uv run ruff format src tests tools` (줄 길이 100).
- LLM: OpenAI 전용 (`agent.Agent`, `agent.llm.OpenAIClient`). `.env` 의 `OPENAI_API_KEY`·`OPENAI_MODEL`.
  테스트는 `tests/fakes.py` 의 `fake_llm` 으로 API 키 없이 돈다.
- 약관 PDF: `insurance-workbench/data/reference/policies/` (삼성생명 7개). `insurance-workbench/` 는 별도 프로젝트.
- 커밋 메시지는 한국어, 작업 단위로. main 에 직접 커밋해 왔음.
