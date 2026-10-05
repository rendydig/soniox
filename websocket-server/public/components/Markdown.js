import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { marked } from 'https://esm.sh/marked@12.0.0';
import DOMPurify from 'https://esm.sh/dompurify@3.0.9';
import hljs from 'https://esm.sh/highlight.js@11.9.0/lib/common';
import { decorate } from './mermaid-zoom.js';

const html = htm.bind(h);

/** Lazily load mermaid the first time a diagram is actually present. */
let mermaidPromise = null;

const getMermaid = () => {
    if (!mermaidPromise) {
        mermaidPromise = import('https://esm.sh/mermaid@12.0.0').then((mod) => {
            const mermaid = mod.default;
            mermaid.initialize({
                startOnLoad: false,
                securityLevel: 'strict',
                theme: 'neutral'
            });
            return mermaid;
        });
    }
    return mermaidPromise;
};

let renderSeq = 0;

/** Mermaid rejects with a plain { str, message, hash } object, not an Error. */
const errorMessage = (error) => {
    if (!error) return 'Unknown error';
    if (typeof error === 'string') return error;
    if (error.message) return error.message;
    if (error.str) return error.str;
    try {
        return JSON.stringify(error);
    } catch (stringifyError) {
        return String(error);
    }
};

/**
 * Quote node labels containing characters Mermaid reads as syntax
 * (parentheses, braces, ampersands, angle brackets, hash).
 */
const repairMermaid = (source) =>
    source.replace(/(\[[^\n\]]*?\]|\{[^\n}]*?\})/g, (token) => {
        const inner = token.slice(1, -1);
        if (!/[()&<>#]/.test(inner)) return token;
        if (/^\s*".*"\s*$/.test(inner)) return token;
        // Leave shape delimiters such as [(Database)] or [[Sub]] untouched.
        if (/^[(\[]/.test(inner.trim()) && /[)\]]$/.test(inner.trim())) return token;
        return `${token[0]}"${inner.trim()}"${token[token.length - 1]}`;
    });

const isValidDiagram = async (mermaid, source) => {
    try {
        const result = await mermaid.parse(source, { suppressErrors: true });
        return result !== false;
    } catch (error) {
        return false;
    }
};

const mermaidFallback = (source) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'mermaid-fallback';

    const note = document.createElement('div');
    note.className = 'markdown-error';
    note.textContent = 'Diagram could not be rendered. Source:';

    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = source;
    pre.appendChild(code);

    wrapper.append(note, pre);
    return wrapper;
};

const renderMermaid = async (container, token) => {
    const blocks = container.querySelectorAll('code.language-mermaid');
    if (blocks.length === 0) return;

    const diagrams = Array.from(blocks).map((code) => {
        const diagram = document.createElement('div');
        diagram.className = 'mermaid';
        diagram.textContent = code.textContent || '';
        (code.closest('pre') || code).replaceWith(diagram);
        return diagram;
    });

    let mermaid;
    try {
        mermaid = await getMermaid();
    } catch (error) {
        console.error('[Markdown] Failed to load mermaid:', errorMessage(error));
        diagrams.forEach((node) => node.replaceWith(mermaidFallback(node.textContent)));
        return;
    }

    for (const node of diagrams) {
        // A newer render replaced this content while mermaid was loading.
        if (container.dataset.renderToken !== String(token)) return;

        const source = node.textContent || '';
        if (!(await isValidDiagram(mermaid, source))) {
            const repaired = repairMermaid(source);
            if (repaired !== source && (await isValidDiagram(mermaid, repaired))) {
                node.textContent = repaired;
            }
        }

        try {
            await mermaid.run({ nodes: [node] });
        } catch (error) {
            console.error('[Markdown] Mermaid render failed:', errorMessage(error));
            node.replaceWith(mermaidFallback(source));
        }
    }

    if (container.dataset.renderToken !== String(token)) return;
    decorate(container);
};

/** Render markdown text into an existing element as sanitized HTML. */
export const renderMarkdown = (el, text) => {
    if (!el) return;

    const token = ++renderSeq;
    el.dataset.renderToken = String(token);

    // Gemini sometimes glues a fenced block onto a header line ("Code: ```mermaid").
    // CommonMark only opens a fence at line start, so split it onto its own line.
    const normalized = (text || '').replace(
        /^([^\n`]*[^\s`])[ \t]*(`{3,}[^\n`]*)$/gm,
        '$1\n$2'
    );
    const rawHtml = marked.parse(normalized, { gfm: true });
    el.innerHTML = DOMPurify.sanitize(rawHtml, { ADD_ATTR: ['class'] });

    el.querySelectorAll('pre code').forEach((block) => {
        if (block.classList.contains('language-mermaid')) return;
        const hasLanguage = Array.from(block.classList).some((name) => name.startsWith('language-'));
        if (!hasLanguage) return;
        try {
            hljs.highlightElement(block);
        } catch (error) {
            console.error('[Markdown] Highlight failed:', error);
        }
    });

    return renderMermaid(el, token);
};

export const Markdown = ({ text }) => {
    const ref = useRef(null);

    useEffect(() => {
        renderMarkdown(ref.current, text);
    }, [text]);

    return html`<div class="markdown-body" ref=${ref}></div>`;
};
