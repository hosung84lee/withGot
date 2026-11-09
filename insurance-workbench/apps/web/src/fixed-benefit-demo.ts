import policies from './fixed-benefit-policies.json'

const cancerPolicy = policies.find(policy => policy.id === 'lina-health-cancer-b00070001')!
const lifePolicy = policies.find(policy => policy.id === 'hanwha-h-whole-life-2209-a01-a17-20251003')!

type CommonFacts = {
  contractDate: string
  eventDate: string
  sumInsured: number
  contract: 'active' | 'inactive' | 'review'
  evidence: 'confirmed' | 'missing' | 'exception'
}
type CancerFacts = CommonFacts & {
  category: 'cancer'
  benefitId: 'malignant' | 'other-skin' | 'in-situ' | 'borderline'
  firstDiagnosis: boolean | null
}
type LifeFacts = CommonFacts & {
  category: 'whole_life'
  reserve: number
  premiumsPaid: number
  additionalPremiums: number
  withdrawals: number
}
export type DemoFacts = CancerFacts | LifeFacts

const cancerBase: CancerFacts = {
  category: 'cancer', benefitId: 'malignant', firstDiagnosis: true,
  contractDate: '2024-01-01', eventDate: '2026-01-01', sumInsured: 10_000_000,
  contract: 'active', evidence: 'confirmed',
}
const lifeBase: LifeFacts = {
  category: 'whole_life', contractDate: '2020-06-15', eventDate: '2022-06-15',
  sumInsured: 100_000_000, reserve: 50_000_000, premiumsPaid: 30_000_000,
  additionalPremiums: 0, withdrawals: 0, contract: 'active', evidence: 'confirmed',
}
function cancer(id: string, title: string, changes: Partial<CancerFacts> = {}) {
  return { id, title, facts: { ...cancerBase, ...changes } }
}
function life(id: string, title: string, changes: Partial<LifeFacts> = {}) {
  return { id, title, facts: { ...lifeBase, ...changes } }
}

export const demoCases = [
  cancer('waiting-last', '일반암 · 대기기간 마지막 날', { eventDate: '2024-03-30' }),
  cancer('waiting-first', '일반암 · 보장개시 첫날', { eventDate: '2024-03-31' }),
  cancer('reduction-last', '일반암 · 감액 마지막 날', { eventDate: '2025-12-31' }),
  cancer('reduction-end', '일반암 · 두 번째 계약해당일'),
  cancer('skin', '기타피부암 · 계약 1개월 내 진단', { eventDate: '2024-01-25', benefitId: 'other-skin' }),
  cancer('in-situ', '상피내암 · 최초 진단', { benefitId: 'in-situ' }),
  cancer('borderline', '경계성종양 · 최초 진단', { benefitId: 'borderline' }),
  cancer('repeat', '일반암 · 해당 급부의 재진단', { firstDiagnosis: false }),
  cancer('unknown-history', '일반암 · 최초 진단 이력 미확인', { firstDiagnosis: null }),
  cancer('missing-pathology', '일반암 · 진단 근거 미확인', { evidence: 'missing' }),
  cancer('inactive', '일반암 · 진단 시 계약 효력 없음', { contract: 'inactive' }),
  cancer('leap-anniversary', '일반암 · 윤일 계약의 해당일 확인', { contractDate: '2024-02-29', eventDate: '2026-02-28' }),
  life('before-step', '종신 · 첫 체증 전날', { eventDate: '2022-06-14' }),
  life('first-step', '종신 · 첫 체증 당일'),
  life('step-cap', '종신 · 체증 5회 상한 및 추가납입·인출', { eventDate: '2030-06-15', additionalPremiums: 8_000_000, withdrawals: 3_000_000 }),
  life('reserve-wins', '종신 · 계약자적립액 기준이 가장 큼', { reserve: 150_000_000 }),
  life('premiums-win', '종신 · 납입보험료 기준이 가장 큼', { premiumsPaid: 150_000_000 }),
  life('death-evidence', '종신 · 사망 증빙 미확인', { evidence: 'missing' }),
  life('death-exception', '종신 · 지급 제외 예외 검토', { evidence: 'exception' }),
  life('contract-type', '종신 · 계약 유형 미확인', { contract: 'review' }),
]

type Detail = { label: string; value: string }
type Outcome =
  | { status: 'estimated'; message: string; amount: number; details: Detail[] }
  | { status: 'outside' | 'review'; message: string; details: Detail[] }

export const formatWon = (value: number) => `${value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })}원`
const percentOf = (value: number, percent: number) => (value * percent) / 100
const hold = (message: string, details: Detail[] = []): Outcome => ({ status: 'review', message, details })
const outside = (message: string, details: Detail[] = []): Outcome => ({ status: 'outside', message, details })

function dateAfterDays(date: string, days: number) {
  const time = new Date(`${date}T00:00:00Z`)
  time.setUTCDate(time.getUTCDate() + days)
  return time.toISOString().slice(0, 10)
}

function anniversary(date: string, years: number) {
  return `${Number(date.slice(0, 4)) + years}${date.slice(4)}`
}

function cancerOutcome(facts: CancerFacts): Outcome {
  const benefit = cancerPolicy.benefits.find(entry => entry.id === facts.benefitId)
  if (!benefit || !('percent' in benefit.amount)) return hold('해당 급부의 지급 기준을 확인해 주세요.')
  const details: Detail[] = [{ label: '약관상 급부', value: benefit.name }]
  const waitingDays = 'waitingPeriod' in benefit.trigger ? benefit.trigger.waitingPeriod?.inclusiveDays : undefined
  if (waitingDays !== undefined) {
    const start = dateAfterDays(facts.contractDate, waitingDays)
    details.push({ label: '암보장개시일', value: start })
    if (facts.eventDate < start) {
      return outside('암보장개시일 전 진단입니다. 계약 무효와 납입보험료 반환은 제4조 검토 대상입니다.', details)
    }
  }
  if (facts.firstDiagnosis === null) return hold('해당 급부의 최초 진단 여부를 확인해 주세요.', details)
  if (!facts.firstDiagnosis) return outside('해당 급부의 최초 진단에 해당하지 않습니다.', details)

  const rate = benefit.amount.percent
  details.push({ label: '가입금액 대비 기본 지급률', value: `${rate}%` })
  const reduction = 'reduction' in benefit.amount ? benefit.amount.reduction : undefined
  let appliedRate = rate
  if (reduction) {
    if (facts.contractDate.endsWith('-02-29')) {
      return hold('윤일 계약의 두 번째 계약해당일을 보험증권에서 확인해 주세요.', details)
    }
    const second = anniversary(facts.contractDate, 2)
    details.push({ label: '두 번째 계약해당일', value: second })
    if (facts.eventDate < second) appliedRate = percentOf(rate, reduction.percentOfBenefit)
    details.push({ label: '감액', value: appliedRate === rate ? '미적용' : `기본 급부의 ${reduction.percentOfBenefit}% 지급` })
  }
  return {
    status: 'estimated', message: '가상 진단 사례의 계산 예시입니다.',
    amount: percentOf(facts.sumInsured, appliedRate), details,
  }
}

function lifeOutcome(facts: LifeFacts): Outcome {
  const amountRule = lifePolicy.benefits[0].amount
  if (!('referenceDeathBenefit' in amountRule)) return hold('사망보험금의 지급 기준을 확인해 주세요.')
  const { reserveFactorPercent, referenceDeathBenefit } = amountRule
  const { stepStartContractAnniversary, firstStepAtStart, linearIncreasePercentPerStep, maximumSteps } = referenceDeathBenefit
  if (facts.contractDate.endsWith('-02-29')) {
    return hold('윤일 계약의 체증 계약해당일을 보험증권에서 확인해 주세요.')
  }
  let steps = 0
  for (let index = 0; index < maximumSteps; index++) {
    if (facts.eventDate >= anniversary(facts.contractDate, stepStartContractAnniversary + index)) {
      steps = Math.min(maximumSteps, firstStepAtStart + index)
    }
  }
  const adjusted = percentOf(facts.sumInsured, 100 + linearIncreasePercentPerStep * steps)
    + facts.additionalPremiums - facts.withdrawals
  if (adjusted < 0) return hold('기준사망보험금 조정에 사용한 추가납입과 인출 이력을 확인해 주세요.')
  const candidates = [
    { label: '조정한 기준사망보험금', value: adjusted },
    { label: `계약자적립액의 ${reserveFactorPercent}%`, value: percentOf(facts.reserve, reserveFactorPercent) },
    { label: '약관상 납입보험료', value: facts.premiumsPaid },
  ]
  const amount = Math.max(...candidates.map(candidate => candidate.value))
  return {
    status: 'estimated', message: '세 가지 약관 기준 중 가장 큰 금액입니다.', amount,
    details: [
      { label: '적용 체증', value: `${steps}회 · 가입금액의 ${steps * linearIncreasePercentPerStep}% 가산` },
      ...candidates.map(candidate => ({
        label: candidate.value === amount ? `${candidate.label} (최댓값)` : candidate.label,
        value: formatWon(candidate.value),
      })),
    ],
  }
}

export function simulateFixedBenefit(facts: DemoFacts): Outcome {
  if (facts.contract === 'review') return hold('사건 시점의 계약 유형과 효력을 확인해 주세요.')
  if (facts.evidence === 'missing') {
    return hold(facts.category === 'cancer' ? '진단확정 근거를 확인해 주세요.' : '사망진단서 등 사망 증빙을 확인해 주세요.')
  }
  if (facts.evidence === 'exception') return hold('지급 제외 사유와 약관상 예외를 검토해 주세요.')
  if (facts.contract === 'inactive' || facts.eventDate < facts.contractDate) {
    return outside('사건 발생일이 가상 계약의 유효한 보험기간에 해당하지 않습니다.')
  }
  return facts.category === 'cancer' ? cancerOutcome(facts) : lifeOutcome(facts)
}

export function demoPolicy(facts: DemoFacts) {
  return facts.category === 'cancer' ? cancerPolicy : lifePolicy
}
