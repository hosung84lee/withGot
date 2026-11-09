const candidatesPath = '/api/coverage/candidates'
const maxBody = 32_768
const commonHeaders = {
  'Cache-Control': 'no-store',
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
}
const policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
  + "img-src 'self' blob: data:; font-src 'self' blob: data:; worker-src 'self' blob:; "
  + "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
const error = (status, code) => Response.json({ error: code }, { status, headers: commonHeaders })

const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const hasOnly = (value, keys) => isRecord(value) && Object.keys(value).every(key => keys.includes(key))
const integerBetween = (value, minimum, maximum) =>
  Number.isInteger(value) && value >= minimum && value <= maximum
const enrollments = ['enrolled', 'not_enrolled', 'unknown']
const kinds = ['consultation', 'blood_test', 'mri', 'injection']
const benefits = ['covered', 'uncovered', 'unknown']
const contractKeys = ['standard', 'mri', 'injection']

function coverageFor({ benefit, kind }) {
  return benefit !== 'covered' && (kind === 'mri' || kind === 'injection') ? kind : 'standard'
}

function validRequest(value) {
  if (!hasOnly(value, ['rule_version', 'contract', 'items']) || value.rule_version !== 'synthetic-v1'
    || !hasOnly(value.contract, contractKeys)
    || !Object.values(value.contract).every(enrollment => enrollments.includes(enrollment))
    || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 100) return false

  const ids = new Set()
  for (const item of value.items) {
    if (!hasOnly(item, ['item_id', 'kind', 'benefit', 'total_won', 'patient_won'])
      || !integerBetween(item.item_id, 1, 100) || ids.has(item.item_id)
      || !kinds.includes(item.kind) || !benefits.includes(item.benefit)
      || (item.benefit !== 'unknown' && !Object.hasOwn(value.contract, coverageFor(item)))) return false
    if (Object.hasOwn(item, 'total_won') || Object.hasOwn(item, 'patient_won')) {
      if (!integerBetween(item.total_won, 0, 100_000_000)
        || !integerBetween(item.patient_won, 0, item.total_won)) return false
    }
    ids.add(item.item_id)
  }
  return true
}

function candidate(item, contract) {
  const coverage = coverageFor(item)
  const enrollment = contract[coverage] ?? 'unknown'
  let status = 'missing_information'
  let check = '급여 구분 확인 후 적용 가능한 담보 확인'
  if (item.benefit !== 'unknown') {
    if (enrollment === 'not_enrolled') {
      status = 'not_enrolled'
      check = '사용자가 선택한 가상 계약에서 해당 담보 미가입'
    } else if (enrollment === 'unknown') {
      check = '담보 가입 여부와 급여 구분 확인'
    } else if (item.benefit === 'uncovered') {
      check = '치료 목적과 해당 특약의 실제 적용 조건 확인'
    } else {
      status = 'candidate'
      check = '공제·한도와 실제 적용 약관 확인'
    }
  }
  return { item_id: item.item_id, coverage, status, checks: [check] }
}

async function candidates(request, url) {
  if (url.search || request.headers.has('content-encoding')) return error(400, 'invalid_request')
  if (request.method !== 'POST') return error(405, 'method_not_allowed')
  if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') {
    return error(415, 'json_required')
  }
  if (!request.body) return error(422, 'invalid_request')
  const reader = request.body.getReader()
  const body = new Uint8Array(maxBody)
  let length = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      if (length + value.byteLength > maxBody) {
        await reader.cancel()
        return error(413, 'request_too_large')
      }
      body.set(value, length)
      length += value.byteLength
    }
    const payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body.subarray(0, length)))
    if (!validRequest(payload)) return error(422, 'invalid_request')
    return Response.json({
      rule_version: 'synthetic-v1', synthetic: true,
      items: payload.items.map(item => candidate(item, payload.contract)),
    }, { headers: commonHeaders })
  } catch {
    return error(422, 'invalid_request')
  } finally {
    reader.releaseLock()
  }
}

export default {
  fetch(request) {
    const url = new URL(request.url)
    const path = url.pathname
    if (path === candidatesPath) return candidates(request, url)
    if (path === '/api/health' && request.method === 'GET') {
      return Response.json({ status: 'ok', version: '0.1.0' }, { headers: commonHeaders })
    }
    if (path.startsWith('/api/') || !['GET', 'HEAD'].includes(request.method)) return error(404, 'not_found')

    const key = path === '/' ? '/index.html' : path
    if (!Object.hasOwn(assets, key)) return error(404, 'not_found')
    const { mime, base64 } = assets[key]
    const headers = { ...commonHeaders, 'Content-Type': mime, 'Content-Security-Policy': policy }
    return new Response(request.method === 'HEAD' ? null : Uint8Array.from(atob(base64), char => char.charCodeAt(0)), { headers })
  },
}
