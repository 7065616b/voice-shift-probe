import {readFile, writeFile, stat} from 'node:fs/promises';
import path from 'node:path';
import {evaluate} from './evaluate.mjs';
const source = path.resolve(process.argv[2] || 'report/results.json');
const data = JSON.parse(await readFile(source, 'utf8'));
const evaluation = evaluate(data, Number(process.env.PROBE_REPETITIONS || 3));
const root = path.dirname(source);
for (const c of data.cases || []) {
  const required = ['before','after', ...(c.status === 'violation' || c.status === 'error' ? ['trace'] : [])];
  for (const name of required) {
    const ref = c.artifacts?.[name];
    if (typeof ref !== 'string' || !ref.startsWith('artifacts/')) { evaluation.issues.push(`Missing ${name}: ${c.id}`); continue; }
    const target = path.resolve(root, ref), relative = path.relative(root, target);
    if (relative === '..' || relative.startsWith('..'+path.sep) || path.isAbsolute(relative)) { evaluation.issues.push(`Artifact outside report: ${c.id}`); continue; }
    try { const info = await stat(target); if (!info.isFile() || !info.size) throw new Error('Empty/non-file'); }
    catch { evaluation.issues.push(`Artifact unreadable: ${c.id}/${name}`); }
  }
}
evaluation.artifactChecks = 'All screenshots and required traces must exist and be nonempty';
evaluation.passed = evaluation.issues.length === 0;
await writeFile(path.join(path.dirname(source), 'evaluation.json'), JSON.stringify(evaluation, null, 2)+'\n');
console.log(JSON.stringify(evaluation, null, 2));
if (!evaluation.passed) process.exitCode = 1;
