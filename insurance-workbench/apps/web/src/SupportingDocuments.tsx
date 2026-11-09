import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { releaseDocuments } from './privacy'
import { type calculationInputs, documentKinds, parseSupportingDocument } from './supplemental'
import type { PaymentRelation, SupportingDocument } from './supplemental'
import DocumentCard from './DocumentCard'

const samples = [
  { kind: 'DIAGNOSIS', file: 'diagnosis.pdf', fields: '진단명, 질병분류기호' },
  { kind: 'PRESCRIPTION', file: 'prescription.pdf', fields: '처방번호, 약 이름, 투약일수' },
  { kind: 'PAYMENT', file: 'payment.pdf', fields: '해당 진료 건의 납입액' },
  { kind: 'PHARMACY', file: 'pharmacy.pdf', fields: '처방번호, 급여 본인부담, 비급여, 약국 환자 부담액' },
] as const
const samplePath = (file: string) => `${import.meta.env.BASE_URL}samples/supplements/${file}`
const maxDocuments = 8
const won = (amount: number) => `${amount.toLocaleString('ko-KR')}원`
const pharmacyLabels = {
  counted: '별도 납부 확인 · 합산', included: '병원 진료비에 포함 · 추가 합산 제외',
  unlinked: '같은 처방번호의 처방전 필요', overlap: '같은 처방의 영수증이 여러 장입니다. 중복 여부 확인 필요',
  unconfirmed: '별도 납부 여부 확인 필요',
}

function sourceRows(document: SupportingDocument) {
  switch (document.kind) {
    case 'DIAGNOSIS': return document.code ? [document.diagnosis, document.code] : [document.diagnosis]
    case 'PRESCRIPTION': return document.medications
    case 'PAYMENT': return [document.paid]
    case 'PHARMACY': return [document.prescriptionId, document.covered, document.uncovered, document.paid]
  }
}

export function SupportingDocumentCatalog({ documents }: { documents?: SupportingDocument[] }) {
  return <section className="privacy-support-catalog" aria-label="첨부 가능한 추가 서류">
    <h3>첨부 가능한 추가 서류 4종</h3>
    <p>기본 서류를 읽은 뒤 같은 진료 건의 추가 서류를 선택하세요. 아래 샘플은 기본 가상 사례와 연결됩니다.</p>
    <ul>{samples.map(sample => {
      const title = documentKinds[sample.kind]
      const count = documents?.filter(document => document.kind === sample.kind).length ?? 0
      return <li key={sample.kind}><DocumentCard sample title={title} description={sample.fields}
        status={count > 0 ? `첨부 ${count}건` : '추가 서류'} confirmed={count > 0}
        actions={<a href={samplePath(sample.file)} download={`가상 ${title}.pdf`}>{title} 샘플 PDF</a>}/>
      </li>
    })}</ul>
  </section>
}

export default function SupportingDocuments({ caseId, documents, onDocumentsChange, inputs, relations, setRelations }: {
  caseId: string
  documents: SupportingDocument[]; onDocumentsChange: (documents: SupportingDocument[]) => void
  inputs: ReturnType<typeof calculationInputs>
  relations: ReadonlyMap<string, PaymentRelation>
  setRelations: Dispatch<SetStateAction<Map<string, PaymentRelation>>>
}) {
  const [errors, setErrors] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const active = useRef<AbortController | null>(null)

  useEffect(() => () => active.current?.abort(), [])

  async function attach(selection: File[] | 'samples') {
    if (active.current) return
    const count = selection === 'samples' ? samples.length : selection.length
    if (documents.length + count > maxDocuments) {
      setErrors(['추가 서류는 최대 8개까지 첨부할 수 있습니다.'])
      return
    }
    const controller = new AbortController()
    active.current = controller
    setLoading(true)
    setErrors([])
    const additions: SupportingDocument[] = []
    const failures: string[] = []
    try {
      const files = selection === 'samples' ? await Promise.all(samples.map(async ({ file }) => {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)])
        const response = await fetch(samplePath(file), {
          signal, cache: 'no-store', credentials: 'omit', redirect: 'error',
        })
        if (!response.ok) throw new Error('가상 추가 서류를 불러오지 못했습니다.')
        return new File([await response.blob()], file, { type: 'application/pdf' })
      })) : selection
      const { readLocalPdf } = await import('./localPdf')
      for (const file of files) {
        if (controller.signal.aborted) break
        try {
          const local = await readLocalPdf(file, controller.signal)
          try {
            const parsed = parseSupportingDocument(local, caseId)
            if ([...documents, ...additions].some(other => other.kind === parsed.kind && other.id === parsed.id)) {
              throw new Error('같은 종류와 문서번호의 서류가 이미 있습니다.')
            }
            additions.push(parsed)
          } finally {
            releaseDocuments([local])
          }
        } catch (error) {
          failures.push(`${file.name} · ${error instanceof Error ? error.message : '문서를 읽지 못했습니다.'}`)
        }
      }
    } catch {
      failures.push('추가 서류를 불러오지 못했습니다. 다시 시도해 주세요.')
    } finally {
      if (!controller.signal.aborted) {
        onDocumentsChange([...documents, ...additions])
        setErrors(failures)
        setLoading(false)
      }
      controller.abort()
      active.current = null
    }
  }

  return <section id="additional-claim-documents" tabIndex={-1} className="wide-panel privacy-supporting" aria-label="추가 서류와 계산 기초자료">
    <div className="section-top"><div><h2>추가 서류와 계산 기초자료</h2>
      <p>진단서·처방전·납입확인서·약제비 영수증에서 같은 진료 건의 근거를 읽습니다.</p></div></div>
    <SupportingDocumentCatalog documents={documents}/>
    <div className="privacy-file-actions">
      <label className="outline privacy-file-button">추가 PDF 선택
        <input type="file" multiple accept="application/pdf,.pdf" aria-label="추가 PDF 선택" disabled={loading}
          onChange={event => {
            const files = Array.from(event.target.files ?? [])
            event.target.value = ''
            if (files.length) void attach(files)
          }}/>
      </label>
      {caseId === 'DEMO-001' && <button className="outline" disabled={loading}
        onClick={() => void attach('samples')}>가상 추가 서류 4종 불러오기</button>}
    </div>
    <p className="privacy-file-help">지원 서식의 텍스트 PDF · 파일당 10 MiB / 10페이지 · 최대 8개 · 기기 내 처리</p>
    {loading && <p className="privacy-local" role="status">추가 서류를 기기에서 읽고 있습니다…</p>}
    {errors.length > 0 && <ul role="alert" className="privacy-support-errors">
      {errors.map((error, index) => <li key={index}>{error}</li>)}
    </ul>}
    {documents.length > 0 && <>
      <ul className="privacy-support-docs" aria-label="구조화한 추가 서류">
        {documents.map(document => <li key={`${document.kind}-${document.id}`}>
          <DocumentCard title={documentKinds[document.kind]} description={`${document.name} · ${document.id}`}
            status="읽기 완료" confirmed actions={<button className="outline" aria-label={`${document.name} 빼기`} disabled={loading} onClick={() => {
              onDocumentsChange(documents.filter(other => other !== document))
              setErrors([])
              if (document.kind === 'PHARMACY') setRelations(previous => {
                const next = new Map(previous)
                next.delete(document.id)
                return next
              })
            }}>빼기</button>}>
          <ul>{sourceRows(document).map((row, index) => <li key={index}>{row.page}쪽 · {row.text}</li>)}</ul>
          {document.kind === 'PAYMENT' && <p>{document.paid.value === inputs.hospital.patientWon
            ? '영수증 환자 부담액과 일치 · 증빙으로 사용' : '영수증 환자 부담액과 납입액이 다릅니다.'}</p>}
          {document.kind === 'PHARMACY' && <>
            <label>병원 진료비와의 관계 <select aria-label={`${document.id} 약제비 납부 관계`}
              value={relations.get(document.id) ?? ''} onChange={event => {
                const value = event.target.value as PaymentRelation | ''
                setRelations(previous => {
                  const next = new Map(previous)
                  if (value) next.set(document.id, value)
                  else next.delete(document.id)
                  return next
                })
              }}><option value="">미확인</option><option value="separate">별도 납부</option>
              <option value="included">병원 진료비에 포함</option></select></label>
            <p>{pharmacyLabels[inputs.pharmacy.find(receipt => receipt.id === document.id)!.status]}</p>
          </>}
          </DocumentCard>
        </li>)}
      </ul>
      <div className="privacy-support-totals" aria-label="비용 대조 결과">
        <p>병원 영수증 환자 부담액 <strong>{won(inputs.hospital.patientWon)}</strong></p>
        <p>별도 납부가 확인된 약제비 <strong>{won(inputs.separatePharmacyWon)}</strong></p>
        <p>{inputs.verifiedExpenseWon === null ? '비용 대조 확인 필요'
          : <>계산용 환자 부담액 합계 <strong>{won(inputs.verifiedExpenseWon)}</strong></>}</p>
        <p>진단과 처방은 보장 조건의 근거로 보관합니다. 합계는 보험금 계산에 쓸 비용 입력입니다.</p>
      </div>
      <details className="privacy-query-receipt"><summary>계산 기초자료 JSON · 기기 내</summary>
        <pre data-testid="calculation-inputs">{JSON.stringify({ caseId, ...inputs }, null, 2)}</pre></details>
    </>}
  </section>
}
