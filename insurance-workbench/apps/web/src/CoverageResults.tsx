import type { Ref } from 'react'
import { benefitNames, coverageNames, enrollmentNames, treatmentNames } from './privacy'
import type { Candidate, ReviewItem, Transfer } from './privacy'

export interface CompletedLookup {
  body: string
  transfer: Transfer
  items: Candidate[]
}

interface Props {
  lookup: CompletedLookup
  reviewedItems: ReviewItem[]
  selected: number
  headingRef: Ref<HTMLHeadingElement>
  onSelect: (index: number) => void
  onOpenSource: (index: number) => void
}

const statusNames = { candidate: '보장 후보', missing_information: '추가 확인 필요', not_enrolled: '미가입' }
const treatmentName = (item: ReviewItem) => item.kind === 'unknown' ? '검토 항목' : treatmentNames[item.kind]

export default function CoverageResults({ lookup, reviewedItems, selected, headingRef, onSelect, onOpenSource }: Props) {
  const resultIndex = Math.max(0, lookup.items.findIndex(item => item.item_id === selected + 1))
  const result = lookup.items[resultIndex]
  const item = reviewedItems[result.item_id - 1]
  const sentItem = lookup.transfer.items[resultIndex]
  const pendingCoverage = sentItem.benefit === 'unknown'
  const coverage = coverageNames[result.coverage]
  const enrollment = lookup.transfer.contract[result.coverage]
  const enrollmentLabel = pendingCoverage ? '급여 구분 확인 후 검토' : `${coverage} · ${enrollmentNames[enrollment ?? 'unknown']}`
  const benefitSource = sentItem.benefit === item.extracted.benefit ? '문서 추출값' : '사용자 수정값'
  const sentConditions = Object.keys(lookup.transfer.contract).length

  return <section className="wide-panel privacy-results" aria-label="보장 후보 조회 결과">
    <span className="status status-amber">가상 규칙 {lookup.transfer.rule_version} · 지급 판단 전</span>
    <h2 ref={headingRef} tabIndex={-1}>4. 선택한 치료의 보장 후보</h2>
    <div className="privacy-result-grid">
      <div className="privacy-result-list">{lookup.items.map(candidate => <button
        className={'outline ' + (candidate === result ? 'chosen' : '')} key={candidate.item_id}
        aria-pressed={candidate === result} onClick={() => onSelect(candidate.item_id - 1)}>
        {treatmentName(reviewedItems[candidate.item_id - 1])}<span>{statusNames[candidate.status]}</span>
      </button>)}</div>
      <div className="privacy-result-detail">
        <h3>{treatmentName(item)} → {pendingCoverage ? '적용 담보 검토 중' : coverage}</h3>
        <strong>{statusNames[result.status]}</strong>
        <dl className="privacy-result-evidence" aria-label="조회에 사용한 정보">
          <div><dt>조회한 급여 구분</dt><dd>{benefitNames[sentItem.benefit]} · {benefitSource}</dd></div>
          <div><dt>가상 계약 입력</dt><dd>{enrollmentLabel}</dd></div>
          <div><dt>원본 근거</dt><dd>세부내역서 {item.source.page}쪽</dd></div>
        </dl>
        <h4>다음 확인</h4>
        <ul>{result.checks.map(check => <li key={check}>{check}</li>)}</ul>
        <button className="outline" onClick={() => onOpenSource(result.item_id - 1)}>원본의 해당 줄 확인</button>
      </div>
    </div>
    <details className="privacy-query-receipt">
      <summary>이 조회에서 보낸 정보 <span>치료 {lookup.transfer.items.length}개 · 가상 담보 상태 {sentConditions}개</span></summary>
      <p>원본 PDF, 이름, 환자번호, 진료비는 이 요청에 포함되지 않았습니다.</p>
      <pre>{lookup.body}</pre>
    </details>
  </section>
}
