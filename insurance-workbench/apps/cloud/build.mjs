import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { dirname, extname, join } from 'node:path'

const [web, output] = process.argv.slice(2)
if (!web || !output) throw new Error('Usage: node apps/cloud/build.mjs <web-build> <worker-output>')

const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.pdf': 'application/pdf',
  '.zip': 'application/zip', '.sha256': 'text/plain; charset=utf-8',
}

async function collect(folder, prefix = '') {
  const entries = await readdir(folder, { withFileTypes: true })
  const pairs = []
  for (const entry of entries) {
    const path = join(folder, entry.name)
    const url = `${prefix}/${encodeURIComponent(entry.name)}`
    if (entry.isDirectory()) {
      pairs.push(...await collect(path, url))
    } else {
      const mime = types[extname(entry.name)]
      if (!entry.isFile() || !mime) throw new Error(`Unsupported deploy asset: ${url}`)
      pairs.push([url, { mime, base64: (await readFile(path)).toString('base64') }])
    }
  }
  return pairs
}

const assets = Object.fromEntries(await collect(web))
if (!assets['/index.html']) throw new Error('The web build is missing index.html')
const worker = await readFile(new URL('./worker.mjs', import.meta.url), 'utf8')
const entry = join(output, 'server', 'index.js')
await mkdir(dirname(entry), { recursive: true })
await writeFile(entry, `const assets = ${JSON.stringify(assets)};\n${worker}`)
