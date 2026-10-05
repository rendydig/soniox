/**
 * Zoom / pan controls for rendered Mermaid diagrams.
 *
 * Each `.mermaid` node (containing a rendered <svg>) is wrapped with a toolbar
 * (zoom out / level / zoom in / reset) and a scroll box. The zoom level is kept
 * at module scope so it persists across diagram re-renders.
 */

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

/** Current zoom level (1 = fit to width). Persists across diagrams. */
let zoomLevel = 1;

const ICON_MINUS =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">' +
    '<path d="M3.5 8h9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

const ICON_PLUS =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">' +
    '<path d="M3.5 8h9M8 3.5v9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

const ICON_RESET =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">' +
    '<path d="M13 8a5 5 0 1 1-1.46-3.54" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
    '<path d="M13 2.5v3h-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const clampLevel = (level) =>
    Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(level * 4) / 4));

const getNaturalWidth = (svg) => {
    const box = svg.viewBox && svg.viewBox.baseVal;
    if (box && box.width) return box.width;
    const attr = parseFloat(svg.getAttribute('width'));
    if (attr) return attr;
    return svg.getBoundingClientRect().width;
};

const updatePannable = (scroll) => {
    const pannable =
        scroll.scrollWidth > scroll.clientWidth ||
        scroll.scrollHeight > scroll.clientHeight;
    scroll.classList.toggle('pannable', pannable);
};

const applyZoom = (scroll, level) => {
    const svg = scroll.querySelector('.mermaid svg');
    if (!svg) return;

    if (level === 1) {
        // Fall back to the CSS fit (max-width: 100%) so it stays responsive.
        svg.style.maxWidth = '';
        svg.style.width = '';
        svg.style.height = '';
    } else {
        const natural = getNaturalWidth(svg);
        const containerWidth =
            scroll.clientWidth || scroll.getBoundingClientRect().width || natural;
        const baseWidth = Math.min(natural, containerWidth);
        svg.style.maxWidth = 'none';
        svg.style.width = `${Math.round(baseWidth * level)}px`;
        svg.style.height = 'auto';
    }

    updatePannable(scroll);
};

const syncWrap = (wrap) => {
    const scroll = wrap.querySelector('.mermaid-scroll');
    if (scroll) applyZoom(scroll, zoomLevel);

    const label = wrap.querySelector('.mermaid-zoom-level');
    if (label) label.textContent = `${Math.round(zoomLevel * 100)}%`;

    wrap.querySelectorAll('button[data-action]').forEach((btn) => {
        if (btn.dataset.action === 'in') btn.disabled = zoomLevel >= MAX_ZOOM;
        else if (btn.dataset.action === 'out') btn.disabled = zoomLevel <= MIN_ZOOM;
    });
};

const setLevel = (level) => {
    zoomLevel = clampLevel(level);
    document.querySelectorAll('.mermaid-wrap').forEach(syncWrap);
};

const enableDragPan = (scroll) => {
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let startTop = 0;

    scroll.addEventListener('pointerdown', (event) => {
        if (event.button !== 0 || !scroll.classList.contains('pannable')) return;
        dragging = true;
        startX = event.clientX;
        startY = event.clientY;
        startLeft = scroll.scrollLeft;
        startTop = scroll.scrollTop;
        scroll.classList.add('panning');
        scroll.setPointerCapture(event.pointerId);
        event.preventDefault();
    });

    scroll.addEventListener('pointermove', (event) => {
        if (!dragging) return;
        scroll.scrollLeft = startLeft - (event.clientX - startX);
        scroll.scrollTop = startTop - (event.clientY - startY);
    });

    const endDrag = (event) => {
        if (!dragging) return;
        dragging = false;
        scroll.classList.remove('panning');
        try {
            scroll.releasePointerCapture(event.pointerId);
        } catch (error) {
            /* pointer already released */
        }
    };

    scroll.addEventListener('pointerup', endDrag);
    scroll.addEventListener('pointercancel', endDrag);
};

const makeButton = (action, title, icon) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'mermaid-zoom-btn';
    button.dataset.action = action;
    button.title = title;
    button.setAttribute('aria-label', title);
    button.innerHTML = icon;
    return button;
};

const wrapDiagram = (node) => {
    if (node.closest('.mermaid-wrap') || !node.querySelector('svg')) return;

    const wrap = document.createElement('div');
    wrap.className = 'mermaid-wrap';

    const toolbar = document.createElement('div');
    toolbar.className = 'mermaid-toolbar';

    const label = document.createElement('span');
    label.className = 'mermaid-zoom-level';

    toolbar.append(
        makeButton('out', 'Zoom out', ICON_MINUS),
        label,
        makeButton('in', 'Zoom in', ICON_PLUS),
        makeButton('reset', 'Reset zoom', ICON_RESET)
    );

    const scroll = document.createElement('div');
    scroll.className = 'mermaid-scroll';

    node.parentNode.insertBefore(wrap, node);
    scroll.appendChild(node);
    wrap.appendChild(toolbar);
    wrap.appendChild(scroll);

    toolbar.addEventListener('click', (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button || button.disabled) return;
        if (button.dataset.action === 'in') setLevel(zoomLevel + ZOOM_STEP);
        else if (button.dataset.action === 'out') setLevel(zoomLevel - ZOOM_STEP);
        else setLevel(1);
    });

    enableDragPan(scroll);
    syncWrap(wrap);
};

/** Wrap every rendered diagram inside `container` with zoom/pan controls. */
export const decorate = (container) => {
    if (!container) return;
    container.querySelectorAll('.mermaid').forEach(wrapDiagram);
};
