import {readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {evaluate} from './evaluate.mjs';

export function safeJson(value) { return JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026'); }
export async function buildReport(dir, {publicSnapshot=false}={}) {
  const data = JSON.parse(await readFile(path.join(dir, 'results.json'), 'utf8'));
  const template = await readFile(new URL('../ui/report.html', import.meta.url), 'utf8');
  const summary = evaluate(data, data.repetitions || 3);
  await writeFile(path.join(dir, 'index.html'), template.replace('/*__PROBE_DATA__*/null', safeJson({publicSnapshot,data, summary})), 'utf8');
  return summary;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const summary = await buildReport(path.resolve(process.argv[2] || 'report'),{publicSnapshot:process.argv.includes('--public')});
  console.log(JSON.stringify({report:'index.html',checks:summary.totalChecks,passed:summary.passed}));
}
