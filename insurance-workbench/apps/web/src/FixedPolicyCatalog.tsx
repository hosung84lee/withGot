import policies from './fixed-benefit-policies.json'
import type { ReactNode } from 'react'
import structuredFile from './fixed-benefit-policies.json?url'
import './fixed-policy.css'

type SourceReference = { clause: string; page: number; endPage?: number }

function ClauseLink({ url, reference }: { url: string; reference: SourceReference }) {
  const pages = reference.endPage ? `${reference.page}–${reference.endPage}` : reference.page
  return <a href={`${url}#page=${reference.page}`} target="_blank" rel="noreferrer">
    {reference.clause} · PDF {pages}쪽
  </a>
}

const categoryNames = { whole_life: '종신보험', cancer: '암보험' }
const indemnityPolicies = [
  { title: '삼성 급여 실손의료비보장보험', insurer: '삼성생명', version: '2605', origin: '사용자 첨부 자료',
    scope: '급여 실손의료비 참고 자료입니다. 가입 담보와 계약 버전에 맞는 약관을 확인하세요.' },
  { title: '삼성화재 다이렉트 실손의료비보험', insurer: '삼성화재', version: '2605.1 · 계약전환용',
    origin: '공식 웹 공개 자료', url: 'https://direct.samsungfire.com/docs/realloss.pdf',
    scope: '계약전환용 실손 약관입니다. 삼성생명 상품과 구분해 계약 버전을 확인하세요.' },
]

function PolicyCard({ title, label, version, status, scope, event, url, children }: {
  title: string; label: string; version: string; status: string; scope: string; event: string; url?: string; children: ReactNode
}) {
  return <article className="fixed-policy-card policy-library-card">
    <div className="fixed-policy-heading">
      <div><p>{label}</p><h3>{title}</h3><p>{version}</p></div>
      <span className="status status-amber">{status}</span>
    </div>
    <p className="fixed-policy-scope">{scope}</p>
    <p><strong>검토 기준</strong> · {event}</p>
    <div className="policy-card-actions">
      {url ? <a className="outline" href={url} target="_blank" rel="noreferrer">공식 약관 PDF</a>
        : <span>원문 · 사용자 첨부 자료</span>}
    </div>
    {children}
  </article>
}

export default function FixedPolicyCatalog({ query }: { query: string }) {
  const search = query.trim().toLocaleLowerCase('ko-KR')
  const matches = (value: string) => value.toLocaleLowerCase('ko-KR').includes(search)
  const matching = policies.filter(policy => {
    const category = categoryNames[policy.category as keyof typeof categoryNames]
    return matches(`${policy.title} ${policy.insurer} 정액 ${category} ${policy.scope} ${policy.documentVersion}`)
  })
  const matchingIndemnity = indemnityPolicies.filter(policy => matches(`${policy.title} ${policy.insurer} ${policy.version}`))

  return <>
    <section className="fixed-policy-catalog" aria-label="실손보험 약관">
      <div className="fixed-policy-heading"><h2>실손보험 약관</h2></div>
      {matchingIndemnity.length === 0 && <p>검색에 맞는 실손보험 약관이 없습니다.</p>}
      {matchingIndemnity.map(policy => <PolicyCard key={policy.title} title={policy.title}
        label={`${policy.insurer} · 실손보험`} version={policy.version} status="참고 자료"
        scope={policy.scope} event="보험기간 중 약관에서 보장하는 의료비 부담" url={policy.url}>
        <details><summary>지급 기준과 근거 조항</summary>
          <p>치료별 인정 비용과 계약의 공제·한도를 확인하는 실손 검토 자료입니다.</p>
          <p>출처 · {policy.origin}. 계약별 지급 기준과 조항은 원문에서 확인해 주세요.</p>
        </details>
      </PolicyCard>)}
    </section>
    <section className="fixed-policy-catalog" aria-label="정액보험 약관">
    <div className="fixed-policy-heading">
      <h2>정액보험 약관</h2>
      <a href={structuredFile} download="fixed-benefit-policies.json">구조화 초안 JSON</a>
    </div>
    {matching.length === 0 && <p>검색에 맞는 정액보험 약관이 없습니다.</p>}
    {matching.map(policy => <PolicyCard key={policy.id} title={policy.title}
      label={`${policy.insurer} · ${categoryNames[policy.category as keyof typeof categoryNames]}`}
      version={policy.documentVersion} status="검토 전 초안" scope={policy.scope} event={policy.event} url={policy.source.url}>
      <details>
        <summary>지급 기준과 근거 조항</summary>
        <ul>{policy.benefits.map(benefit => <li key={benefit.id}>
          <strong>{benefit.name}</strong>
          <p>{benefit.displayCondition}</p>
          <p>{benefit.displayAmount}</p>
          <div className="fixed-policy-links">{benefit.sources.map(source =>
            <ClauseLink key={source.clause} url={policy.source.url} reference={source}/>)}</div>
        </li>)}</ul>
        <h4>추가 확인 조건</h4>
        <ul>{policy.conditions.map(condition => <li key={condition.id}>
          <p>{condition.description}</p>
          <ClauseLink url={policy.source.url} reference={condition.source}/>
        </li>)}</ul>
        <h4>계산에 필요한 입력</h4>
        <p>{policy.inputs.join(' · ')}</p>
        <h4>관련 서류</h4>
        <p>{policy.documents.join(' · ')}</p>
        <div className="fixed-policy-links">{policy.references.map(source =>
          <ClauseLink key={source.clause} url={policy.source.url} reference={source}/>)}</div>
        <p className="fixed-policy-scope">{policy.scopeNote}</p>
      </details>
    </PolicyCard>)}
  </section></>
}
