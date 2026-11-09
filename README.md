# withGod

Streamlit 기반 앱.

## 실행

```bash
uv sync
cp .env.example .env
uv run streamlit run src/app/main.py
```

MCP 서버: `uv run python -m mcp_server.server`

## 폴더 구조

```
docs/             # 문서 (agent.md, tracing.md, terms.md, coverage_schema.md)
tests/            # pytest
src/
├── app/          # Streamlit UI (main.py + views/)
├── backend/      # 설정, DB, 파일 저장, 실행 추적(tracing)
├── schema/       # Pydantic 모델
├── workflow/     # 처리 파이프라인
├── agent/        # Agent 루프 + providers/ (anthropic, openai)
├── mcp_server/   # MCP 서버
├── skills/       # Agent 도구 (@tool 로 등록)
├── terms/        # 약관 구조화 · 검증 · AI 분석
└── data/
    ├── pdf/
    ├── image/
    └── db/       # SQLite
```

## 약관 분석

앱의 **약관 분석** 화면에서 약관(PDF/TXT/붙여넣기)을 조·항·호·목으로 구조화하고, 구조를 검증한 뒤
AI 로 조항별 위험(약관규제법 기준)을 검토합니다. AI 분석 결과가 원문에 근거하는지도 다시 검증합니다.
자세한 내용: [docs/terms.md](docs/terms.md)

약관에서 뽑은 보장 정보를 담는 표준 구조(사고보장 Canonical Schema) 설계: [docs/coverage_schema.md](docs/coverage_schema.md)

```python
from terms import parse_terms, validate_structure, run_terms_pipeline

doc = parse_terms(text)
issues = validate_structure(doc)
report = run_terms_pipeline(text, provider="anthropic")
```

## Agent

- 사용법과 동작 구조: [docs/agent.md](docs/agent.md)
- 실행 추적과 디버깅: [docs/tracing.md](docs/tracing.md)

`.env`에 사용할 provider의 API 키를 넣고 앱의 **Agent** 화면에서 provider/모델을 골라 대화합니다.
PDF·이미지는 채팅에 첨부하거나, 사이드바 **문서 보관함**에 올려 두면 agent가 직접 찾아 읽습니다.
실행 과정은 **Trace** 화면에서 단계별로 볼 수 있습니다.

```python
from agent import Agent

result = Agent("anthropic").run("지금 서울 몇 시야?")   # 또는 "openai"
print(result.output, result.tool_traces)
```

도구 추가: `src/skills/` 에 함수를 만들고 `@tool` 을 붙이면 됩니다 (타입 힌트 → JSON Schema 자동 생성, docstring → 설명).

테스트: `uv run pytest`

실제 약관 PDF(`insurance-workbench/data/reference/policies/`)를 읽는 느린 테스트는 기본으로 건너뜁니다.
약관 구조화(`src/terms/`)를 고쳤다면 `uv run pytest --pdf` 로 함께 돌려 주세요 (PDF 텍스트 추출 때문에 1분 넘게 걸립니다).
