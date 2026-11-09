"""약관 구조화 / 검증 / 분석 데이터 모델.

구조: 약관(TermsDocument) → 조(Article) → 항(Paragraph) → 호/목(Item)
편·장·절·관 같은 상위 제목은 Heading 으로 따로 두고, 각 조는 자기가 속한 제목 경로(path)를 가집니다.
"""

from typing import Literal

from pydantic import BaseModel, Field

HeadingKind = Literal["편", "장", "절", "관"]
HEADING_LEVEL: dict[str, int] = {"편": 0, "장": 1, "절": 2, "관": 3}


class TermsPart(BaseModel):
    """한 PDF 에 묶인 약관 하나 (주계약 약관, ○○특약 약관 …). 조 번호는 약관마다 1부터 다시 매깁니다."""

    title: str
    line: int


class Heading(BaseModel):
    kind: HeadingKind
    number: int
    title: str
    line: int  # 원문 줄 번호 (1부터)
    part: int | None = None  # TermsDocument.parts 의 위치. 약관 제목 줄이 없으면 None

    @property
    def label(self) -> str:
        return f"제{self.number}{self.kind} {self.title}".strip()


class ArticleRef(BaseModel):
    """본문 안의 다른 조항 인용 (예: '제12조제2항제3호')."""

    text: str  # 원문 그대로
    article: int
    sub: int | None = None  # 제12조의2 → 2
    paragraph: int | None = None
    item: int | None = None

    @property
    def article_label(self) -> str:
        return f"제{self.article}조" + (f"의{self.sub}" if self.sub else "")


class Item(BaseModel):
    """호(1.), 목(가.), 세목(1) / (1))."""

    level: Literal["호", "목", "세목"]
    label: str  # "1", "가", "1)" 등 원문 표기에서 구두점을 뺀 값
    text: str
    children: list["Item"] = Field(default_factory=list)


class Paragraph(BaseModel):
    """항. ①②… 표시가 없는 조의 본문은 number=None 인 항 하나로 둡니다."""

    number: int | None = None
    text: str = ""
    items: list[Item] = Field(default_factory=list)


class Article(BaseModel):
    number: int
    sub: int | None = None  # 제12조의2
    title: str | None = None
    deleted: bool = False  # '삭제' 표시된 조
    paragraphs: list[Paragraph] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)  # 상위 제목 (예: ["제2관 보험금의 지급"])
    addendum: int | None = None  # 부칙 소속이면 몇 번째 부칙인지 (1부터)
    part: int | None = None  # TermsDocument.parts 의 위치. 약관 제목 줄이 없으면 None
    line: int
    references: list[ArticleRef] = Field(default_factory=list)

    @property
    def label(self) -> str:
        base = f"제{self.number}조" + (f"의{self.sub}" if self.sub else "")
        return f"부칙 {base}" if self.addendum else base

    def full_text(self) -> str:
        """조 전체 본문 (제목 제외). 항/호/목을 원래 표기와 함께 이어 붙입니다."""
        lines: list[str] = []

        def walk(items: list[Item], depth: int) -> None:
            for it in items:
                mark = {"호": f"{it.label}.", "목": f"{it.label}.", "세목": it.label}[it.level]
                lines.append("  " * depth + f"{mark} {it.text}".rstrip())
                walk(it.children, depth + 1)

        for p in self.paragraphs:
            prefix = f"{circled(p.number)} " if p.number else ""
            if p.text or prefix:
                lines.append(f"{prefix}{p.text}".rstrip())
            walk(p.items, 1)
        return "\n".join(lines)


class Appendix(BaseModel):
    """별표 / 별지."""

    label: str
    text: str
    line: int


class TermsDocument(BaseModel):
    title: str = ""
    preamble: str = ""  # 첫 조 이전의 본문 (제목 제외)
    parts: list[TermsPart] = Field(default_factory=list)  # 주계약·특약이 묶인 PDF 의 약관별 제목
    headings: list[Heading] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)
    addenda: list[str] = Field(default_factory=list)  # 부칙 제목 줄 (예: "부칙 <2024.1.1>")
    addendum_text: list[str] = Field(default_factory=list)  # 조 없이 본문만 있는 부칙
    appendices: list[Appendix] = Field(default_factory=list)

    @property
    def body_articles(self) -> list[Article]:
        return [a for a in self.articles if not a.addendum]

    def find(self, label: str) -> Article | None:
        """'제12조', '12', '제12조의2', '부칙 제1조' 로 조를 찾습니다.
        부칙이 여러 개면 첫 번째 부칙에서 찾습니다."""
        norm = label.replace(" ", "")
        if norm.isdigit():
            norm = f"제{norm}조"
        return next((a for a in self.articles if a.label.replace(" ", "") == norm), None)


# ---------------------------------------------------------------- 검증

Severity = Literal["error", "warning", "info"]


class ValidationIssue(BaseModel):
    severity: Severity
    code: str  # 예: BROKEN_REFERENCE
    message: str
    article: str | None = None  # 문제 위치 (조 표기)
    line: int | None = None
    source: Literal["structure", "analysis"] = "structure"


# ---------------------------------------------------------------- AI 분석

RiskLevel = Literal["none", "low", "medium", "high"]

# 약관의 규제에 관한 법률 제6조~제14조 기준 불공정 유형
UNFAIR_TYPES: dict[str, str] = {
    "general_unfair": "신의성실 원칙 위반·고객에게 부당하게 불리 (제6조)",
    "liability_exemption": "면책 조항 (제7조)",
    "penalty": "과중한 손해배상액 예정·위약금 (제8조)",
    "termination": "계약의 해제·해지 제한 또는 사업자 해지권 확대 (제9조)",
    "obligation_change": "급부 내용의 일방적 결정·변경, 채무 이행 제한 (제10조)",
    "customer_rights": "고객의 항변권·상계권 등 권익 제한 (제11조)",
    "deemed_declaration": "의사표시 의제·통지 방법 부당 (제12조)",
    "agent_liability": "대리인 책임 가중 (제13조)",
    "litigation": "소송 제기 금지·재판관할 부당·입증책임 전가 (제14조)",
    "unclear": "모호하거나 해석이 갈리는 표현 (작성자 불이익 원칙, 제5조)",
    "other": "기타",
}

CLAUSE_CATEGORIES = [
    "목적·정의",
    "계약 성립·효력",
    "권리·의무",
    "요금·대금·보험료",
    "지급·환급",
    "면책·책임 제한",
    "계약 변경",
    "해지·해제·종료",
    "개인정보",
    "분쟁 해결",
    "기타",
]


class ClauseIssue(BaseModel):
    type: str = Field(description="UNFAIR_TYPES 의 키")
    description: str
    quote: str = Field(description="해당 조 본문에서 그대로 옮긴 문구")
    legal_basis: str = ""


class ClauseAnalysis(BaseModel):
    article: str = Field(description="조 표기. 예: 제12조, 제3조의2, 부칙 제1조")
    category: str
    summary: str
    risk: RiskLevel = "none"
    issues: list[ClauseIssue] = Field(default_factory=list)


class TermsOverview(BaseModel):
    document_type: str = ""  # 예: 보험 약관, 서비스 이용약관
    parties: list[str] = Field(default_factory=list)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)


class TermsAnalysis(BaseModel):
    overview: TermsOverview = Field(default_factory=TermsOverview)
    clauses: list[ClauseAnalysis] = Field(default_factory=list)
    model: str = ""


class TermsReport(BaseModel):
    """파이프라인 최종 결과."""

    trace_id: str = ""
    source: str = ""  # 파일명 또는 '직접 입력'
    document: TermsDocument
    structure_issues: list[ValidationIssue] = Field(default_factory=list)
    analysis: TermsAnalysis | None = None
    analysis_issues: list[ValidationIssue] = Field(default_factory=list)
    analysis_error: str | None = None

    @property
    def issues(self) -> list[ValidationIssue]:
        return self.structure_issues + self.analysis_issues


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def circled(n: int) -> str:
    return _CIRCLED[n - 1] if 1 <= n <= len(_CIRCLED) else f"({n})"
