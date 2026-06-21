/**
 * Safe markdown rendering for assistant output.
 *
 * The old chat rendered `{@html marked(content)}` with NO sanitization — an XSS
 * vector if any tool/model output contained markup. We render with `marked`
 * then strip dangerous tags/attributes. No new dependency: uses the DOM in the
 * browser/jsdom and a conservative regex fallback elsewhere.
 */
import { marked } from 'marked';

const DANGEROUS_TAGS = ['script', 'style', 'iframe', 'object', 'embed', 'link', 'meta', 'form', 'base'];

function sanitizeHtml(html: string): string {
	if (typeof DOMParser !== 'undefined') {
		try {
			const doc = new DOMParser().parseFromString(html, 'text/html');
			doc.querySelectorAll(DANGEROUS_TAGS.join(',')).forEach((n) => n.remove());
			doc.querySelectorAll('*').forEach((el) => {
				for (const attr of Array.from(el.attributes)) {
					const name = attr.name.toLowerCase();
					const value = attr.value || '';
					if (name.startsWith('on')) {
						el.removeAttribute(attr.name);
					} else if ((name === 'href' || name === 'src') && /^\s*(javascript|data|vbscript):/i.test(value)) {
						el.removeAttribute(attr.name);
					}
				}
			});
			return doc.body.innerHTML;
		} catch {
			// fall through to regex fallback
		}
	}
	return html
		.replace(/<\/?(?:script|style|iframe|object|embed|link|meta|form|base)\b[^>]*>/gi, '')
		.replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
		.replace(/\son\w+\s*=\s*'[^']*'/gi, '')
		.replace(/(?:javascript|vbscript):/gi, '');
}

export function renderMarkdown(src: string): string {
	const raw = src ?? '';
	let html: string;
	try {
		html = marked.parse(raw, { async: false }) as string;
	} catch {
		// If markdown parsing fails, fall back to escaped plain text.
		const div = typeof document !== 'undefined' ? document.createElement('div') : null;
		if (div) {
			div.textContent = raw;
			return div.innerHTML;
		}
		return raw.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c] as string));
	}
	return sanitizeHtml(html);
}
