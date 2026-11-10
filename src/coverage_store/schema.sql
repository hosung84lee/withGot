-- 사고보장 데이터 저장 테이블 (SQLite). 설계: docs/coverage_tables.md
--
-- 업무 구조를 그대로 따름: 상품 → 보장 → 위험률 → 위험유형(지급 규칙) → 참조조건·급부·공제·특수조건·분할,
-- 보상 제외, 담보코드 → KCD 범위, 그리고 모든 항목의 약관 근거(source_ref).
-- 규칙 id 는 상품마다 같은 모양(p0/질병급여형/…)이라, 모든 키에 product_id 를 넣어 여러 상품(개정 전후)을
-- 한 DB 에 함께 저장합니다.

CREATE TABLE IF NOT EXISTS product (
    product_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    insurer     TEXT NOT NULL DEFAULT '',
    version     TEXT NOT NULL DEFAULT ''
);

-- 보장 = 약관 단위 (주계약 / 특약)
CREATE TABLE IF NOT EXISTS coverage (
    product_id  TEXT NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    coverage_id TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('main', 'rider')),
    PRIMARY KEY (product_id, coverage_id)
);

-- 담보코드 = KCD 코드 묶음
CREATE TABLE IF NOT EXISTS coverage_code (
    product_id  TEXT NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    code        TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    name        TEXT NOT NULL,
    PRIMARY KEY (product_id, code)
);

CREATE TABLE IF NOT EXISTS kcd_range (
    product_id  TEXT NOT NULL,
    code        TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    kcd_start   TEXT NOT NULL,
    kcd_end     TEXT NOT NULL,
    level       INTEGER,
    kcd_version INTEGER,
    valid_from  TEXT,
    valid_to    TEXT,
    PRIMARY KEY (product_id, code, seq),
    FOREIGN KEY (product_id, code) REFERENCES coverage_code (product_id, code) ON DELETE CASCADE
);

-- 위험률 = 보장종목 × 청구사유 (× 담보코드)
CREATE TABLE IF NOT EXISTS risk (
    product_id    TEXT NOT NULL,
    risk_id       TEXT NOT NULL,
    coverage_id   TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    section       TEXT,
    claim_reason  TEXT NOT NULL,
    coverage_code TEXT,
    PRIMARY KEY (product_id, risk_id),
    FOREIGN KEY (product_id, coverage_id) REFERENCES coverage (product_id, coverage_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id, coverage_code) REFERENCES coverage_code (product_id, code)
);

-- 위험유형 = 지급 규칙 하나
CREATE TABLE IF NOT EXISTS benefit_rule (
    product_id    TEXT NOT NULL,
    rule_id       TEXT NOT NULL,
    risk_id       TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    name          TEXT NOT NULL,
    insured_role  TEXT NOT NULL,
    policy_status TEXT,
    facility      TEXT,
    occurrence    TEXT CHECK (occurrence IN ('first', 'each')),
    status        TEXT NOT NULL CHECK (status IN ('confirmed', 'needs_review')),
    PRIMARY KEY (product_id, rule_id),
    FOREIGN KEY (product_id, risk_id) REFERENCES risk (product_id, risk_id) ON DELETE CASCADE
);

-- 참조조건 항목 사전 (항목코드 → 이름·단위)
CREATE TABLE IF NOT EXISTS condition_item (
    item_code   TEXT PRIMARY KEY,
    item_name   TEXT NOT NULL,
    unit        TEXT NOT NULL
);

-- 참조조건 = 규칙의 기간·한도 값 (항목코드 · 값 한 줄씩)
CREATE TABLE IF NOT EXISTS rule_condition (
    product_id  TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    item_code   TEXT NOT NULL REFERENCES condition_item (item_code),
    value       REAL NOT NULL,
    selectable  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (product_id, rule_id, seq),
    FOREIGN KEY (product_id, rule_id) REFERENCES benefit_rule (product_id, rule_id) ON DELETE CASCADE
);

-- 급부 = 지급 방식 (규칙당 하나)
CREATE TABLE IF NOT EXISTS benefit (
    product_id       TEXT NOT NULL,
    rule_id          TEXT NOT NULL,
    benefit_type     TEXT NOT NULL CHECK (benefit_type IN ('rate', 'fixed', 'actual_cost')),
    base             TEXT NOT NULL,
    cost_type        TEXT,
    ratio_num        REAL,
    ratio_den        REAL,
    fixed_amount     INTEGER,
    min_amount       INTEGER,
    max_amount       INTEGER,
    copay_cap_annual INTEGER,
    deductible_pick  TEXT CHECK (deductible_pick IN ('max', 'min', 'sum')),
    PRIMARY KEY (product_id, rule_id),
    FOREIGN KEY (product_id, rule_id) REFERENCES benefit_rule (product_id, rule_id) ON DELETE CASCADE
);

-- 공제금액 기준 (정액 · 비율 · 본인부담률). benefit.deductible_pick 으로 큰 금액 등을 고름
CREATE TABLE IF NOT EXISTS deductible (
    product_id  TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('AMOUNT', 'RATIO', 'COPAY_RATE')),
    amount      INTEGER,
    ratio_num   REAL,
    ratio_den   REAL,
    PRIMARY KEY (product_id, rule_id, seq),
    FOREIGN KEY (product_id, rule_id) REFERENCES benefit_rule (product_id, rule_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS special_condition (
    product_id      TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    type            TEXT NOT NULL,
    related_rule_id TEXT,
    description     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (product_id, rule_id, seq),
    FOREIGN KEY (product_id, rule_id) REFERENCES benefit_rule (product_id, rule_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS installment (
    product_id   TEXT NOT NULL,
    rule_id      TEXT NOT NULL,
    count        INTEGER NOT NULL,
    cycle_months INTEGER NOT NULL,
    PRIMARY KEY (product_id, rule_id),
    FOREIGN KEY (product_id, rule_id) REFERENCES benefit_rule (product_id, rule_id) ON DELETE CASCADE
);

-- 보상하지 않는 사항
CREATE TABLE IF NOT EXISTS exclusion (
    product_id    TEXT NOT NULL,
    exclusion_id  TEXT NOT NULL,
    coverage_id   TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    section       TEXT,
    kind          TEXT NOT NULL CHECK (kind IN ('kcd', 'cost_item', 'cause')),
    description   TEXT NOT NULL,
    coverage_code TEXT,
    exception     TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL CHECK (status IN ('confirmed', 'needs_review')),
    PRIMARY KEY (product_id, exclusion_id),
    FOREIGN KEY (product_id, coverage_id) REFERENCES coverage (product_id, coverage_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id, coverage_code) REFERENCES coverage_code (product_id, code)
);

-- 약관 근거. target_type 이 가리키는 항목(규칙·보상 제외·보장·담보코드)의 조·항·인용문
CREATE TABLE IF NOT EXISTS source_ref (
    product_id  TEXT NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('rule', 'exclusion', 'coverage', 'coverage_code')),
    target_id   TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('primary', 'extra')),
    part        TEXT NOT NULL,
    section     TEXT,
    article     TEXT,
    paragraph   INTEGER,
    item        INTEGER,
    appendix    TEXT,
    quote       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (product_id, target_type, target_id, seq)
);
