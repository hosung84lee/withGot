import { useEffect, useRef, useState } from 'react'
import { ShieldCheck, Sparkles, Upload, X } from 'lucide-react'
import { benefitNames, coverageNames, enrollmentNames, isCandidateResponse, moneyValue,
  parsePair, releaseDocuments, selectedCoverages, transferSnapshot, treatmentNames } from './privacy'
import type { Benefit, Contract, Enrollment, LocalDocument, ReviewItem, Transfer,
  TreatmentKind } from './privacy'
import CoverageResults from './CoverageResults'
import SupportingDocuments, { SupportingDocumentCatalog } from './SupportingDocuments'
import ClaimCoveragePicker, { type ClaimRoute } from './ClaimCoveragePicker'
import DocumentCard from './DocumentCard'
import OutpatientEstimate from './OutpatientEstimate'
import { calculationInputs, type PaymentRelation, type SupportingDocument } from './supplemental'
import type { CompletedLookup } from './CoverageResults'
import './privacy.css'

const initialContract: Contract = { standard: 'enrolled', mri: 'unknown', injection: 'unknown' }
const money = (value: number) => value.toLocaleString('ko-KR') + '원'
const samples = [
  { path: `${import.meta.env.BASE_URL}samples/receipt.pdf`, name: '가상 영수증.pdf', title: '진료비 영수증', fields: '환자 부담 합계' },
  { path: `${import.meta.env.BASE_URL}samples/details.pdf`, name: '가상 세부내역서.pdf', title: '진료비 세부내역서', fields: '치료 항목, 급여 구분, 비용' },
]

export default function PrivacyWorkbench() {
  const [queuedFiles, setQueuedFiles] = useState<File[]>([])
  const [documents, setDocuments] = useState<LocalDocument[]>([])
  const [receiptIndex, setReceiptIndex] = useState<number | null>(null)
  const [supporting, setSupporting] = useState<SupportingDocument[]>([])
  const [relations, setRelations] = useState(() => new Map<string, PaymentRelation>())
  const [claimRoute, setClaimRoute] = useState<ClaimRoute>('indemnity')
  const [items, setItems] = useState<ReviewItem[]>([])
  const [patientTotal, setPatientTotal] = useState<number | null>(null)
  const [caseId, setCaseId] = useState('')
  const [contract, setContract] = useState<Contract>({ ...initialContract })
  const [status, setStatus] = useState<'idle' | 'loading_sample' | 'extracting' | 'review' | 'sending' | 'result'>('idle')
  const [error, setError] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [snapshot, setSnapshot] = useState<string | null>(null)
  const [lookup, setLookup] = useState<CompletedLookup | null>(null)
  const [selected, setSelected] = useState(0)
  const [source, setSource] = useState({ document: 0, page: 1, item: -1 })
  const resources = useRef<LocalDocument[]>([])
  const active = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const busy = useRef(false)
  const coverageHeading = useRef<HTMLHeadingElement>(null)
  const sourceHeading = useRef<HTMLHeadingElement>(null)
  const transferHeading = useRef<HTMLHeadingElement>(null)
  const resultsHeading = useRef<HTMLHeadingElement>(null)

  function dispose() {
    generation.current++
    active.current?.abort()
    active.current = null
    releaseDocuments(resources.current)
    resources.current = []
    busy.current = false
  }

  const hasItems = items.length > 0
  useEffect(() => () => dispose(), [])
  useEffect(() => { if (hasItems) coverageHeading.current?.focus() }, [hasItems])
  useEffect(() => { if (snapshot) transferHeading.current?.focus() }, [snapshot])
  useEffect(() => { if (lookup) resultsHeading.current?.focus() }, [lookup])

  function reset() {
    dispose()
    setQueuedFiles([])
    setDocuments([])
    setReceiptIndex(null)
    setSupporting([])
    setRelations(new Map())
    setClaimRoute('indemnity')
    setItems([])
    setPatientTotal(null)
    setCaseId('')
    setContract({ ...initialContract })
    setStatus('idle')
    setError('')
    setReviewed(false)
    setSnapshot(null)
    setLookup(null)
    setSelected(0)
    setSource({ document: 0, page: 1, item: -1 })
  }

  async function openFiles(selection: File[] | 'samples') {
    if (selection !== 'samples' && selection.length > 2) {
      setError('영수증과 세부내역서 PDF를 최대 두 개까지 선택해 주세요.')
      return
    }
    reset()
    if (selection !== 'samples') {
      setQueuedFiles(selection)
      if (selection.length < 2) return
    }
    const current = generation.current
    const controller = new AbortController()
    active.current = controller
    setStatus(selection === 'samples' ? 'loading_sample' : 'extracting')
    const loaded: LocalDocument[] = []
    try {
      let files = selection
      if (files === 'samples') {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)])
        files = await Promise.all(samples.map(async sample => {
          const response = await fetch(sample.path, { signal, cache: 'no-store', credentials: 'omit', redirect: 'error' })
          if (!response.ok) throw new Error('sample_unavailable')
          return new File([await response.blob()], sample.name, { type: 'application/pdf' })
        }))
        if (current !== generation.current) return
        setQueuedFiles(files)
        setStatus('extracting')
      }
      const { readLocalPdf } = await import('./localPdf')
      for (const file of files) loaded.push(await readLocalPdf(file, controller.signal))
      if (current !== generation.current) { releaseDocuments(loaded); return }
      const parsed = parsePair(loaded)
      resources.current = loaded
      setDocuments(loaded)
      setReceiptIndex(parsed.receiptIndex)
      setItems(parsed.items)
      setPatientTotal(parsed.patientTotal)
      setCaseId(parsed.caseId)
      setStatus('review')
      const index = Math.min(2, parsed.items.length - 1)
      setSelected(index)
      const item = parsed.items[index]
      setSource({ document: item.document, page: item.source.page, item: index })
    } catch (error) {
      releaseDocuments(loaded)
      if (current !== generation.current) return
      controller.abort()
      setError(selection === 'samples' ? '가상 샘플을 읽지 못했습니다. 다시 시도하거나 PDF를 직접 선택해 주세요.'
        : error instanceof Error ? error.message : '문서를 읽을 수 없습니다.')
      setStatus('idle')
    }
  }

  function invalidate() {
    setSnapshot(null)
    setReviewed(false)
    setLookup(null)
    setStatus('review')
    setError('')
  }

  function updateItem(index: number, change: Partial<Pick<ReviewItem, 'kind' | 'benefit' | 'total' | 'patient' | 'selected'>>) {
    invalidate()
    setItems(previous => previous.map((item, position) => position === index ? { ...item, ...change } : item))
  }

  function showSource(index: number) {
    const item = items[index]
    setSelected(index)
    setSource({ document: item.document, page: item.source.page, item: index })
  }

  function openSource(index: number) {
    showSource(index)
    sourceHeading.current?.focus()
  }

  const invalidCosts = items.some(item => moneyValue(item.total) === null || moneyValue(item.patient) === null
    || Number(item.patient) > Number(item.total))
  const allPatient = items.reduce((sum, item) => sum + (moneyValue(item.patient) ?? 0), 0)
  const selectedPatient = items.filter(item => item.selected)
    .reduce((sum, item) => sum + (moneyValue(item.patient) ?? 0), 0)
  const reconciled = patientTotal !== null && !invalidCosts && allPatient === patientTotal
  const expenses = patientTotal === null ? null : calculationInputs(supporting, relations, {
    total: patientTotal, reconciled, items,
  })

  function prepare() {
    if (claimRoute !== 'indemnity' || !reviewed || !reconciled) return
    try {
      setSnapshot(transferSnapshot(items, contract))
      setError('')
    } catch (error) {
      setError(error instanceof Error ? error.message : '전송할 항목을 확인해 주세요.')
    }
  }

  async function sendSnapshot() {
    if (claimRoute !== 'indemnity' || !snapshot || busy.current) return
    busy.current = true
    const current = generation.current
    const controller = new AbortController()
    active.current = controller
    setStatus('sending')
    setError('')
    try {
      const confirmedTransfer = JSON.parse(snapshot) as Transfer
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)])
      const response = await fetch('/api/coverage/candidates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: snapshot, signal, cache: 'no-store', credentials: 'omit',
      })
      if (!response.ok) throw new Error('조회에 실패했습니다. API 실행 상태와 검토한 항목을 확인한 뒤 다시 시도해 주세요.')
      const result: unknown = await response.json()
      if (!isCandidateResponse(result, confirmedTransfer)) {
        throw new Error('조회 응답을 확인할 수 없습니다. 다시 시도해 주세요.')
      }
      if (current !== generation.current) return
      const initialResult = result.items.find(item => item.item_id === selected + 1) ?? result.items[0]
      showSource(initialResult.item_id - 1)
      setLookup({ body: snapshot, transfer: confirmedTransfer, items: result.items })
      setStatus('result')
    } catch (error) {
      if (current !== generation.current) return
      setError(error instanceof Error && !controller.signal.aborted && error.name !== 'TimeoutError'
        && error.message.startsWith('조회') ? error.message : '연결이 끊겼거나 응답 시간이 초과되었습니다. 다시 시도해 주세요.')
      setStatus('review')
    } finally {
      if (current === generation.current) busy.current = false
    }
  }

  const sourceDocument = documents[source.document]
  const sourcePage = sourceDocument?.pages[source.page - 1]
  const highlighted = source.item >= 0 ? items[source.item]?.source : null
  const transfer = snapshot ? JSON.parse(snapshot) as Transfer : null
  const relevantCoverages = selectedCoverages(items)
  const transferConditions = Object.entries(transfer?.contract ?? {}).map(([key, value]) =>
    `${coverageNames[key as keyof Contract]} ${enrollmentNames[value]}`)

  return <div className="privacy-workbench">
    <section className="privacy-intro">
      <ShieldCheck size={28}/>
      <div><h2>원본은 기기에, 보장 조회는 선택한 항목으로</h2>
        <p>PDF를 기기에서 읽고, 전송할 치료 항목을 직접 확인하세요. 치료 종류와 금액도 민감한 정보입니다.</p></div>
      <button className="outline" onClick={reset}>세션 초기화</button>
    </section>
    <ol className="privacy-steps" aria-label="분석 진행 단계">
      {['기기 내 문서 읽기', '항목 검토', '전송 내용 확인', '보장 후보 조회'].map((step, index) =>
        <li key={step} className={(index === 0 && !items.length) || (index === 1 && items.length > 0 && !snapshot)
          || (index === 2 && snapshot && status !== 'result') || (index === 3 && status === 'result') ? 'current' : ''}>
          <span>{index + 1}</span>{step}</li>)}
    </ol>
    <section className="privacy-files wide-panel" aria-label="PDF 선택">
      <div className="section-top"><div><h2>1. 분석할 서류를 준비하세요</h2>
        <p>같은 진료 건의 영수증과 세부내역서가 필요합니다. 가상 서류로 바로 체험할 수 있어요.</p></div></div>
      <div className="privacy-file-actions">
        <button className="primary" disabled={status === 'loading_sample' || status === 'extracting'}
          onClick={() => void openFiles('samples')}><Sparkles size={16}/>가상 샘플로 시작</button>
        <label className="outline privacy-file-button"><Upload size={16}/>{queuedFiles.length === 1 ? '나머지 PDF 추가' : 'PDF 선택'}
          <input aria-label="영수증과 세부내역서 선택" type="file" accept="application/pdf,.pdf" multiple
            onChange={event => {
              const files = Array.from(event.target.files ?? [])
              event.target.value = ''
              if (!files.length) return
              void openFiles(files.length === 1 && queuedFiles.length === 1 ? [...queuedFiles, ...files] : files)
            }}/>
        </label>
      </div>
      <p className="privacy-file-help">지원 서식의 텍스트 PDF · 파일당 10 MiB / 10페이지 · 한 장씩 또는 두 장 함께 선택</p>
      <p className="privacy-local" role="status">{status === 'loading_sample' ? '가상 샘플을 불러오고 있습니다…'
        : status === 'extracting' ? '기기에서 PDF를 읽고 있습니다…'
        : documents.length ? `PDF ${documents.length}개를 기기에서 읽었습니다.`
        : queuedFiles.length === 1 ? '1/2 선택됨 · 나머지 PDF를 추가해 주세요.'
        : '파일 선택과 검토 단계에서는 문서 데이터를 전송하지 않습니다.'}</p>
      {queuedFiles.length > 0 && <ul className="privacy-file-list" aria-label="선택한 PDF">
        {queuedFiles.map((file, index) => <li key={index}>
          <DocumentCard title={receiptIndex === null ? '선택한 PDF' : samples[index === receiptIndex ? 0 : 1].title}
            description={file.name} status={documents[index] ? '읽기 완료' : status === 'extracting' ? '읽는 중' : '유형 미확인'}
            confirmed={Boolean(documents[index])} actions={<>
              {documents[index] && <button className="outline" aria-label={`${file.name} 원본 보기`}
                onClick={() => { setSource({ document: index, page: 1, item: -1 }); sourceHeading.current?.focus() }}>원본 보기</button>}
              <button className="outline" aria-label={`${file.name} 선택 해제`}
                onClick={() => void openFiles(queuedFiles.filter((_, position) => position !== index))}>빼기</button>
            </>}/>
        </li>)}
      </ul>}
      <section className="privacy-support-catalog" aria-label="기본 서류 샘플">
        <h3>기본 서류 2종</h3>
        <ul>{samples.map(sample => <li key={sample.path}><DocumentCard sample
          title={sample.title} description={sample.fields} status="기본 서류"
          actions={<a href={sample.path} download={sample.name}>{sample.title} 샘플 PDF</a>}/>
        </li>)}</ul>
      </section>
      {!hasItems && <SupportingDocumentCatalog/>}
    </section>
    {error && <div className="privacy-error" role="alert">{error}</div>}
    {hasItems && <>
      {expenses && <SupportingDocuments key={caseId} caseId={caseId} inputs={expenses}
        relations={relations} setRelations={setRelations} documents={supporting} onDocumentsChange={setSupporting}/>}
      <ClaimCoveragePicker value={claimRoute} documents={supporting} reconciled={reconciled} headingRef={coverageHeading}
        selectedCount={items.filter(item => item.selected).length}
        coverageSummary={[...relevantCoverages].map(key => `${coverageNames[key]} ${enrollmentNames[contract[key]]}`)}
        disabled={status === 'sending'} onChange={route => { invalidate(); setClaimRoute(route) }}/>
      {claimRoute === 'indemnity' && <section className="wide-panel privacy-review" aria-label="치료 항목 검토">
        <div className="section-top"><div><h2>2. 읽어 온 항목을 원본과 대조하세요</h2>
          <p>원본 위치를 누르면 해당 줄을 강조합니다. 수정한 값과 원문은 구분하여 표시합니다.</p></div></div>
        <fieldset disabled={status === 'sending'}>
          <div className="privacy-table-scroll"><table><thead><tr><th>조회</th><th>치료 종류</th><th>급여 구분</th><th>총액 (원)</th><th>환자 부담 (원)</th><th>기기 내 원본</th></tr></thead>
            <tbody>{items.map((item, index) => <tr key={index}>
              <td><input aria-label={`항목 ${index + 1} 조회 선택`} type="checkbox" checked={item.selected}
                onChange={event => updateItem(index, { selected: event.target.checked })}/></td>
              <td><select aria-label={`항목 ${index + 1} 치료 종류`} value={item.kind}
                onChange={event => updateItem(index, { kind: event.target.value as TreatmentKind | 'unknown' })}>
                <option value="unknown">미지원 · 검토 필요</option>
                {Object.entries(treatmentNames).map(([kind, name]) => <option key={kind} value={kind}>{name}</option>)}</select></td>
              <td><select aria-label={`항목 ${index + 1} 급여 구분`} value={item.benefit}
                onChange={event => updateItem(index, { benefit: event.target.value as Benefit })}>
                {Object.entries(benefitNames).map(([benefit, name]) => <option key={benefit} value={benefit}>{name}</option>)}</select></td>
              <td><input aria-label={`항목 ${index + 1} 총액`} inputMode="numeric" value={item.total}
                onChange={event => updateItem(index, { total: event.target.value })}/></td>
              <td><input aria-label={`항목 ${index + 1} 환자 부담`} inputMode="numeric" value={item.patient}
                onChange={event => updateItem(index, { patient: event.target.value })}/></td>
              <td><button className="outline" onClick={() => openSource(index)}>원본 위치 · {item.source.page}쪽</button>
                <small className="privacy-provenance">{item.kind !== item.extracted.kind || item.benefit !== item.extracted.benefit
                  || item.total !== item.extracted.total || item.patient !== item.extracted.patient ? '사용자 수정값' : '문서 추출값'}</small></td>
            </tr>)}</tbody></table></div>
          <div className={'privacy-balance ' + (reconciled ? 'balanced' : 'unbalanced')} role="status">
            <span>영수증 환자 부담 {money(patientTotal ?? 0)}</span><span>전체 항목 환자 부담 {invalidCosts ? '금액 확인 필요' : money(allPatient)}</span>
            <strong>{reconciled ? '합계 일치' : '합계 불일치 · 금액을 다시 확인해 주세요'}</strong>
            <span>조회할 항목의 환자 부담 {money(selectedPatient)}</span>
          </div>
          {relevantCoverages.size > 0 && <div className="privacy-contract"><h3>선택한 치료에 필요한 가상 담보 상태</h3>
            {[...relevantCoverages].map(key => <label key={key}>{coverageNames[key]}
              <select aria-label={`${coverageNames[key]} 가입 상태`} value={contract[key]} onChange={event => {
                invalidate(); setContract(previous => ({ ...previous, [key]: event.target.value as Enrollment }))
              }}>{Object.entries(enrollmentNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>)}
          </div>}
          <label className="privacy-check"><input type="checkbox" checked={reviewed} aria-label="항목과 합계 검토 완료"
            onChange={event => { setReviewed(event.target.checked); setSnapshot(null); setLookup(null); setStatus('review') }}/>
            원본과 치료 항목, 금액, 가상 계약 조건을 확인했습니다.</label>
          <div className="privacy-file-actions">
            <button className="primary" disabled={!reviewed || !reconciled} onClick={prepare}>전송 내용 확인</button>
            <a className="outline" href="#outpatient-estimate">기기에서 실손 계산 보기</a>
          </div>
        </fieldset>
      </section>}
      {claimRoute === 'indemnity' && expenses && <OutpatientEstimate
        key={JSON.stringify(expenses.pharmacy.map(receipt => [receipt.id, receipt.status, receipt.paid.value, receipt.covered.value]))}
        items={items} inputs={expenses} reviewed={reviewed} enrollment={contract.standard} onOpenSource={openSource}/>}
      {sourcePage && <section className="wide-panel privacy-source" aria-label="기기 내 원본 미리보기">
        <div className="section-top"><div><h2 ref={sourceHeading} tabIndex={-1}>기기 내 원본</h2><p>{sourceDocument.name} · {source.page}쪽</p></div>
          <div className="privacy-page-buttons">{sourceDocument.pages.map((_, index) => <button className="outline" key={index}
            onClick={() => setSource(previous => ({ ...previous, page: index + 1, item: -1 }))}>{index + 1}쪽</button>)}</div></div>
        {highlighted && <p className="privacy-original">추출 원문 · {items[source.item].original}</p>}
        <div className="privacy-paper" style={{ aspectRatio: `${sourcePage.width}/${sourcePage.height}` }}>
          <img src={sourcePage.url} alt="기기에서 생성한 원본 PDF 미리보기"/>
          {highlighted && <div className="privacy-highlight" aria-label="선택한 치료의 원본 위치" style={{
            left: `${Math.max(0, highlighted.left - 3) / sourcePage.width * 100}%`,
            top: `${Math.max(0, highlighted.top - 3) / sourcePage.height * 100}%`,
            width: `${(highlighted.width + 6) / sourcePage.width * 100}%`,
            height: `${(highlighted.height + 8) / sourcePage.height * 100}%`,
          }}/>}</div>
      </section>}
      {snapshot && transfer && <section className="wide-panel privacy-transfer" aria-label="전송 내용 확인">
        <div className="section-top"><div><h2 ref={transferHeading} tabIndex={-1}>3. 이 내용으로 서버에 조회합니다</h2>
          <p>선택한 치료 종류와 급여 구분, 조회에 필요한 가상 담보 상태를 보냅니다.</p></div>
          <button className="outline" disabled={status === 'sending'} aria-label="전송 확인 닫기" onClick={() => setSnapshot(null)}><X size={15}/></button></div>
        <div className="privacy-boundaries"><div><h3>기기에 남는 정보</h3><p>진료비 총액, 환자 부담액, 원본 PDF, 이름, 환자번호, 파일명, 원문과 페이지 위치</p></div>
          <div><h3>서버에 보내는 정보</h3><p>선택한 치료 {transfer.items.length}개와 조회에 필요한 담보 상태 {transferConditions.length}개</p></div></div>
        <ul className="privacy-transfer-list">{transfer.items.map(item => <li key={item.item_id}>
          {treatmentNames[item.kind]} · {benefitNames[item.benefit]}</li>)}</ul>
        {transferConditions.length > 0 && <p>{transferConditions.join(' / ')}</p>}
        <p className="privacy-purpose">조회 결과는 가상 규칙에 따른 후보입니다. 서버는 이 요청의 문서 데이터를 저장하지 않습니다.</p>
        <details><summary>실제 전송 데이터 확인</summary><pre data-testid="transfer-json">{snapshot}</pre></details>
        <button className="primary" disabled={status === 'sending'} onClick={() => void sendSnapshot()}>
          {status === 'sending' ? '조회 중…' : '확인한 항목으로 서버 조회'}</button>
      </section>}
      {lookup && <CoverageResults lookup={lookup} reviewedItems={items} selected={selected}
        headingRef={resultsHeading} onSelect={showSource} onOpenSource={openSource}/>}
    </>}
    <p className="privacy-session-note">원본과 추출 내용은 이 화면의 메모리에서만 유지됩니다. 세션 초기화 또는 화면 종료 시 앱이 보유한 문서와 조회 결과를 정리합니다.</p>
  </div>
}
