import {createHash} from 'node:crypto';
import {readFile,writeFile,readdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = path.join(root,'report/provenance.json');
const digest = async p => createHash('sha256').update(await readFile(path.join(root,p))).digest('hex');
if(process.argv.includes('--check')) {
  const data=JSON.parse(await readFile(manifest,'utf8'));
  for(const [p,hash] of Object.entries(data.sha256)) {
    const rel=path.relative(root,path.resolve(root,p));
    if(rel==='..'||rel.startsWith('..'+path.sep)||path.isAbsolute(rel)||await digest(p)!==hash) throw new Error('Evidence fingerprint mismatch: '+p);
  }
  console.log(`Archived evidence verified: ${Object.keys(data.sha256).length} file fingerprints`);
} else {
  const files=['package.json','package-lock.json','report/results.json','report/evaluation.json'];
  for(const dir of ['src','fixture','tools','ui','tests']) for(const name of await readdir(path.join(root,dir))) if(/\.(mjs|html|css|js)$/.test(name)) files.push(dir+'/'+name);
  const data=JSON.parse(await readFile(path.join(root,'report/results.json'),'utf8'));
  const sha256={};for(const p of files.sort())sha256[p]=await digest(p);
  await writeFile(manifest,JSON.stringify({schemaVersion:1,scope:'Source, raw observations and independent evaluation. Screenshots and trace ZIP files remain local and are excluded from public uploads.',generatedAt:new Date().toISOString(),sha256},null,2)+'\n');
  console.log(`Evidence fingerprints saved: ${files.length} files`);
}
