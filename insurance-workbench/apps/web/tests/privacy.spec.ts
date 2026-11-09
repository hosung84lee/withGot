import { test, expect, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const marker = 'PRIVATE-PATIENT-TRACE-48291'
const sample = (name: string) => resolve('public/samples', name)

async function loadPair(page: Page) {
  await page.getByLabel('영수증과 세부내역서 선택').setInputFiles([
    { name: `${marker}-receipt.pdf`, mimeType: 'application/pdf', buffer: await readFile(sample('receipt.pdf')) },
    { name: 'details.pdf', mimeType: 'application/pdf', buffer: await readFile(sample('details.pdf')) },
  ])
  await expect(page.getByLabel('항목 4 총액')).toHaveValue('65000')
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
}

async function prepare(page: Page) {
  await page.getByLabel('항목과 합계 검토 완료').check()
  await page.getByRole('button', { name: '전송 내용 확인', exact: true }).click()
  await expect(page.getByLabel('전송 내용 확인', { exact: true })).toBeVisible()
}

test('only the reviewed allowlist is sent and the local session is released', async ({ page }) => {
  const requests: { url: string; body: string | null }[] = []
  const errors: string[] = []
  page.on('request', request => requests.push({ url: request.url(), body: request.postData() }))
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await loadPair(page)
  expect(requests.filter(request => request.body)).toHaveLength(0)
  expect(requests.filter(request => /^https?:/.test(request.url) && new URL(request.url).origin !== new URL(page.url()).origin)).toHaveLength(0)

  await page.getByLabel('항목 3 총액').fill('480001')
  await page.getByLabel('항목 4 조회 선택').uncheck()
  await expect(page.getByLabel('비급여 주사 가입 상태')).toHaveCount(0)
  await prepare(page)
  await expect(page.getByRole('heading', { name: /이 내용으로 서버에 조회합니다/ })).toBeFocused()
  const snapshot = await page.getByTestId('transfer-json').textContent()
  expect(snapshot).not.toContain(marker)
  expect(snapshot).not.toContain('details.pdf')
  expect(snapshot).not.toContain('김하늘')
  expect(JSON.parse(snapshot!)).toEqual({
    rule_version: 'synthetic-v1',
    contract: { standard: 'enrolled', mri: 'unknown' },
    items: [
      { item_id: 1, kind: 'consultation', benefit: 'covered' },
      { item_id: 2, kind: 'blood_test', benefit: 'covered' },
      { item_id: 3, kind: 'mri', benefit: 'uncovered' },
    ],
  })
  const requestPromise = page.waitForRequest('**/api/coverage/candidates')
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회', exact: true }).click()
  const request = await requestPromise
  expect(request.postData()).toBe(snapshot)
  expect(await (await request.response())!.json()).toMatchObject({ rule_version: 'synthetic-v1', synthetic: true })
  await expect(page.getByLabel('보장 후보 조회 결과')).toBeVisible()
  await expect(page.getByRole('heading', { name: /선택한 치료의 보장 후보/ })).toBeFocused()
  await page.locator('.privacy-result-list').getByRole('button', { name: /복부 MRI/ }).click()
  await page.getByRole('button', { name: '원본의 해당 줄 확인' }).click()
  await expect(page.getByRole('heading', { name: '기기 내 원본', exact: true })).toBeFocused()
  await expect(page.getByLabel('선택한 치료의 원본 위치')).toBeVisible()
  await expect(page.locator('.privacy-original')).toContainText('480000 | 480000')
  await page.screenshot({ path: test.info().outputPath('privacy-result.png'), fullPage: true })
  await page.getByLabel('치료 항목 검토').screenshot({ path: test.info().outputPath('privacy-review.png') })
  await page.getByLabel('전송 내용 확인', { exact: true }).screenshot({ path: test.info().outputPath('privacy-transfer.png') })
  await page.getByLabel('보장 후보 조회 결과').screenshot({ path: test.info().outputPath('privacy-map.png') })
  const url = await page.locator('.privacy-paper img').getAttribute('src')
  await page.getByRole('button', { name: '세션 초기화' }).click()
  await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
  await expect(page.getByLabel('보장 후보 조회 결과')).toHaveCount(0)
  const state = await page.evaluate(async oldUrl => ({
    local: localStorage.length, session: sessionStorage.length,
    databases: await indexedDB.databases(), caches: await caches.keys(),
    objectUrlReleased: await fetch(oldUrl!).then(() => false, () => true),
  }), url)
  expect(state).toEqual({ local: 0, session: 0, databases: [], caches: [], objectUrlReleased: true })
  expect(requests.filter(request => request.body)).toHaveLength(1)
  for (const request of requests) expect(request.url + (request.body ?? '')).not.toContain(marker)
  expect(errors).toEqual([])
})

test('editing invalidates approval and mismatched totals block submission', async ({ page }) => {
  await page.goto('/')
  await loadPair(page)
  await prepare(page)
  await page.getByLabel('항목 1 환자 부담').fill('5551')
  await expect(page.getByLabel('전송 내용 확인', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('항목과 합계 검토 완료')).not.toBeChecked()
  await page.getByLabel('항목과 합계 검토 완료').check()
  await expect(page.getByRole('button', { name: '전송 내용 확인', exact: true })).toBeDisabled()
  await page.getByLabel('항목 1 환자 부담').fill('5550')
  await prepare(page)
  await page.getByLabel('비급여 MRI 가입 상태').selectOption('enrolled')
  await expect(page.getByLabel('전송 내용 확인', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('항목과 합계 검토 완료')).not.toBeChecked()
})

test('duplicate clicks, failed requests and reset during response are safe', async ({ page }) => {
  let calls = 0
  let pending: (() => void) | undefined
  await page.route('**/api/coverage/candidates', async route => {
    calls++
    await new Promise<void>(resolve => { pending = resolve })
    await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' }).catch(() => {})
  })
  await page.goto('/')
  await loadPair(page)
  await prepare(page)
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회', exact: true }).click()
  await expect(page.getByRole('button', { name: '조회 중…' })).toBeDisabled()
  expect(calls).toBe(1)
  pending!()
  await expect(page.getByRole('alert')).toContainText('조회에 실패')
  await expect(page.getByLabel('전송 내용 확인', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회', exact: true }).click()
  await expect(page.getByRole('button', { name: '조회 중…' })).toBeDisabled()
  await page.getByRole('button', { name: '세션 초기화' }).click()
  pending!()
  await expect(page.getByLabel('보장 후보 조회 결과')).toHaveCount(0)
  await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('bad or unsupported files stop locally without a request body', async ({ page }) => {
  const bodies: string[] = []
  page.on('request', request => { if (request.postData()) bodies.push(request.postData()!) })
  await page.goto('/')
  const input = page.getByLabel('영수증과 세부내역서 선택')
  await input.setInputFiles([sample('receipt.pdf')])
  await expect(page.getByText('1/2 선택됨', { exact: false })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
  await input.setInputFiles([sample('receipt.pdf'), sample('details.pdf'), sample('receipt.pdf')])
  await expect(page.getByRole('alert')).toContainText('최대 두 개')
  await input.setInputFiles([
    { name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a PDF ' + marker) },
    { name: 'details.pdf', mimeType: 'application/pdf', buffer: await readFile(sample('details.pdf')) },
  ])
  await expect(page.getByRole('alert')).toContainText('유효한 PDF')
  await input.setInputFiles([sample('receipt.pdf'), sample('receipt.pdf')])
  await expect(page.getByRole('alert')).toContainText('한 쌍')
  await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
  expect(bodies).toEqual([])
})

function minimalPdf(pageCount: number, text: string, script = '') {
  const pageIds = Array.from({ length: pageCount }, (_, index) => index + 5)
  const content = text ? `BT /F1 12 Tf 40 700 Td (${text}) Tj ET` : ''
  const objects = [
    `<< /Type /Catalog /Pages 2 0 R${script ? ` /OpenAction << /S /JavaScript /JS <${Buffer.from(script).toString('hex')}> >>` : ''} >>`,
    `<< /Type /Pages /Kids [${pageIds.map(id => `${id} 0 R`).join(' ')}] /Count ${pageCount} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    ...pageIds.map(() => '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>'),
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((object, index) => { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Root 1 0 R /Size ${objects.length + 1} >>\nstartxref\n${xref}\n%%EOF`
  return Buffer.from(pdf)
}

test('size, page and text limits are enforced before transfer', async ({ page }) => {
  const bodies: string[] = []
  page.on('request', request => { if (request.postData()) bodies.push(request.postData()!) })
  await page.goto('/')
  const input = page.getByLabel('영수증과 세부내역서 선택')
  const details = { name: 'details.pdf', mimeType: 'application/pdf', buffer: await readFile(sample('details.pdf')) }
  for (const [buffer, expected] of [
    [Buffer.alloc(10 * 1024 * 1024 + 1), '10 MiB'],
    [minimalPdf(11, 'test'), '10페이지'],
    [minimalPdf(1, ''), '텍스트를 읽을 수 없습니다'],
    [Buffer.from('%PDF-1.7\nbroken'), 'PDF를 읽을 수 없습니다'],
  ] as const) {
    await input.setInputFiles([{ name: 'unsupported.pdf', mimeType: 'application/pdf', buffer }, details])
    await expect(page.getByRole('alert')).toContainText(expected)
    await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
  }
  expect(bodies).toEqual([])
})

test('PDF document actions do not execute or contact a third party', async ({ page, baseURL }) => {
  const external: string[] = []
  const expectedOrigin = new URL(baseURL!).origin
  page.on('request', request => {
    if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== expectedOrigin) {
      external.push(request.url())
    }
  })
  await page.goto('/')
  await page.getByLabel('영수증과 세부내역서 선택').setInputFiles([
    { name: 'document-action.pdf', mimeType: 'application/pdf', buffer: minimalPdf(1, 'UNSUPPORTED',
      `globalThis.__pdfExecuted = true; fetch('https://example.invalid/${marker}')`) },
    { name: 'details.pdf', mimeType: 'application/pdf', buffer: await readFile(sample('details.pdf')) },
  ])
  await expect(page.getByRole('alert')).toContainText('한 쌍')
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__pdfExecuted)).toBeUndefined()
  expect(external).toEqual([])
})

test('a deselected source is replaced by the first result after a successful retry', async ({ page }) => {
  await page.goto('/')
  await loadPair(page)
  await expect(page.locator('.privacy-original')).toContainText('복부 MRI')
  await page.getByLabel('항목 3 조회 선택').uncheck()
  await prepare(page)
  const snapshot = await page.getByTestId('transfer-json').textContent()
  const path = '**/api/coverage/candidates'
  await page.route(path, route => route.fulfill({ status: 503 }), { times: 1 })
  const send = page.getByRole('button', { name: '확인한 항목으로 서버 조회', exact: true })
  await send.click()
  await expect(page.getByRole('alert')).toContainText('조회에 실패')
  const request = page.waitForRequest(path)
  await send.click()
  expect((await request).postData()).toBe(snapshot)
  await expect(page.getByLabel('보장 후보 조회 결과')).toBeVisible()
  await expect(page.locator('.privacy-result-detail h3')).toContainText('외래 진찰료')
  await expect(page.locator('.privacy-original')).toContainText('외래 진찰료')
})

test('mobile layout contains the table and blocks an empty selection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await loadPair(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  for (let index = 1; index <= 4; index++) await page.getByLabel(`항목 ${index} 조회 선택`).uncheck()
  await page.getByLabel('항목과 합계 검토 완료').check()
  await page.getByRole('button', { name: '전송 내용 확인', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('하나 이상')
  await expect(page.getByLabel('전송 내용 확인', { exact: true })).toHaveCount(0)
})

test('unclassified benefit can be checked without sending any enrollment', async ({ page }) => {
  await page.goto('/')
  await loadPair(page)
  for (const index of [1, 2, 4]) await page.getByLabel(`항목 ${index} 조회 선택`).uncheck()
  await page.getByLabel('항목 3 급여 구분').selectOption('unknown')
  await expect(page.getByLabel(/가입 상태/)).toHaveCount(0)
  await prepare(page)
  const sent = page.waitForRequest('**/api/coverage/candidates')
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회', exact: true }).click()
  expect((await sent).postDataJSON()).toEqual({
    rule_version: 'synthetic-v1', contract: {}, items: [{ item_id: 3, kind: 'mri', benefit: 'unknown' }],
  })
  await expect(page.locator('.privacy-result-detail')).toContainText('급여 구분 확인 후 적용 가능한 담보 확인')
  await expect(page.locator('.privacy-result-detail h3')).toContainText('적용 담보 검토 중')
})

test('sample button recovers from a failed fetch and starts review without a download or upload', async ({ page }) => {
  const requests: { method: string; path: string; body: string | null }[] = []
  let downloads = 0
  page.on('request', request => requests.push({
    method: request.method(), path: new URL(request.url()).pathname, body: request.postData(),
  }))
  page.on('download', () => { downloads++ })
  await page.route('**/samples/receipt.pdf', route => route.fulfill({ status: 503 }), { times: 1 })
  await page.goto('/')
  const start = page.getByRole('button', { name: '가상 샘플로 시작' })
  await start.click()
  await expect(page.getByRole('alert')).toContainText('가상 샘플을 읽지 못했습니다')
  requests.length = 0
  await start.click()
  await expect(page.getByRole('heading', { name: '어떤 보험으로 검토할까요?' })).toBeFocused()
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
  const pdfRequests = requests.filter(request => request.path.startsWith('/samples/'))
  expect(pdfRequests.map(request => request.path).sort()).toEqual(['/samples/details.pdf', '/samples/receipt.pdf'])
  expect(pdfRequests.every(request => request.method === 'GET' && request.body === null)).toBe(true)
  expect(requests.some(request => request.method === 'POST' || request.body)).toBe(false)
  expect(downloads).toBe(0)
})

test('stages individual PDFs and retains the valid file when replacing the invalid one', async ({ page }) => {
  const posts: string[] = []
  page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()) })
  await page.goto('/')
  const input = page.getByLabel('영수증과 세부내역서 선택')
  const files = page.getByRole('list', { name: '선택한 PDF' })
  await input.setInputFiles(sample('receipt.pdf'))
  await expect(files.getByText('receipt.pdf', { exact: true })).toBeVisible()
  await expect(page.getByText('1/2 선택됨', { exact: false })).toBeVisible()
  await input.setInputFiles({ name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('invalid') })
  await expect(page.getByRole('alert')).toContainText('유효한 PDF')
  await files.getByRole('button', { name: 'invalid.pdf 선택 해제' }).click()
  await expect(files.getByText('receipt.pdf', { exact: true })).toBeVisible()
  await expect(files.getByText('invalid.pdf', { exact: true })).toHaveCount(0)
  await input.setInputFiles(sample('details.pdf'))
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
  await expect(files.getByRole('button', { name: 'receipt.pdf 원본 보기' })).toBeVisible()
  await page.getByRole('button', { name: '세션 초기화' }).click()
  await expect(files).toHaveCount(0)
  await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
  expect(posts).toEqual([])
})

test('reset cancels a pending sample and leaves the picker ready for a new pair', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/samples/receipt.pdf', async route => {
    await gate
    await route.continue().catch(() => {})
  }, { times: 1 })
  await page.goto('/')
  const requested = page.waitForRequest('**/samples/receipt.pdf')
  await page.getByRole('button', { name: '가상 샘플로 시작' }).click()
  await requested
  await expect(page.getByText('가상 샘플을 불러오고 있습니다…')).toBeVisible()
  await page.getByRole('button', { name: '세션 초기화' }).click()
  release()
  await expect(page.getByRole('list', { name: '선택한 PDF' })).toHaveCount(0)
  await loadPair(page)
  await expect(page.getByRole('list', { name: '선택한 PDF' }).getByText('details.pdf', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('sample results explain the evidence and retain the successful request body', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '가상 샘플로 시작' }).click()
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
  await page.getByLabel('항목 4 급여 구분').selectOption('covered')
  await prepare(page)
  await expect(page.getByText('이 조회에서 보낸 정보', { exact: false })).toHaveCount(0)
  const sent = page.waitForRequest('**/api/coverage/candidates')
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회', exact: true }).click()
  const body = (await sent).postData()
  const results = page.getByLabel('보장 후보 조회 결과')
  await expect(results).toBeVisible()
  const detail = results.locator('.privacy-result-detail')
  await expect(detail).toContainText('복부 MRI → 비급여 MRI')
  await expect(detail).toContainText('비급여 · 문서 추출값')
  await expect(detail).toContainText('비급여 MRI · 미확인')
  await expect(detail).toContainText('세부내역서 1쪽')
  await expect(detail.getByRole('heading', { name: '다음 확인' })).toBeVisible()
  await results.getByRole('button', { name: /혈액 검사/ }).click()
  await expect(detail).toContainText('혈액 검사 → 질병급여')
  await expect(detail).toContainText('질병급여 · 가입')
  await results.getByRole('button', { name: /영양 주사/ }).click()
  await expect(detail).toContainText('급여 · 사용자 수정값')
  await expect(detail).toContainText('질병급여 · 가입')
  await detail.getByRole('button', { name: '원본의 해당 줄 확인' }).click()
  await expect(page.locator('.privacy-original')).toContainText('영양 주사 | 비급여')
  await page.getByRole('button', { name: '전송 확인 닫기' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await results.getByText('이 조회에서 보낸 정보', { exact: false }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  const receipt = await results.locator('.privacy-query-receipt pre').textContent()
  expect(receipt).toBe(body)
  for (const privateValue of [marker, '김하늘', 'total_won', 'patient_won', '.pdf']) {
    expect(receipt).not.toContain(privateValue)
  }
  await page.getByLabel('항목 4 조회 선택').uncheck()
  await expect(results).toHaveCount(0)
})
