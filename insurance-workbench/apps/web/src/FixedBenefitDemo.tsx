import { useState } from 'react'
import { demoCases, demoPolicy, formatWon, simulateFixedBenefit } from './fixed-benefit-demo'
import './fixed-policy.css'

const labels = {
  estimated: '가상 예상액',
  outside: '해당 급부 지급 조건 미충족',
  review: '계산 보류',
}

export default function FixedBenefitDemo({ openLibrary }: { openLibrary: () => void }) {
  const [category, setCategory] = useState<'cancer' | 'whole_life'>('cancer')
  const [caseId, setCaseId] = useState('')
  const cases = demoCases.filter(entry => entry.facts.category === category)
  const current = cases.find(entry => entry.id === caseId) ?? cases[0]
  const { facts } = current
  const outcome = simulateFixedBenefit(facts)
  const policy = demoPolicy(facts)
  const benefit = facts.category === 'cancer'
    ? policy.benefits.find(entry => entry.id === facts.benefitId)!
    : policy.benefits[0]
  const inputs = [
    { label: '계약일', value: facts.contractDate },
    { label: facts.category === 'cancer' ? '진단확정일' : '사망일', value: facts.eventDate },
    { label: '보험가입금액', value: formatWon(facts.sumInsured) },
    { label: '계약 상태', value: { active: '유효 가정', inactive: '효력 없음', review: '미확인' }[facts.contract] },
    { label: '사건 근거', value: { confirmed: '충족 가정', missing: '미확인', exception: '예외 검토 필요' }[facts.evidence] },
  ]
  if (facts.category === 'cancer') {
    inputs.push(
      { label: '약관상 진단 분류', value: benefit.name },
      { label: '최초 진단 여부', value: facts.firstDiagnosis === null ? '미확인' : facts.firstDiagnosis ? '최초 진단' : '재진단' },
    )
  } else {
    inputs.push(
      { label: '계약자적립액', value: formatWon(facts.reserve) },
      { label: '약관상 납입보험료', value: formatWon(facts.premiumsPaid) },
      { label: '기준금액에 더할 추가납입액', value: formatWon(facts.additionalPremiums) },
      { label: '기준금액에서 뺄 인출액', value: formatWon(facts.withdrawals) },
    )
  }
  const sources = [...benefit.sources, ...policy.conditions.map(condition => condition.source)]

  return <section className="wide-panel fixed-demo" aria-labelledby="fixed-demo-title">
    <div className="fixed-policy-heading">
      <h2 id="fixed-demo-title">정액보험 시뮬레이션</h2>
      <button type="button" className="outline" onClick={openLibrary}>약관 라이브러리 보기</button>
    </div>
    <p>가상 사례를 선택해 청구 조건과 계산 근거를 비교하세요. 검토 전 약관 초안을 사용합니다.</p>
    <div className="fixed-demo-controls">
      <label>보험 유형
        <select value={category} onChange={event => {
          setCategory(event.target.value === 'whole_life' ? 'whole_life' : 'cancer')
          setCaseId('')
        }}>
          <option value="cancer">암보험</option>
          <option value="whole_life">종신보험</option>
        </select>
      </label>
      <label>가상 사례
        <select value={current.id} onChange={event => setCaseId(event.target.value)}>
          {cases.map(entry => <option key={entry.id} value={entry.id}>{entry.title}</option>)}
        </select>
      </label>
    </div>
    <div className="fixed-demo-grid">
      <section className="fixed-policy-card" aria-label="가상 입력">
        <h3>{policy.title}</h3>
        <p>{policy.documentVersion} · {policy.scope}</p>
        <dl>{inputs.map(input => <div key={input.label}><dt>{input.label}</dt><dd>{input.value}</dd></div>)}</dl>
      </section>
      <section className="fixed-policy-card" aria-label="가상 계산 결과" aria-live="polite">
        <p><strong>{labels[outcome.status]}</strong></p>
        {outcome.status === 'estimated' && <p className="fixed-demo-amount">{formatWon(outcome.amount)}</p>}
        <p>{outcome.message}</p>
        {outcome.details.length > 0 && <dl>{outcome.details.map(detail =>
          <div key={detail.label}><dt>{detail.label}</dt><dd>{detail.value}</dd></div>,
        )}</dl>}
      </section>
    </div>
    <details>
      <summary>공식 약관에서 근거 확인</summary>
      <ul className="fixed-policy-links">{sources.map(source => <li key={source.clause}>
        <a href={`${policy.source.url}#page=${source.page}`} target="_blank" rel="noreferrer">
          {source.clause} · PDF {source.page}쪽
        </a>
      </li>)}</ul>
    </details>
  </section>
}
