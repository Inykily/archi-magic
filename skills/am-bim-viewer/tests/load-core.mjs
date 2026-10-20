// Loads the shipped viewer core, or a mutant named by AM_CORE_PATH.
import { pathToFileURL, fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
export const SHIPPED_CORE = resolve(here, '../../../mods/am-bim-viewer/viewer/viewer-core.mjs');
const path = process.env.AM_CORE_PATH || SHIPPED_CORE;
export const core = await import(pathToFileURL(path).href);
export const corePath = path;
