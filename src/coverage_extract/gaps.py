"""스키마 갭 분석: 약관에는 있는데 사고보장 데이터로 담지 못한 것을 찾습니다 (LLM 없이 규칙으로).

추출 결과가 스키마에 '잘 들어간 것'만 보면, 스키마가 표현하지 못해 빠진 내용은 드러나지 않습니다.
이 모듈은 반대 방향으로, 약관 원문에서 출발해 다음 세 가지를 찾습니다.

1. 개념 갭 (CONCEPTS): 원문에 나오는 보상 규칙의 개념 중 스키마에 자리가 없거나(structure·field)
   글로만 담기는(partial) 것. 개념마다 '지금 표현'과 '제안하는 확장'을 둡니다.
2. 근거 없는 원문 (uncovered): 사고보장 데이터가 있는 묶음에서, 어떤 규칙·보상 제외도 인용하지 않은 항·호.
   → 추출에서 빠졌거나 스키마에 담을 곳이 없어 버려진 내용.
3. 빈 필드 (unfilled): 스키마에 필드는 있는데 원문에 값이 있음에도 데이터에서 비어 있는 것.

    report = analyze_gaps(doc, product)        # product 는 선택 (없으면 1번만)
    report.findings, report.uncovered, report.unfilled
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from coverage_extract.bundles import Bundle, build_bundles
from coverage_extract.grounding import expected_numbers, numbers_in, squash
from schema.coverage import Product
from schema.terms import Article, Item, TermsDocument, circled

GapKind = Literal["structure", "field", "partial"]
KIND_LABEL = {"structure": "구조 확장", "field": "필드 추가", "partial": "부분 표현"}


class Concept(BaseModel):
    code: str
    name: str
    kind: GapKind
    now: str = Field(description="지금 스키마에서의 표현")
    proposal: str = Field(description="제안하는 확장")
    patterns: list[str]
    exclusion_only: bool = False  # 보상하지 않는 사항 조에서만 찾음


# 실손 2605 묶음 8개와 인터넷암 2404 주계약에서 실제로 나온 개념으로 만든 목록.
# 새 약관에서 새 개념이 보이면 여기에 추가합니다.
CONCEPTS: list[Concept] = [
    Concept(
        code="SHARED_LIMIT",
        name="여러 보상의 합산 한도",
        kind="structure",
        now="규칙마다 같은 연간 한도(Limit.amounts)를 따로 복사. 합산된다는 사실이 사라짐",
        proposal="LimitPool{id, amount, per, members:[rule_id]} — 보장 단위 공유 한도",
        patterns=[r"합산하여\d[\d,]*(?:억|천만|백만|만|천)?원(?:이내|한도)", r"보상금액을합산"],
    ),
    Concept(
        code="COUNTING_RULE",
        name="1회 산정 규칙 (합산·분리)",
        kind="structure",
        now="없음. 같은 날 외래+처방 합산, 치료행위·부위별 1회 등 '몇 회로 볼지'를 담을 곳이 없음",
        proposal="CountingRule{unit: visit|day|treatment|body_part, merge_when, deductible_on_merge}",
        patterns=[r"(?:통원)?1회로보[아고]", r"1회의통원으로보아", r"각(?:치료|진단)행위를1회로"],
    ),
    Concept(
        code="EVENT_DEFINITION",
        name="사고 단위 정의 (하나의 질병·1회 입원)",
        kind="structure",
        now="없음. 한도·공제를 적용하는 단위의 정의가 규칙에 연결되지 않음",
        proposal="EventDefinition{kind: one_disease|one_stay, text, source} + 규칙에서 참조",
        patterns=[r"[“\"]?하나의질병[”\"]?이란", r"1회입원이라함은"],
    ),
    Concept(
        code="STRUCTURED_EXCEPTION",
        name="보상 제외의 예외 (다만 …은 보상)",
        kind="partial",
        now="Exclusion.exception 글(요약)로만 저장. KCD·의료비 구분·나이 조건을 계산에 못 씀",
        proposal="ExclusionException{kcd:[KcdRange], cost_type, insured_condition, age_limit}",
        patterns=[r"\(다만,[^)]*보상"],
        exclusion_only=True,
    ),
    Concept(
        code="STAGED_LIMIT",
        name="단계적 보장 (최초 N회 후 확인 시 추가)",
        kind="structure",
        now="Limit.count 하나뿐. '최초 10회, 이후 개선 확인 시 10회 단위로 50회'를 못 담음",
        proposal="Limit.stages{initial, step, max, requires}",
        patterns=[r"최초\d+회보장하고", r"\d+회단위로"],
    ),
    Concept(
        code="ROUTING",
        name="다른 보장종목으로 보상 이관",
        kind="structure",
        now="없음. '항암제 주사료는 《질병비급여형》에서 보상' 같은 이관이 빠짐",
        proposal="RuleConditions.excluded_items + redirect_to{section, article}",
        patterns=[r"《[^》]+》제\d+조\(보상내용\)(?:또는《[^》]+》제\d+조\(보상내용\))?에서보상"],
    ),
    Concept(
        code="PERIOD_BASIS",
        name="'연간'의 기준 (보험연도)",
        kind="field",
        now="AmountLimit.per='year' 만. 보험연도(계약해당일)인지 달력 연도인지 구분 없음",
        proposal="AmountLimit.period_basis: policy_year | calendar_year",
        patterns=[r"[‘']?연간[’']?이라함은", r"계약해당일부터1년단위"],
    ),
    Concept(
        code="REMAINING_LIMIT",
        name="연장 보상의 잔여 한도",
        kind="field",
        now="Extension{days, max_visits, max_visit_days} 만. 연장 기간 한도가 '연간 한도 − 이미 지급한 금액'인 것을 못 담음",
        proposal="Extension.limit_basis = remaining_annual_amount | remaining_annual_days",
        patterns=[r"차감한잔여(?:금액|일수)"],
    ),
    Concept(
        code="COST_REDUCTION",
        name="감면받은 의료비의 계산 기준",
        kind="field",
        now="없음. 감면 후/감면 전 의료비 중 무엇으로 계산하는지와 그 예외가 빠짐",
        proposal="Benefit.reduction_basis{default: after, before_when:[근로소득 포함, 국가유공자 …]}",
        patterns=[r"감면후실제본인이부담한의료비", r"감면(?:또는지원)?전의료비"],
    ),
    Concept(
        code="EXCLUSION_PERIOD",
        name="기간이 정해진 보상 제외",
        kind="field",
        now="Exclusion 에 기간 필드 없음. '가입일부터 2년 이내'만 제외인 것이 사라짐",
        proposal="Exclusion.within_days (가입일 기준)",
        patterns=[r"가입일로부터\d+년이내"],
        exclusion_only=True,
    ),
    Concept(
        code="INSURED_CONDITION",
        name="피보험자 조건 (가입 당시 태아·나이)",
        kind="field",
        now="없음. 조건이 Exclusion.exception 글에 섞임",
        proposal="Condition.insured{at_entry: fetus, age_max}",
        patterns=[r"가입당시태아", r"\d+세까지보상"],
    ),
    Concept(
        code="CONTRACT_HISTORY",
        name="갱신·전환·재가입 시 처리",
        kind="field",
        now="없음. 연장 보상 미적용, 가입일 승계 같은 계약 이력 조건이 빠짐",
        proposal="Condition.contract_history{on: renewal|conversion|re_entry, effect}",
        patterns=[r"자동갱신", r"재가입"],
    ),
    Concept(
        code="ELIGIBILITY",
        name="대상 질환 조건",
        kind="field",
        now="Risk.coverage_code 는 KCD 묶음만. '산정특례 대상 질환'처럼 제도로 정한 대상을 못 담음",
        proposal="Risk.eligibility{kind: special_copay_case, text}",
        patterns=[r"산정특례"],
    ),
    Concept(
        code="COST_ITEMS",
        name="보상 대상 비용 항목",
        kind="field",
        now="cost_type(급여·비급여)만. 행위료·약제비·치료재료대, 입원실료·입원수술비 같은 포함 항목이 빠짐",
        proposal="Benefit.included_items[] / excluded_items[]",
        patterns=[r"\(행위료,약제비", r"\(입원실료,"],
    ),
    Concept(
        code="ANNUAL_COUNT",
        name="연간 횟수 한도",
        kind="partial",
        now="Limit.count 는 있으나 기간(연간)과 금액 한도와의 결합을 못 담음",
        proposal="Limit.count_per: year | stay, 금액 한도와 함께 '둘 중 먼저 도달'",
        patterns=[r"이내에서\d+회까지"],
    ),
    Concept(
        code="KCD_VERSION",
        name="KCD 차수",
        kind="partial",
        now="KcdRange.kcd_version 필드 있음 (값을 채우는지 데이터에서 확인)",
        proposal="추출 프롬프트에 KCD 차수·이후 개정 포함 규칙을 넣고 kcd_version 을 채움",
        patterns=[r"제\d+차한국표준질병사인분류"],
    ),
    # ---- 정액형(암보험) 약관에서 나온 개념: 인터넷암 2404 주계약 기준
    Concept(
        code="STAGE_CRITERIA",
        name="병기·조직형으로 나누는 대상 질병",
        kind="structure",
        now="담보코드는 KCD 범위만. '유방암 중 TNM 1기', '갑상선암 중 수질성·역형성암'은 "
        "special_conditions 글로만 남아 계산·심사에서 자동 판정 못 함",
        proposal="CoverageCode.criteria{system: AJCC, edition, stage | histology | depth, text}",
        patterns=[r"AJCC암병기설정매뉴얼", r"수질성암", r"점막하층\(submucosa\)까지는"],
    ),
    Concept(
        code="CODE_SUBTRACTION",
        name="담보코드에서 일부 질병 제외",
        kind="structure",
        now="KcdRange 는 포함 범위만. '암 중 기타피부암·초기유방암 … 제외', '유방암 중 초기유방암을 "
        "제외한 나머지'를 담보코드끼리의 관계로 못 담음",
        proposal="CoverageCode.excludes: [code] (다른 담보코드를 빼는 관계)",
        patterns=[r"있어서암에해당하지않습니다", r"에해당하는질병중.{2,15}을제외한나머지"],
    ),
    Concept(
        code="GROUPED_OCCURRENCE",
        name="묶음 단위 지급 횟수 (합산·각각 1회)",
        kind="structure",
        now="occurrence='first' 는 규칙 하나 기준. '셋 중 최초 1회', '7가지 분류질병마다 각각 1회', "
        "'Ⅰ·Ⅱ·Ⅲ 을 합하여 암진단보험금'을 못 담음",
        proposal="OccurrenceGroup{id, members:[rule_id | code], count, per: group | each_member}",
        patterns=[r"중최초1회", r"각각1회의진단확정에한", r"을합하여암진단보험금이라"],
    ),
    Concept(
        code="PREMIUM_WAIVER",
        name="보험료 납입면제",
        kind="structure",
        now="없음. 보험금이 아닌 급부(차회 이후 보험료 납입면제)를 규칙으로 담을 곳이 없음",
        proposal="Benefit.type='premium_waiver' + 사유(장해지급률 합산 50% 이상, 암 진단)",
        patterns=[r"보험료의?납입을면제", r"보험료의?납입이면제", r"보험료납입면제", r"장해지급률"],
    ),
    Concept(
        code="INSURED_SEX",
        name="피보험자 성별 조건",
        kind="field",
        now="special_conditions 글(type: sex)로만 저장",
        proposal="Condition.insured{sex: F | M} — 담보코드별로 지정",
        patterns=[r"피보험자가(?:여성|남성)인경우에한"],
    ),
    Concept(
        code="RECURRENCE",
        name="같은 질병의 재발·전이·잔존 부지급과 재보장",
        kind="field",
        now="special_conditions 글(type: prior_payment). 범위(같은 암)와 재보장 조건(5년 무진단·무치료)이 없음",
        proposal="SpecialCondition{type: same_disease, includes: [recurrence, metastasis, residual], "
        "reset_after_years, reset_requires}",
        patterns=[r"잔존하거나재발또는전이된경우포함\)에회사는해당보험금을", r"\d+년이지나는동안"],
    ),
    Concept(
        code="PRIMARY_SITE",
        name="전이암의 원발부위 기준 분류",
        kind="field",
        now="없음. C77~C80(이차성) 진단 코드를 원발부위 코드로 바꿔 판정한다는 규칙이 빠짐",
        proposal="CoverageCode.classify_by: primary_site (대상 KCD: C77~C80)",
        patterns=[r"원발부위\(최초발생한부위\)를기준으로분류"],
    ),
    Concept(
        code="DIAGNOSIS_METHOD",
        name="진단 확정 방법",
        kind="field",
        now="special_conditions type='diagnosis_confirmed' 만. 누가(병리과 전문의), 어떤 검사로, "
        "검사가 불가능할 때의 대체 증빙이 빠짐",
        proposal="DiagnosisRequirement{by, methods:[조직검사 …], confirmed_at, fallback}",
        patterns=[r"병리과(?:또는진단검사의학과)?전문의자격증", r"에따른진단이가능하지않을때"],
    ),
    Concept(
        code="DEEMED_DIAGNOSIS",
        name="사망 후 확인 시 진단일 간주·기지급액 차감",
        kind="field",
        now="없음. 사망일을 진단 확정일로 보는 규칙과 이미 지급한 계약자적립액 차감이 빠짐",
        proposal="BenefitRule.deemed_event{when: death_confirmed, date: death_date} + Benefit.offset",
        patterns=[r"사망일을진단확정일로보고", r"이미지급된계약자적립액을차감"],
    ),
    Concept(
        code="START_DATE_BASIS",
        name="보장개시일·감액기간의 기준일 (최초계약·갱신·부활)",
        kind="partial",
        now="exemption_days·reduction.days 숫자만. 기준일(최초계약일, 부활일)과 갱신계약에서는 "
        "면책이 없다는 것을 못 담음",
        proposal="exemption{days, from: first_contract | reinstatement, on_renewal: 0}, reduction.from",
        patterns=[r"갱신계약의암보장개시일은갱신일", r"최초계약의계약일부터\d+년이내"],
    ),
]
CONCEPT_BY_CODE = {c.code: c for c in CONCEPTS}


class Unit(BaseModel):
    """원문 위치 하나 (항 또는 호)."""

    bundle: str
    part: str
    section: str | None
    article: str
    title: str | None = None
    paragraph: int | None = None
    item: str | None = None
    text: str

    @property
    def label(self) -> str:
        s = self.article + (f" {circled(self.paragraph)}" if self.paragraph else "")
        return s + (f" {self.item}." if self.item else "")


class GapHit(BaseModel):
    unit: Unit
    snippet: str
    bundles: list[str]  # 같은 공통 조가 여러 묶음에 들어갈 때 모두


class GapFinding(BaseModel):
    concept: Concept
    hits: list[GapHit]


class BundleCoverage(BaseModel):
    bundle: str
    units: int  # 안내 문장('다음과 같습니다')을 뺀 항·호 수
    cited: int


class Uncovered(BaseModel):
    """어떤 규칙·보상 제외도 인용하지 않은 항·호와 빠진 이유."""

    unit: Unit
    concepts: list[str]  # 이 항·호에서 찾은 개념 갭 코드
    reason: Literal["schema_gap", "uncited_value", "extraction_gap"]
    # schema_gap: 스키마에 자리가 없는 개념이 있음 → 스키마 확장 필요
    # uncited_value: 이 항·호의 숫자(180일 등)가 데이터에 이미 있는데 근거로 인용하지 않음 → 근거 보완
    # extraction_gap: 지금 스키마로 담을 수 있는데 추출(데이터)에서 빠짐 → 데이터 보완
    values: list[str] = Field(default_factory=list)  # uncited_value 일 때 데이터에 있는 값


class Unfilled(BaseModel):
    concept: str
    message: str
    unit: Unit


class GapReport(BaseModel):
    bundles: list[str]
    findings: list[GapFinding]  # 개념 갭 (원문에 나온 것만)
    coverage: list[BundleCoverage]  # 사고보장 데이터가 있는 묶음의 인용 비율
    uncovered: list[Uncovered]  # 어떤 항목도 인용하지 않은 항·호와 이유
    unfilled: list[Unfilled]


# ---------------------------------------------------------------- 원문 단위


def _item_text(it: Item) -> str:
    return " ".join([it.text, *(_item_text(c) for c in it.children)])


def units_of(bundle: Bundle) -> list[Unit]:
    """묶음의 조를 항·호 단위로 나눔. 호가 있는 항은 머리글(항 본문)과 호를 따로."""
    out: list[Unit] = []
    for a in bundle.articles:
        base = {
            "bundle": bundle.key,
            "part": bundle.part_title,
            "section": a.section,
            "article": a.label,
            "title": a.title,
        }
        for p in a.paragraphs:
            if p.text.strip():
                out.append(Unit(**base, paragraph=p.number, text=p.text))
            for it in p.items:
                out.append(Unit(**base, paragraph=p.number, item=it.label, text=_item_text(it)))
    return out


_LEAD = re.compile(r"다음(?:과같|의|에|은|중어느)")
# '제2조의3(…)에서 정한 초기유방암(을 말합니다)' 처럼 다른 조를 가리키기만 하는 문장
_POINTER = re.compile(
    r"^(?:이계약에있어서.{1,20}(?:이라함은|은))?제\d+조(?:의\d+)?\([^)]*\)에서정한.{1,20}$"
)


def is_lead(u: Unit) -> bool:
    """'회사는 다음의 … 보상하지 않습니다' 처럼 아래 호를 이끄는 짧은 안내 문장 (담을 내용 없음)."""
    sq = squash(u.text)
    if _POINTER.match(sq):
        return True
    return u.item is None and len(sq) < 80 and bool(_LEAD.search(sq))


def _is_exclusion_article(a: Article) -> bool:
    return "보상하지" in (a.title or "")


def _snippet(text: str, pattern: re.Pattern, width: int = 70) -> str:
    """정규식이 맞은 부분 근처 원문 (공백 정규화 전 원문 기준)."""
    flat = " ".join(text.split())
    sq, idx = "", []
    for i, ch in enumerate(flat):
        if squash(ch):
            sq += ch
            idx.append(i)
    m = pattern.search(sq)
    if not m:
        return flat[:width]
    a, b = idx[m.start()], idx[m.end() - 1] + 1
    start = max(0, a - (width - (b - a)) // 2)
    s = flat[start : start + max(width, b - a + 10)]
    return ("…" if start else "") + s + ("…" if start + len(s) < len(flat) else "")


# ---------------------------------------------------------------- 분석


def find_concepts(bundles: list[Bundle]) -> list[GapFinding]:
    compiled = {c.code: [re.compile(p) for p in c.patterns] for c in CONCEPTS}
    seen: dict[tuple, GapHit] = {}
    hits: dict[str, list[GapHit]] = {c.code: [] for c in CONCEPTS}
    for b in bundles:
        excl_articles = {a.label for a in b.articles if _is_exclusion_article(a)}
        for u in units_of(b):
            sq = squash(u.text)
            for c in CONCEPTS:
                if c.exclusion_only and u.article not in excl_articles:
                    continue
                pat = next((p for p in compiled[c.code] if p.search(sq)), None)
                if pat is None:
                    continue
                key = (c.code, u.part, u.section, u.article, u.paragraph, u.item)
                if key in seen:  # 공통 조(제5조 등)는 묶음마다 들어가므로 한 번만
                    seen[key].bundles.append(b.key)
                    continue
                hit = GapHit(unit=u, snippet=_snippet(u.text, pat), bundles=[b.key])
                seen[key] = hit
                hits[c.code].append(hit)
    return [GapFinding(concept=c, hits=hits[c.code]) for c in CONCEPTS if hits[c.code]]


def _quotes_for(product: Product, bundle: Bundle) -> list[str]:
    quotes = []
    items = [*product.rules(), *product.exclusions()]
    for x in items:
        srcs = [x.source, *getattr(x, "extra_sources", [])]
        for s in srcs:
            if s.part == bundle.part_title and s.section in (None, bundle.section) and s.quote:
                quotes.append(squash(s.quote))
    return quotes


def _cited_appendices(product: Product, bundle: Bundle) -> set[str]:
    """이 묶음의 규칙·담보코드가 근거로 든 별표 번호 ('별표 2' → '2')."""
    srcs = [s for r in product.rules() for s in [r.source, *r.extra_sources]]
    srcs += [cc.source for cc in product.coverage_codes if cc.source]
    return {
        n
        for s in srcs
        if s.part == bundle.part_title and s.appendix
        for n in re.findall(r"\d+", s.appendix)[:1]
    }


def _has_data(product: Product, bundle: Bundle) -> bool:
    for x in [*product.rules(), *product.exclusions()]:
        if x.source.part == bundle.part_title and x.source.section == bundle.section:
            return True
    return False


def _unit_key(u: Unit) -> tuple:
    return (u.part, u.section, u.article, u.paragraph, u.item)


def citation_coverage(
    product: Product, bundles: list[Bundle], findings: list[GapFinding]
) -> tuple[list[BundleCoverage], list[Uncovered]]:
    concepts_at: dict[tuple, list[str]] = {}
    for f in findings:
        for h in f.hits:
            concepts_at.setdefault(_unit_key(h.unit), []).append(f.concept.code)
    coverage, uncovered = [], []
    for b in bundles:
        if not _has_data(product, b):
            continue
        quotes = _quotes_for(product, b)
        values = [
            (kind, v, label)
            for r in product.rules()
            if r.source.part == b.part_title and r.source.section == b.section
            for kind, v, label in expected_numbers(r)
        ]
        units = [u for u in units_of(b) if not is_lead(u)]
        appendices = _cited_appendices(product, b)
        cited = 0
        for u in units:
            sq = squash(u.text)
            # 인용문이 이 항·호에 있거나, 이 항·호가 가리키는 별표를 데이터가 근거로 씀 (분류표 → 담보코드)
            if any(q and q in sq for q in quotes) or (
                appendices and set(re.findall(r"별표(\d+)", sq)) & appendices
            ):
                cited += 1
                continue
            codes = concepts_at.get(_unit_key(u), [])
            if any(CONCEPT_BY_CODE[c].kind != "partial" for c in codes):
                uncovered.append(Uncovered(unit=u, concepts=codes, reason="schema_gap"))
                continue
            found = numbers_in(u.text)
            hit = sorted({f"{label} {v:g}" for kind, v, label in values if v in found[kind]})
            uncovered.append(
                Uncovered(
                    unit=u,
                    concepts=codes,
                    reason="uncited_value" if hit else "extraction_gap",
                    values=hit,
                )
            )
        coverage.append(BundleCoverage(bundle=b.key, units=len(units), cited=cited))
    return coverage, uncovered


def unfilled_fields(
    product: Product, bundles: list[Bundle], findings: list[GapFinding]
) -> list[Unfilled]:
    """스키마에 필드가 있는데 데이터에서 빈 것 (데이터가 있는 묶음만)."""
    out: list[Unfilled] = []
    with_data = {b.key for b in bundles if _has_data(product, b)}
    by_code = {f.concept.code: f for f in findings}

    kcd_filled = any(k.kcd_version for cc in product.coverage_codes for k in cc.kcd)

    def hits(code: str) -> list[GapHit]:
        return by_code[code].hits if code in by_code else []

    for h in hits("KCD_VERSION"):
        if set(h.bundles) & with_data and product.coverage_codes and not kcd_filled:
            out.append(
                Unfilled(
                    concept="KCD_VERSION",
                    unit=h.unit,
                    message="원문에 KCD 차수가 있는데 담보코드의 kcd_version 이 비어 있음",
                )
            )

    counted = any(r.conditions.limit and r.conditions.limit.count for r in product.rules())
    for h in hits("ANNUAL_COUNT"):
        if set(h.bundles) & with_data and not counted:
            out.append(
                Unfilled(
                    concept="ANNUAL_COUNT",
                    unit=h.unit,
                    message="원문에 횟수 한도가 있는데 Limit.count 가 비어 있음",
                )
            )
    return out


def analyze_gaps(doc: TermsDocument, product: Product | None = None) -> GapReport:
    bundles = build_bundles(doc)
    findings = find_concepts(bundles)
    coverage, uncovered, unfilled = [], [], []
    if product is not None:
        coverage, uncovered = citation_coverage(product, bundles, findings)
        unfilled = unfilled_fields(product, bundles, findings)
    return GapReport(
        bundles=[b.key for b in bundles],
        findings=findings,
        coverage=coverage,
        uncovered=uncovered,
        unfilled=unfilled,
    )


def format_report(report: GapReport) -> str:
    lines = [f"스키마 갭 분석 · 묶음 {len(report.bundles)}개", ""]
    lines.append(
        f"[1] 개념 갭 {len(report.findings)}종 (원문에 있는데 스키마에 자리가 없거나 부족)"
    )
    for kind in ("structure", "field", "partial"):
        for f in [f for f in report.findings if f.concept.kind == kind]:
            c = f.concept
            lines.append(f"  · [{KIND_LABEL[kind]}] {c.name} ({c.code}) — 원문 {len(f.hits)}곳")
            lines.append(f"      지금: {c.now}")
            lines.append(f"      제안: {c.proposal}")
            for h in f.hits[:3]:
                where = h.unit.part.split("(")[0] + (
                    f" 《{h.unit.section}》" if h.unit.section else ""
                )
                lines.append(f"      - {where} {h.unit.label}: {h.snippet}")
            if len(f.hits) > 3:
                lines.append(f"      - … 외 {len(f.hits) - 3}곳")
    if report.coverage:
        lines += ["", "[2] 근거 없는 원문 (사고보장 데이터가 있는 묶음)"]
        for cov in report.coverage:
            lines.append(
                f"  · {cov.bundle}: 항·호 {cov.units}개 중 {cov.cited}개 인용 "
                f"({cov.cited / cov.units:.0%})"
            )
        for reason, title in (
            ("schema_gap", "스키마에 자리가 없어 빠짐 → 스키마 확장"),
            ("uncited_value", "값은 데이터에 있는데 근거로 인용 안 됨 → 근거(extra_sources) 보완"),
            ("extraction_gap", "스키마로 담을 수 있는데 데이터에서 빠짐 → 추출·정답 보완"),
        ):
            rows = [x for x in report.uncovered if x.reason == reason]
            lines.append(f"    {title}: {len(rows)}곳")
            for x in rows:
                codes = f" [{', '.join(x.concepts or x.values)}]" if x.concepts or x.values else ""
                lines.append(f"      - {x.unit.label}{codes}: {' '.join(x.unit.text.split())[:60]}")
    if report.unfilled:
        lines += ["", "[3] 빈 필드 (스키마에 필드는 있는데 데이터에 값이 없음)"]
        for x in report.unfilled:
            lines.append(f"  · {x.concept} {x.unit.label}: {x.message}")
    return "\n".join(lines)
