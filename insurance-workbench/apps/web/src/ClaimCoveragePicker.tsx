import policies from './fixed-benefit-policies.json'
import type { Ref } from 'react'
import type { SupportingDocument } from './supplemental'

export type ClaimRoute = 'indemnity' | 'cancer' | 'whole_life'
const cancerPolicy = policies.find(policy => policy.category === 'cancer')!

function diagnosisCandidates(documents: SupportingDocument[]) {
  return documents.flatMap(document => {
    if (document.kind !== 'DIAGNOSIS' || !document.code) return []
    const code = document.code.value.trim().toUpperCase()
    if (!/^[CD][0-9]{2}(?:\.[0-9A-Z]{1,4})?$/.test(code)) return []
    const group = code.slice(0, 3)
    const benefit = cancerPolicy.benefits.find(benefit =>
      'codes' in benefit.trigger && benefit.trigger.codes?.some(range => {
        const [first, last = first] = range.split('-')
        return first <= group && group <= last
      }))
    return benefit ? [{ code, name: benefit.name }] : []
  })
}

export default function ClaimCoveragePicker({ value, onChange, documents, reconciled, selectedCount, coverageSummary, disabled, headingRef }: {
  value: ClaimRoute; onChange: (route: ClaimRoute) => void; documents: SupportingDocument[]
  reconciled: boolean; selectedCount: number; coverageSummary: string[]
  disabled: boolean; headingRef: Ref<HTMLHeadingElement>
}) {
  const diagnoses = documents.filter(document => document.kind === 'DIAGNOSIS')
  const matches = diagnosisCandidates(documents)
  const categories = [
    { id: 'indemnity', title: '실손보험', event: '실제로 부담한 치료비',
      status: !reconciled ? '금액 대조 필요' : selectedCount ? '검토 가능' : '치료 선택 필요',
      ready: reconciled && selectedCount > 0,
      evidence: '진료비 영수증과 세부내역서를 읽었습니다.',
      next: coverageSummary.length ? `선택한 치료의 가상 담보 · ${coverageSummary.join(' / ')}`
        : '조회할 치료 항목과 급여 구분을 확인하세요.' },
    { id: 'cancer', title: '암보험', event: '약관에서 정한 최초 진단확정',
      status: matches.length ? '분류 후보' : diagnoses.length ? '분류 확인 필요' : '진단서 필요', ready: false,
      evidence: matches.length ? `라이나 약관의 분류 후보 · ${matches.map(match => `${match.code} → ${match.name}`).join(', ')}`
        : diagnoses.length ? '등록된 진단서의 코드에서 이 약관의 암 급부 분류 후보를 찾지 못했습니다.' : '등록된 진단서가 없습니다.',
      next: '해당 보험증권, 진단확정일과 병리 근거, 최초 진단 이력, 보장개시일을 확인해야 합니다.' },
    { id: 'whole_life', title: '종신보험', event: '보장형 계약의 사망',
      status: '사망 증빙 필요', ready: false,
      evidence: '등록된 진료 서류만으로 사망 사건을 확인할 수 없습니다.',
      next: '사망진단서 등 사고증명서와 보장형 계약의 보험증권이 필요합니다. 현재 첨부 화면은 사망진단서 읽기를 지원하지 않습니다.' },
  ] as const

  return <section className="wide-panel claim-coverage" aria-labelledby="claim-coverage-heading">
    <div className="section-top"><div>
      <h2 id="claim-coverage-heading" ref={headingRef} tabIndex={-1}>어떤 보험으로 검토할까요?</h2>
      <p>서류에 근거해 검토할 보험을 고르세요. 지급 여부는 가입 계약과 약관 조건을 확인해야 알 수 있습니다.</p>
    </div><a href="#additional-claim-documents" className="outline">추가 서류 첨부로 이동</a></div>
    <fieldset className="claim-coverage-options" disabled={disabled} aria-label="검토할 보험">
      {categories.map(option => <label key={option.id} className={`claim-coverage-option${value === option.id ? ' selected' : ''}`}>
        <span className="claim-coverage-title">
          <input type="radio" name="claim-coverage" value={option.id} aria-label={option.title}
            aria-describedby={`claim-${option.id}-event claim-${option.id}-evidence claim-${option.id}-next`}
            checked={value === option.id} onChange={() => onChange(option.id)}/>
          <strong>{option.title}</strong>
          <span className={`status ${option.ready ? 'status-green' : 'status-amber'}`}>{option.status}</span>
        </span>
        <span className="claim-coverage-event" id={`claim-${option.id}-event`}>{option.event}</span>
        <span id={`claim-${option.id}-evidence`}><b>등록 근거</b> {option.evidence}</span>
        <span id={`claim-${option.id}-next`}><b>다음 확인</b> {option.next}</span>
      </label>)}
    </fieldset>
    {value !== 'indemnity' && <p className="claim-coverage-note" role="status">
      {value === 'cancer' ? '암보험' : '종신보험'}을 선택했습니다. 등록 서류는 기기에 유지됩니다. 이 청구 건의 정액보험 금액은 증빙과 계약을 확인할 때까지 보류합니다.
    </p>}
  </section>
}
