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
src/
├── app/          # Streamlit UI (main.py + views/)
├── backend/      # 설정, DB, 파일 저장
├── schema/       # Pydantic 모델
├── workflow/     # 처리 파이프라인
├── agent/        # 에이전트 (LLM 호출)
├── mcp_server/   # MCP 서버
├── skills/       # 에이전트용 스킬/도구
└── data/
    ├── pdf/
    ├── image/
    └── db/       # SQLite
```
