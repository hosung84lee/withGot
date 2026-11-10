# src/schema — 데이터 계약 (잠금)

- 이 폴더는 세 영역(앱·약관·보험금)이 공유하는 계약이다. **에이전트는 수정하지 말 것.** (`.claude/settings.json` 에서도 막혀 있다)
- 필드 추가·변경이 필요하면 아래 형식으로 제안만 출력하고 멈출 것.
  - 모델 / 바꿀 필드 / 이유 / 영향받는 영역과 파일 / 갭 분석 개념 코드(해당하면)
- **변경 절차**: 셋이 합의 → 정한 한 사람이 직접 수정(에디터) → `[schema]` 커밋 → 나머지 둘이 pull 후 테스트.
- 파일: `coverage.py`(① 사고보장), `judgment.py`(② AI 판단), `escalation.py`(③), `claim.py`(④ 청구정보), `calc.py`(⑤ 계산 결과).
- LLM structured output 용 추출 모델과 코드에서 쓰는 내부 모델이 다르면 둘 다 여기에 두고 변환 함수도 여기에 둔다.
- 금액 int(원), 비율 `{numerator, denominator}`, 날짜 `YYYY-MM-DD` 문자열.
