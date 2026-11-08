"""실제 로직 대신 가짜 결과를 돌려주는 mock 워크플로우.

단계: 입력 파싱 → 분석 → 결과 생성. 각 단계 시작 시 on_step 콜백을 호출해
UI가 진행 상황을 표시할 수 있게 합니다.
"""

import random
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from backend.tracing import span
from schema.workflow import StepResult, WorkflowResult

STEPS = ["입력 파싱", "분석", "결과 생성"]


def _timed(name: str, fn: Callable[[], str], delay: float) -> StepResult:
    with span("step", name) as s:
        start = time.perf_counter()
        time.sleep(delay)  # 실제 처리 시간 흉내
        output = fn()
        s.set(output=output)
    return StepResult(name=name, duration_sec=round(time.perf_counter() - start, 2), output=output)


def run_mock_workflow(
    text: str,
    delay: float = 0.8,
    on_step: Callable[[int, str], None] | None = None,
) -> WorkflowResult:
    with span("workflow", "mock_workflow", input={"text": text, "delay": delay}) as s:
        result = _run(text, delay, on_step)
        result.workflow_id = s.trace_id
        s.set(output=result.summary, keywords=result.keywords)
    return result


def _run(text: str, delay: float, on_step: Callable[[int, str], None] | None) -> WorkflowResult:
    started_at = datetime.now()
    words = text.split()
    keywords = [w for w, _ in Counter(w for w in words if len(w) > 1).most_common(5)]

    tasks = [
        lambda: f"{len(words)}개 단어, {len(text)}자",
        lambda: f"키워드 {len(keywords)}개 추출, 신뢰도 {random.uniform(0.7, 0.99):.2f}",
        lambda: "요약 생성 완료",
    ]

    steps = []
    for i, (name, task) in enumerate(zip(STEPS, tasks)):
        if on_step:
            on_step(i, name)
        steps.append(_timed(name, task, delay))

    preview = text if len(text) <= 60 else text[:60] + "…"
    return WorkflowResult(
        workflow_id="",
        input_text=text,
        steps=steps,
        summary=f"[mock] '{preview}' 에 대한 요약 결과입니다.",
        keywords=keywords,
        started_at=started_at,
    )
