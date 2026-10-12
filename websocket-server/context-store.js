/**
 * Context store: the single owner of the Host/Speaker context files.
 *
 * The desktop app is only a WebSocket client of this server, so this module
 * holds the whole truth about which context file each role uses: the selection
 * (a path — the file may live anywhere, inside or outside the repo), a
 * 10-entry re-select history, and the file contents the panes render and the
 * Python AI worker mirrors in memory.
 *
 * Guarantees:
 *   - Files are never created by a save: `save()` only overwrites a file that
 *     already exists and is the current selection for that role.
 *   - A missing or oversized file is not an error: its contents become `""`
 *     (no context) and `problems[role]` says why, so the pane can tell the user
 *     which path to fix without anything crashing.
 *   - Every write is atomic (temp file + rename), so a reader never sees a
 *     half-written file.
 *   - `onExternalChange` fires only for changes this module did not make
 *     (e.g. the file edited in VS Code), deduplicated by a content signature —
 *     so a save cannot bounce back as a broadcast loop.
 */

const fs = require('fs');
const fsp = fs.promises;
const path = require('path');

const REPO_ROOT = path.join(__dirname, '..');
const STATE_PATH = path.join(REPO_ROOT, 'context_state.json');

const ROLES = ['host', 'speaker'];
const HISTORY_MAX = 10;
const MAX_CONTEXT_BYTES = 64 * 1024;
const ALLOWED_EXTENSIONS = new Set(['.txt', '.md']);
const WATCH_DEBOUNCE_MS = 250;

let state = emptyState();
// Signature of the last state broadcast, so the watcher can tell "someone else
// changed a file" from "we just wrote it ourselves".
let lastSignature = '';
// dir path -> fs.FSWatcher
const watchers = new Map();
let watchTimer = null;
let externalChangeCallback = null;

function emptyState() {
  return {
    selection: { host: null, speaker: null },
    history: { host: [], speaker: [] },
    last_dir: { host: null, speaker: null },
  };
}

// --- paths ----------------------------------------------------------------

/** Stored paths are repo-relative when inside the repo, absolute otherwise. */
function resolvePath(stored) {
  if (!stored) return null;
  return path.isAbsolute(stored) ? path.normalize(stored) : path.resolve(REPO_ROOT, stored);
}

function storePath(absolute) {
  const abs = path.resolve(absolute);
  const rel = path.relative(REPO_ROOT, abs);
  const inside = rel && !rel.startsWith('..') && !path.isAbsolute(rel);
  return inside ? rel : abs;
}

function extensionOk(target) {
  return ALLOWED_EXTENSIONS.has(path.extname(target).toLowerCase());
}

// --- state file -----------------------------------------------------------

function loadState() {
  let disk = null;
  try {
    disk = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8'));
  } catch (error) {
    disk = null; // absent or unreadable: start from defaults
  }
  state = emptyState();
  if (disk && typeof disk === 'object') {
    for (const role of ROLES) {
      const selected = disk.selection && disk.selection[role];
      if (typeof selected === 'string' && selected.trim()) {
        state.selection[role] = selected.trim();
      }
      const history = disk.history && disk.history[role];
      if (Array.isArray(history)) {
        state.history[role] = history
          .filter((entry) => typeof entry === 'string' && entry.trim())
          .map((entry) => entry.trim())
          .slice(0, HISTORY_MAX);
      }
      // Only keep a remembered folder that still exists: the Browse/New dialogs
      // would otherwise open in a directory the user has since deleted.
      const lastDir = disk.last_dir && disk.last_dir[role];
      if (typeof lastDir === 'string' && lastDir.trim() && fs.existsSync(lastDir.trim())) {
        state.last_dir[role] = lastDir.trim();
      }
    }
  }
}

async function saveState() {
  const payload = JSON.stringify(state, null, 2);
  const tmp = STATE_PATH + '.tmp';
  try {
    await fsp.writeFile(tmp, payload, 'utf-8');
    await fsp.rename(tmp, STATE_PATH);
  } catch (error) {
    console.error('[Context] Failed to write state:', error.message);
  }
}

/**
 * Seed values for the very first run, from SELF_CONTEXT_FILE /
 * SPEAKER_CONTEXT_FILE. `process.env` is used when the app spawned this server
 * (dotenv exports it), and `.env` is parsed directly otherwise, so the seed
 * does not depend on how the server was started.
 */
function envContextPaths() {
  const fromFile = parseDotEnv();
  const pick = (name) => process.env[name] || fromFile[name] || null;
  return { host: pick('SELF_CONTEXT_FILE'), speaker: pick('SPEAKER_CONTEXT_FILE') };
}

function parseDotEnv() {
  const values = {};
  let raw = '';
  try {
    raw = fs.readFileSync(path.join(REPO_ROOT, '.env'), 'utf-8');
  } catch (error) {
    return values;
  }
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key) values[key] = value;
  }
  return values;
}

// --- validation -----------------------------------------------------------

function validateTarget(target, { mustExist }) {
  if (!target) return { ok: false, status: 'invalid', message: 'No file path given' };
  if (!extensionOk(target)) {
    return { ok: false, status: 'invalid', message: 'Only .txt and .md files are supported' };
  }
  let stats;
  try {
    stats = fs.statSync(target);
  } catch (error) {
    if (error.code === 'ENOENT' && !mustExist) return { ok: true };
    return { ok: false, status: 'missing', message: 'File not found' };
  }
  if (!stats.isFile()) {
    return { ok: false, status: 'invalid', message: 'Not a regular file' };
  }
  if (stats.size > MAX_CONTEXT_BYTES) {
    return { ok: false, status: 'too_large', message: 'File is larger than 64 KB' };
  }
  return { ok: true };
}

/** Read a context file; a missing file is "no context", never an error. */
async function readTarget(target) {
  try {
    const stats = await fsp.stat(target);
    if (stats.size > MAX_CONTEXT_BYTES) {
      return { text: '', problem: 'too_large', mtimeMs: stats.mtimeMs };
    }
    const text = await fsp.readFile(target, 'utf-8');
    return { text, problem: null, mtimeMs: stats.mtimeMs };
  } catch (error) {
    return { text: '', problem: 'missing', mtimeMs: 0 };
  }
}

// --- snapshot -------------------------------------------------------------

async function buildPayload() {
  const payload = {
    selection: {},
    problems: {},
    history: {},
    contents: {},
    revision: {},
  };
  for (const role of ROLES) {
    const stored = state.selection[role] || null;
    payload.selection[role] = stored;
    payload.history[role] = (state.history[role] || []).slice(0, HISTORY_MAX);
    if (!stored) {
      payload.problems[role] = null;
      payload.contents[role] = '';
      payload.revision[role] = 0;
      continue;
    }
    const read = await readTarget(resolvePath(stored));
    payload.problems[role] = read.problem;
    payload.contents[role] = read.problem ? '' : read.text;
    payload.revision[role] = Math.round(read.mtimeMs);
  }
  return payload;
}

function signature(payload) {
  return JSON.stringify([
    payload.selection,
    payload.problems,
    payload.history,
    payload.contents,
    payload.revision,
  ]);
}

/** Read-only snapshot for a `context_get` reply. */
async function getState() {
  return buildPayload();
}

/** Every mutation returns `{ok, payload}` or `{ok: false, status, message}`. */
async function afterMutation() {
  const payload = await buildPayload();
  lastSignature = signature(payload);
  refreshWatchers();
  return { ok: true, payload };
}

// --- mutations ------------------------------------------------------------

async function select(role, stored) {
  if (!ROLES.includes(role)) return { ok: false, status: 'invalid', message: 'Unknown role' };
  const target = resolvePath(stored);
  const check = validateTarget(target, { mustExist: true });
  if (!check.ok) return check;
  const value = storePath(target);
  state.selection[role] = value;
  state.last_dir[role] = path.dirname(target);
  state.history[role] = [value, ...(state.history[role] || []).filter((p) => p !== value)].slice(
    0,
    HISTORY_MAX
  );
  await saveState();
  return afterMutation();
}

async function clearSelection(role) {
  if (!ROLES.includes(role)) return { ok: false, status: 'invalid', message: 'Unknown role' };
  state.selection[role] = null;
  await saveState();
  return afterMutation();
}

async function newFile(role, stored) {
  if (!ROLES.includes(role)) return { ok: false, status: 'invalid', message: 'Unknown role' };
  const target = resolvePath(stored);
  const check = validateTarget(target, { mustExist: false });
  if (!check.ok) return check;
  const parent = path.dirname(target);
  let parentStats;
  try {
    parentStats = await fsp.stat(parent);
  } catch (error) {
    return { ok: false, status: 'invalid', message: 'Folder does not exist' };
  }
  if (!parentStats.isDirectory()) {
    return { ok: false, status: 'invalid', message: 'Not a folder' };
  }
  try {
    // 'wx' fails when the file exists, so an existing file is never truncated.
    await fsp.writeFile(target, '', { flag: 'wx' });
  } catch (error) {
    if (error.code !== 'EEXIST') {
      return { ok: false, status: 'invalid', message: 'Could not create the file' };
    }
  }
  return select(role, stored);
}

async function save(role, stored, text) {
  if (!ROLES.includes(role)) return { ok: false, status: 'invalid', message: 'Unknown role' };
  const selected = state.selection[role];
  if (!selected) {
    return { ok: false, status: 'no_target', message: 'No context file selected' };
  }
  const target = resolvePath(stored);
  // A save may only overwrite the role's current selection.
  if (target !== resolvePath(selected)) {
    return { ok: false, status: 'invalid', message: 'That file is not the selected context' };
  }
  const check = validateTarget(target, { mustExist: true });
  if (!check.ok) return check;
  const body = typeof text === 'string' ? text : '';
  if (Buffer.byteLength(body, 'utf-8') > MAX_CONTEXT_BYTES) {
    return { ok: false, status: 'too_large', message: 'Content is larger than 64 KB' };
  }
  const tmp = target + '.tmp';
  try {
    await fsp.writeFile(tmp, body, 'utf-8');
    await fsp.rename(tmp, target);
  } catch (error) {
    return { ok: false, status: 'invalid', message: 'Could not write the file' };
  }
  return afterMutation();
}

async function forget(role, stored) {
  if (!ROLES.includes(role)) return { ok: false, status: 'invalid', message: 'Unknown role' };
  const value = storePath(resolvePath(stored));
  state.history[role] = (state.history[role] || []).filter((entry) => entry !== value);
  await saveState();
  return afterMutation();
}

// --- watchers -------------------------------------------------------------

function watchedDirs() {
  const dirs = new Set();
  for (const role of ROLES) {
    const entries = [state.selection[role], ...(state.history[role] || [])];
    for (const entry of entries) {
      if (!entry) continue;
      const target = resolvePath(entry);
      if (target) dirs.add(path.dirname(target));
    }
  }
  return dirs;
}

/** Keep one watcher per folder any selected/recent file lives in. */
function refreshWatchers() {
  const wanted = watchedDirs();
  for (const [dir, watcher] of watchers) {
    if (wanted.has(dir)) continue;
    try {
      watcher.close();
    } catch (error) {
      // already gone
    }
    watchers.delete(dir);
  }
  for (const dir of wanted) {
    if (watchers.has(dir)) continue;
    try {
      const watcher = fs.watch(dir, () => scheduleWatchCheck());
      watcher.on('error', () => {
        try {
          watcher.close();
        } catch (error) {
          // already gone
        }
        watchers.delete(dir);
      });
      watchers.set(dir, watcher);
    } catch (error) {
      // Folder vanished between listing and watching: ignore, the next refresh retries.
    }
  }
}

function scheduleWatchCheck() {
  if (watchTimer) clearTimeout(watchTimer);
  watchTimer = setTimeout(async () => {
    watchTimer = null;
    try {
      const payload = await buildPayload();
      const current = signature(payload);
      if (current === lastSignature) return; // our own write, or a no-op touch
      lastSignature = current;
      refreshWatchers();
      if (externalChangeCallback) externalChangeCallback(payload);
    } catch (error) {
      console.error('[Context] Watch check failed:', error.message);
    }
  }, WATCH_DEBOUNCE_MS);
}

function onExternalChange(callback) {
  externalChangeCallback = callback;
}

// --- init -----------------------------------------------------------------

async function init() {
  loadState();
  let changed = false;
  const firstRun = !fs.existsSync(STATE_PATH);
  if (firstRun) {
    // Seed the selection from .env so an existing setup keeps working.
    const seeded = envContextPaths();
    for (const role of ROLES) {
      const stored = seeded[role];
      if (!stored) continue;
      const target = resolvePath(stored);
      if (!validateTarget(target, { mustExist: true }).ok) continue;
      state.selection[role] = storePath(target);
      state.last_dir[role] = path.dirname(target);
      state.history[role] = [state.selection[role]];
      changed = true;
    }
  }
  if (changed) await saveState();
  refreshWatchers();
  lastSignature = signature(await buildPayload());
  return firstRun;
}

module.exports = {
  REPO_ROOT,
  STATE_PATH,
  ROLES,
  HISTORY_MAX,
  MAX_CONTEXT_BYTES,
  init,
  getState,
  select,
  clearSelection,
  newFile,
  save,
  forget,
  onExternalChange,
  resolvePath,
  storePath,
};
