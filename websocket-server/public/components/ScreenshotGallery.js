import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef, useState } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { ScreenshotLightbox } from './ScreenshotLightbox.js';

const html = htm.bind(h);

/** 4-column grid of screenshots captured with ALT+SHIFT+K; click to enlarge. */
export const ScreenshotGallery = ({ screenshots }) => {
    const galleryRef = useRef(null);
    const [openId, setOpenId] = useState(null);
    const count = screenshots ? screenshots.length : 0;

    useEffect(() => {
        if (galleryRef.current) {
            galleryRef.current.scrollTop = galleryRef.current.scrollHeight;
        }
    }, [count]);

    // Close the lightbox if the shown screenshot is cleared or removed.
    useEffect(() => {
        if (openId !== null && !screenshots.some((s) => s.id === openId)) {
            setOpenId(null);
        }
    }, [screenshots, openId]);

    if (count === 0) return null;

    const openIndex = screenshots.findIndex((s) => s.id === openId);

    return html`
        <div class="screenshot-gallery" ref=${galleryRef}>
            <div class="screenshot-gallery-header">
                <span>Screenshots (${count})</span>
                <span class="screenshot-hint">ALT+CTRL+SHIFT+K clears</span>
            </div>
            <div class="screenshot-grid">
                ${screenshots.map((s) => html`
                    <button
                        type="button"
                        class="screenshot-thumb"
                        key=${s.id}
                        title=${new Date(s.timestamp).toLocaleTimeString()}
                        onClick=${() => setOpenId(s.id)}
                    >
                        <img class="screenshot-thumb-img" src=${s.image} alt="Screenshot" />
                    </button>
                `)}
            </div>
            ${openIndex >= 0 && html`
                <${ScreenshotLightbox}
                    screenshots=${screenshots}
                    index=${openIndex}
                    onClose=${() => setOpenId(null)}
                    onNavigate=${(nextIndex) => setOpenId(screenshots[nextIndex].id)}
                />
            `}
        </div>
    `;
};
