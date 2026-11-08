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
docs/             # 문서 (agent.md, tracing.md)
tests/            # pytest
src/
├── app/          # Streamlit UI (main.py + views/)
├── backend/      # 설정, DB, 파일 저장, 실행 추적(tracing)
├── schema/       # Pydantic 모델
├── workflow/     # 처리 파이프라인
├── agent/        # Agent 루프 + providers/ (anthropic, openai)
├── mcp_server/   # MCP 서버
├── skills/       # Agent 도구 (@tool 로 등록)
└── data/
    ├── pdf/
    ├── image/
    └── db/       # SQLite
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
