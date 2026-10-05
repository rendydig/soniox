import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef, useState } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

const MIN_ZOOM = 1;
const MAX_ZOOM = 10;
const ZOOM_STEP = 0.25;

const clampZoom = (value) =>
    Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(value * 4) / 4));

/**
 * Enlarged, zoomable view of one screenshot.
 *
 * Fills the pane (position: fixed). Supports zoom in/out/reset, Ctrl+wheel
 * zoom, drag-to-pan when the image overflows, and prev/next navigation via the
 * side buttons or the Left/Right arrow keys (Escape closes).
 */
export const ScreenshotLightbox = ({ screenshots, index, onClose, onNavigate }) => {
    const [zoom, setZoom] = useState(1);
    const scrollRef = useRef(null);
    const imgRef = useRef(null);
    const dragMovedRef = useRef(false);
    const total = screenshots.length;
    const current = screenshots[index];

    // Reset the zoom whenever the shown image changes.
    useEffect(() => {
        setZoom(1);
    }, [index]);

    // Apply the zoom level to the image (mirrors mermaid-zoom's approach).
    useEffect(() => {
        const scroll = scrollRef.current;
        const img = imgRef.current;
        if (!scroll || !img) return;

        if (zoom === 1) {
            img.style.maxWidth = '';
            img.style.width = '';
            img.style.height = '';
        } else {
            const natural = img.naturalWidth || 680;
            const containerWidth = scroll.clientWidth || natural;
            const baseWidth = Math.min(natural, containerWidth);
            img.style.maxWidth = 'none';
            img.style.width = `${Math.round(baseWidth * zoom)}px`;
            img.style.height = 'auto';
        }

        const pannable =
            scroll.scrollWidth > scroll.clientWidth ||
            scroll.scrollHeight > scroll.clientHeight;
        scroll.classList.toggle('pannable', pannable);
    }, [zoom, index]);

    // Ctrl/Cmd + wheel zooms; a plain wheel keeps scrolling.
    useEffect(() => {
        const scroll = scrollRef.current;
        if (!scroll) return;
        const onWheel = (event) => {
            if (!event.ctrlKey && !event.metaKey) return;
            event.preventDefault();
            setZoom((value) => clampZoom(value + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP)));
        };
        scroll.addEventListener('wheel', onWheel, { passive: false });
        return () => scroll.removeEventListener('wheel', onWheel);
    }, []);

    // Drag to pan once the image overflows its container.
    useEffect(() => {
        const scroll = scrollRef.current;
        if (!scroll) return;
        let dragging = false;
        let startX = 0;
        let startY = 0;
        let startLeft = 0;
        let startTop = 0;

        const onDown = (event) => {
            if (event.button !== 0 || !scroll.classList.contains('pannable')) return;
            dragging = true;
            dragMovedRef.current = false;
            startX = event.clientX;
            startY = event.clientY;
            startLeft = scroll.scrollLeft;
            startTop = scroll.scrollTop;
            scroll.classList.add('panning');
            scroll.setPointerCapture(event.pointerId);
            event.preventDefault();
        };

        const onMove = (event) => {
            if (!dragging) return;
            const dx = event.clientX - startX;
            const dy = event.clientY - startY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMovedRef.current = true;
            scroll.scrollLeft = startLeft - dx;
            scroll.scrollTop = startTop - dy;
        };

        const onUp = (event) => {
            if (!dragging) return;
            dragging = false;
            scroll.classList.remove('panning');
            try {
                scroll.releasePointerCapture(event.pointerId);
            } catch (error) {
                /* pointer already released */
            }
        };

        scroll.addEventListener('pointerdown', onDown);
        scroll.addEventListener('pointermove', onMove);
        scroll.addEventListener('pointerup', onUp);
        scroll.addEventListener('pointercancel', onUp);
        return () => {
            scroll.removeEventListener('pointerdown', onDown);
            scroll.removeEventListener('pointermove', onMove);
            scroll.removeEventListener('pointerup', onUp);
            scroll.removeEventListener('pointercancel', onUp);
        };
    }, []);

    // Escape closes; Left/Right navigate.
    useEffect(() => {
        const onKey = (event) => {
            if (event.key === 'Escape') onClose();
            else if (event.key === 'ArrowLeft' && index > 0) onNavigate(index - 1);
            else if (event.key === 'ArrowRight' && index < total - 1) onNavigate(index + 1);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [index, total, onClose, onNavigate]);

    if (!current) return null;

    const zoomIn = () => setZoom((value) => clampZoom(value + ZOOM_STEP));
    const zoomOut = () => setZoom((value) => clampZoom(value - ZOOM_STEP));

    return html`
        <div class="screenshot-lightbox">
            <div class="screenshot-lightbox-toolbar">
                <span class="screenshot-lightbox-meta">
                    ${index + 1} / ${total} · ${new Date(current.timestamp).toLocaleTimeString()}
                </span>
                <div class="screenshot-lightbox-zoom">
                    <button
                        type="button"
                        class="screenshot-zoom-btn"
                        title="Zoom out"
                        aria-label="Zoom out"
                        disabled=${zoom <= MIN_ZOOM}
                        onClick=${zoomOut}
                    >−</button>
                    <span class="screenshot-lightbox-level">${Math.round(zoom * 100)}%</span>
                    <button
                        type="button"
                        class="screenshot-zoom-btn"
                        title="Zoom in"
                        aria-label="Zoom in"
                        disabled=${zoom >= MAX_ZOOM}
                        onClick=${zoomIn}
                    >+</button>
                    <button
                        type="button"
                        class="screenshot-zoom-btn"
                        title="Reset zoom"
                        aria-label="Reset zoom"
                        onClick=${() => setZoom(1)}
                    >⟲</button>
                </div>
                <button
                    type="button"
                    class="screenshot-lightbox-close"
                    title="Close"
                    aria-label="Close"
                    onClick=${onClose}
                >×</button>
            </div>
            <div class="screenshot-lightbox-body">
                <button
                    type="button"
                    class="screenshot-lightbox-nav prev"
                    title="Previous"
                    aria-label="Previous"
                    disabled=${index <= 0}
                    onClick=${() => onNavigate(index - 1)}
                >‹</button>
                <div
                    class="screenshot-lightbox-scroll"
                    ref=${scrollRef}
                    onClick=${(event) => {
                        const moved = dragMovedRef.current;
                        dragMovedRef.current = false;
                        if (!moved && event.target === event.currentTarget) onClose();
                    }}
                >
                    <img class="screenshot-lightbox-img" ref=${imgRef} src=${current.image} alt="Screenshot" />
                </div>
                <button
                    type="button"
                    class="screenshot-lightbox-nav next"
                    title="Next"
                    aria-label="Next"
                    disabled=${index >= total - 1}
                    onClick=${() => onNavigate(index + 1)}
                >›</button>
            </div>
        </div>
    `;
};
