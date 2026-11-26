import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const files=new Map();
for(const line of fs.readFileSync(path.join(root,'Dockerfile'),'utf8').split(/\r?\n/)){
 if(!line.startsWith('COPY '))continue;
 const parts=line.slice(5).trim().split(/\s+/),destination=parts.pop();
 assert(parts.every(p=>!p.startsWith('--')&&!/[\[*?]/.test(p)), 'Update manifest parser for new Docker COPY syntax');
 for(const source of parts)files.set(path.posix.normalize(path.posix.join(destination,path.posix.basename(source))),source);
}
const rules=fs.readFileSync(path.join(root,'.dockerignore'),'utf8').split(/\r?\n/).map(s=>s.trim()).filter(s=>s&&!s.startsWith('#'));
function included(name){
 let yes=true;
 for(const rule of rules){
  const allow=rule.startsWith('!'),pattern=allow?rule.slice(1):rule;
  assert(pattern==='**'||!/[?*\[]/.test(pattern),'Update manifest parser for new dockerignore syntax');
  if(pattern==='**'||pattern===name||pattern===name+'/')yes=allow;
 }
 return yes;
}
test('every Docker COPY source exists and is included in the build context',()=>{
 for(const source of files.values()){
  assert(fs.statSync(path.join(root,source)).isFile(),source);
  assert(included(source),`${source} is excluded from Docker context`);
  const parent=path.posix.dirname(source);
  if(parent!=='.')assert(included(parent),`${parent} directory is excluded from Docker context`);
 }
});
test('Docker API and workbook entry points contain their full static module dependency closure',()=>{
 const queue=['api/server.mjs','export_dual_quote_workbook.mjs'],seen=new Set();
 while(queue.length){
  const file=queue.shift();if(seen.has(file))continue;seen.add(file);
  assert(files.has(file),`${file} is imported but missing from Docker COPY`);
  assert(included(files.get(file)),`${file} is imported but excluded from Docker context`);
  const module=new vm.SourceTextModule(fs.readFileSync(path.join(root,files.get(file)),'utf8'));
  for(const specifier of module.dependencySpecifiers){
   if(!specifier.startsWith('.'))continue;
   const target=path.posix.normalize(path.posix.join(path.posix.dirname(file),specifier));
   assert(!target.startsWith('../'),'Relative module escaped the API image');
   assert(files.has(target),`${file} imports ${target}, missing from Docker COPY`);
   queue.push(target);
  }
 }
});
