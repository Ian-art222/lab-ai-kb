export const LITERATURE_NOTE_KIND = 'literature_note'

export function stripHtml(s: string): string {
  return s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

export function notePreviewTitle(ann: { annotation_json?: Record<string, unknown> | null }): string {
  const j = (ann?.annotation_json || {}) as Record<string, unknown>
  const t = j.title
  if (typeof t === 'string' && t.trim()) return t.trim().slice(0, 80)
  const html = j.body_html
  if (typeof html === 'string' && html.trim()) {
    const plain = stripHtml(html)
    if (plain) return plain.slice(0, 80)
  }
  const tx = j.text
  if (typeof tx === 'string' && tx.trim()) return tx.trim().slice(0, 80)
  return '未命名笔记'
}

export function noteBodyHtmlFromJson(j: Record<string, unknown> | null | undefined): string {
  if (!j) return ''
  if (typeof j.body_html === 'string') return j.body_html
  if (typeof j.text === 'string') return `<p>${escapeHtml(j.text)}</p>`
  return ''
}

export function buildLiteratureNotePayload(opts: { title: string; bodyHtml: string; quoteFromPdf?: string }) {
  const title = opts.title.trim()
  const body = opts.bodyHtml || ''
  const out: Record<string, unknown> = {
    kind: LITERATURE_NOTE_KIND,
    title,
    body_html: body,
    content_format: 'html',
  }
  const q = opts.quoteFromPdf?.trim()
  if (q) out.quote_from_pdf = q
  return out
}
