import { h, render } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';
import { App } from './components/App.js';

const html = htm.bind(h);

render(
    html`<${App} hideControlType="hide_live_window" />`,
    document.getElementById('live-root')
);
