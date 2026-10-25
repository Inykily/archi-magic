// Builds a self-contained 3D viewer page from a BIM JSON file.
// Usage: node build-viewer.mjs [in.json] [out.html]
//   in.json  default: the demo dataset
//   out.html default: next to in.json, same name + .viewer.html
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
// The skill's own copy (scripts/sync-shared-files.ps1 writes it from mods/am-bim-viewer/viewer),
// so the installed skill never reads above its plugin folder.
const viewerDir = resolve(here, '../viewer');
const { buildViewerHtml } = await import(pathToFileURL(resolve(viewerDir, 'build.mjs')).href);

const input = resolve(process.argv[2] || resolve(viewerDir, 'demo.json'));
const output = resolve(process.argv[3] || input.replace(/\.json$/i, '') + '.viewer.html');

const html = buildViewerHtml({
  template: readFileSync(resolve(viewerDir, 'template.html'), 'utf8'),
  core: readFileSync(resolve(viewerDir, 'viewer-core.mjs'), 'utf8'),
  data: JSON.parse(readFileSync(input, 'utf8')),
});
writeFileSync(output, html);
console.log(output);
