import { useState } from 'react'
import { moneyValue, treatmentNames, type Enrollment, type ReviewItem } from './privacy'
import { estimateOutpatient, outpatientPolicy as policy } from './indemnity-outpatient'
import type { calculationInputs } from './supplemental'

const won = (amount: number) => `${amount.toLocaleString('ko-KR')}원`

export default function OutpatientEstimate({ items, inputs, reviewed, enrollment, onOpenSource }: {
  items: ReviewItem[]
  inputs: ReturnType<typeof calculationInputs>
  reviewed: boolean
  enrollment: Enrollment
  onOpenSource: (index: number) => void
}) {
  const [facility, setFacility] = useState<'' | keyof typeof policy.minimum>('')
  const [annual, setAnnual] = useState('')
  const [remainingText, setRemainingText] = useState('')
  const [scope, setScope] = useState('')
  const [fundByReceipt, setFundByReceipt] = useState<Record<string, string>>({})
  const plan = policy.limits.find(limit => String(limit.annual) === annual)
  const remaining = moneyValue(remainingText)
  const covered = items.flatMap((item, index) => item.benefit === 'covered'
    ? [{ item, index, copay: moneyValue(item.patient) ?? 0, total: moneyValue(item.total) ?? 0 }] : [])
  const hospitalCopay = covered.reduce((sum, row) => sum + row.copay, 0)
  const hospitalFund = covered.reduce((sum, row) => sum + row.total - row.copay, 0)
  const pharmacy = inputs.pharmacy.filter(receipt => receipt.status === 'counted' && receipt.covered.value > 0)
  const pharmacyCopay = pharmacy.reduce((sum, receipt) => sum + receipt.covered.value, 0)
  const pharmacyFunds = pharmacy.map(receipt => moneyValue(fundByReceipt[receipt.id] ?? ''))
  const pharmacyFund = pharmacyFunds.reduce<number>((sum, value) => sum + (value ?? 0), 0)
  const eligible = hospitalCopay + pharmacyCopay
  const issues: string[] = []
  if (inputs.verifiedExpenseWon === null) issues.push('영수증과 세부내역서 합계, 추가 서류의 납입액과 약제비 관계를 대조해 주세요.')
  if (!reviewed) issues.push('치료 항목 검토에서 원본 대조 완료를 체크해 주세요.')
  if (enrollment === 'unknown') issues.push('가상 계약의 질병급여 담보 가입 상태를 확인해 주세요.')
  if (items.some(item => item.benefit === 'unknown')) issues.push('급여 구분이 미확인인 치료 항목을 확인해 주세요.')
  const excluded = enrollment === 'not_enrolled' || scope === 'excluded' || (eligible === 0 && issues.length === 0)
  if (!excluded) {
    if (scope !== 'included') issues.push('질병 통원 1회와 급여 일부본인부담 범위를 확인해 주세요.')
    if (covered.some(row => row.copay > 0 && row.copay === row.total)) {
      issues.push('공단부담금이 없는 급여 행은 전액본인부담 여부와 적용 조항을 별도로 확인해 주세요.')
    }
    if (!facility) issues.push('진료비 영수증의 의료기관 유형을 선택해 주세요.')
    if (!plan) issues.push('보험증권의 질병급여 가입금액을 선택해 주세요.')
    if (remaining === null || (plan && remaining > plan.annual)) {
      issues.push('보험사 지급 내역에서 연간 잔여 한도를 확인해 주세요. 가입금액 이하의 원 단위로 입력하세요.')
    }
    if (pharmacyFunds.some(value => value === null || value === 0)) {
      issues.push('별도 납부 약제비의 급여 공단부담금을 약제비 영수증에서 확인해 주세요.')
    }
  }
  const result = !excluded && issues.length === 0 && facility && plan && remaining !== null
    ? estimateOutpatient({
      eligible, copay: eligible, publicFund: hospitalFund + pharmacyFund,
      minimum: policy.minimum[facility], visitLimit: plan.visit, remaining,
    }) : null
  const excludedReason = enrollment === 'not_enrolled' ? '질병급여 담보 미가입'
    : '이 가상 사례에서 질병급여 통원 보장대상 비용이 없다고 확인했습니다.'
  const payableLabel = result?.payable === 0
    ? result.beforeLimits === 0 ? '공제 후 지급액 0원' : '잔여 한도 적용 후 지급액 0원'
    : '가상 예상 보험금'

  return <section id="outpatient-estimate" tabIndex={-1} className="wide-panel outpatient-estimate" aria-labelledby="outpatient-heading">
    <div className="section-top"><div>
      <h2 id="outpatient-heading">실손 급여 통원 계산</h2>
      <p>가상 사례 시뮬레이션 · {policy.title} 계약전환용 · 질병급여 통원 1회</p>
    </div><span className="status status-amber">검토 전 산식</span></div>
    <p>같은 통원 건의 급여 항목을 합산합니다. 치료 목록의 조회 체크박스는 서버 조회에만 적용됩니다. 계산 조건과 금액은 기기 안에서 처리합니다.</p>
    <div className="outpatient-fields">
      <label>질병 통원 보장 범위
        <select value={scope} onChange={event => setScope(event.target.value)}>
          <option value="">확인 필요</option>
          <option value="included">급여 일부본인부담 전액 보장대상 확인</option>
          <option value="excluded">보장대상 비용 없음 확인</option>
        </select>
        <small>동일 질병 통원 1회와 연계 처방, 단일 실손 계약을 가정합니다. 일부 제외·환급·전액본인부담이 있으면 별도 검토가 필요합니다.</small>
      </label>
      <label>의료기관 유형
        <select value={facility} onChange={event => setFacility(event.target.value === 'clinic' ? 'clinic'
          : event.target.value === 'general' ? 'general' : '')}>
          <option value="">영수증에서 확인</option>
          <option value="clinic">병·의원 등 · 최소 1만원</option>
          <option value="general">종합·상급종합병원 · 최소 2만원</option>
        </select>
      </label>
      <label>질병급여 가입금액
        <select value={annual} onChange={event => { setAnnual(event.target.value); setRemainingText('') }}>
          <option value="">보험증권에서 확인</option>
          {policy.limits.map(limit => <option key={limit.annual} value={limit.annual}>
            {won(limit.annual)} · 통원 1회 {won(limit.visit)}
          </option>)}
        </select>
      </label>
      <label>연간 잔여 한도 (원)
        <input inputMode="numeric" maxLength={9} value={remainingText} placeholder="보험사 지급 내역에서 확인"
          onChange={event => setRemainingText(event.target.value)}/>
      </label>
      {pharmacy.map(receipt => <label key={receipt.id}>약제비 급여 공단부담금 (원) · {receipt.id}
        <input inputMode="numeric" maxLength={9} value={fundByReceipt[receipt.id] ?? ''}
          placeholder="약제비 영수증에서 확인"
          onChange={event => setFundByReceipt(previous => ({ ...previous, [receipt.id]: event.target.value }))}/>
      </label>)}
    </div>
    <div className="outpatient-result" role="status">
      {excluded && (enrollment === 'not_enrolled' || issues.length === 0) ? <>
        <h3>보장 제외</h3><p>{excludedReason}</p>
      </> : result && facility && plan && remaining !== null ? <>
        <h3>{payableLabel}</h3>
        <strong className="outpatient-amount">{won(result.payable)}</strong>
        <dl>
          <div><dt>보장대상 의료비</dt><dd>{won(eligible)} · 병원 {won(hospitalCopay)} + 약국 {won(pharmacyCopay)}</dd></div>
          <div><dt>건강보험 본인부담률</dt><dd>약 {(result.rate * 100).toFixed(2)}% · {won(eligible)} ÷ {won(eligible + hospitalFund + pharmacyFund)}</dd></div>
          <div><dt>급여 공단부담금</dt><dd>{won(hospitalFund + pharmacyFund)} · 병원 {won(hospitalFund)} + 약국 {won(pharmacyFund)}</dd></div>
          <div><dt>공제액 · 세 기준 중 최댓값</dt><dd>{won(result.deduction)} · 최소 {won(policy.minimum[facility])} / 20% {won(result.percentDeduction)} / 건보 연동 {won(result.linkedDeduction)}</dd></div>
          <div><dt>공제 후 금액</dt><dd>{won(result.beforeLimits)}</dd></div>
          <div><dt>적용 한도</dt><dd>통원 1회 {won(plan.visit)} · 연간 잔여 {won(remaining)}</dd></div>
        </dl>
        <p>시뮬레이션은 원 미만 지급액을 절사합니다.</p>
      </> : <>
        <h3>계산 보류</h3>
        <ul>{issues.map(issue => <li key={issue}>{issue}</li>)}</ul>
      </>}
    </div>
    <details>
      <summary>입력 서류와 적용 약관</summary>
      <ul>{covered.map(({ item, index, copay }) => <li key={index}>
        {item.kind === 'unknown' ? '급여 항목' : treatmentNames[item.kind]} · {won(copay)}{' '}
        <button className="outline" type="button" onClick={() => onOpenSource(index)}>계산 근거 원본 · {item.source.page}쪽</button>
      </li>)}</ul>
      {pharmacy.length > 0 && <a href="#additional-claim-documents">약제비 영수증 추출 근거 보기</a>}
      <div className="fixed-policy-links">
        <a href={`${policy.url}#page=${policy.benefitsPage}`} target="_blank" rel="noreferrer">질병급여 제3조 · PDF {policy.benefitsPage}쪽부터</a>
        <a href={`${policy.url}#page=${policy.limitsPage}`} target="_blank" rel="noreferrer">가입금액과 회당 한도 · PDF {policy.limitsPage}쪽</a>
        <a href={`${policy.url}#page=${policy.limitClausePage}`} target="_blank" rel="noreferrer">제6조 보험가입금액 한도 · PDF {policy.limitClausePage}쪽부터</a>
      </div>
    </details>
  </section>
}
