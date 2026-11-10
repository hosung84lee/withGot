# 해커톤 새 저장소용 에이전트 규칙 템플릿

팀 구성안(CLAUDE.md / AGENTS.md 구성안)을 평가 결과대로 고친 버전입니다. **새 저장소 루트에 이 폴더 내용을 그대로 복사**합니다.

```
AGENTS.md  CLAUDE.md  .claude/settings.json
src/schema/AGENTS.md  src/app/AGENTS.md  src/workflow/AGENTS.md
src/agent/AGENTS.md   src/mcp_server/AGENTS.md  src/skills/AGENTS.md
```

하위 폴더마다 `CLAUDE.md` 를 `@AGENTS.md` 한 줄로 만들어 둡니다 (복사 후 아래 명령, PowerShell):

```powershell
foreach ($d in "src/schema","src/app","src/workflow","src/agent","src/mcp_server","src/skills") { Set-Content "$d/CLAUDE.md" "@AGENTS.md" -Encoding utf8 }
```

## 원래 구성안에서 바꾼 것

| 항목 | 원래 | 바꾼 것 | 이유 |
|---|---|---|---|
| 범위 | 서류 이미지 분류·태깅, 계산 코드 생성이 기본 | 시나리오 JSON 입력 + **고정 계산 툴**이 기본, 둘은 추가 목표 | 보험금 담당 과부하, 생성 코드 검증 시간 |
| 흐름 1 | LLM 페이지 추출 → 부분 PDF | **규칙 기반 구조화 → 묶음** | 실제 약관 7개로 검증된 방식, 정확하고 비용 0 |
| 비율 | `int(%)` | `{numerator, denominator}` | 본인부담률 등 정수가 아닌 비율 |
| 잠금 | `Edit` 만 deny | `Edit` + `Write` deny, 변경 절차 추가 | `Write` 로 새로 쓰기가 막히지 않음 |
| 계약 | escalations 위치 없음 | `schema/escalation.py` | 약관·보험금·앱이 모두 씀 |
| 정답 | 담당 없음 | 약관 정답 = 약관, 계산 정답 = 보험금 | 30건 목표 |
| 근거 검증 위치 | `agent/` | `workflow/policy/` (순수 코드) | LLM 호출이 아님 |
| 보안 | 없음 | 사내 Confidential 자료 금지 규칙 | 내부 테이블명·화면 캡처 유출 방지 |
| 스택 | 3.11, pip, PyMuPDF, anthropic+openai | **H0 확정** 항목으로 (권장: 3.12, uv, pypdf, 받은 키 하나) | 검증된 조합, PyMuPDF 는 AGPL |

계약(①~⑤)의 내용은 [../TEAM_INTERFACE.md](../TEAM_INTERFACE.md) 에 있습니다.
