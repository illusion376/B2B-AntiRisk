import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const ts=require('typescript');
require.extensions['.ts']=(module,filename)=>module._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,filename);
const {defaultRoute,parseRoute,serializeRoute,normalizeRoute}=require('../lib/navigation.ts');
const documentRoute={view:'document',projectId:'248c6a80-71a5-4c91-a316-6d34c297e06d',documentId:'6d9e854c-e030-42c1-91a0-e62c8e024c42',page:24,findingId:'044d8724-ee09-470d-82a0-dbf8e6d25d4e'};

test('document links restore distinct project, document, page and UUID finding identifiers',()=>{
  assert.deepEqual(parseRoute(serializeRoute(documentRoute),54),documentRoute);
  assert.match(serializeRoute(documentRoute),/^#\/projects\/[^/]+\/documents\/[^?]+\?page=24&finding=/);
});
test('project and document identifiers survive URL encoding',()=>{
  const route={...documentRoute,projectId:'проект & # 20',documentId:'документ 1/2',findingId:'замечание 2'};
  assert.deepEqual(parseRoute(serializeRoute(route)),route);
});
test('empty, unknown and malformed routes safely show the project list',()=>{
  for(const hash of ['', '#', '#/', '#unknown', '#/projects', '#/projects/a/documents/b/extra', '#/projects/%E0%A4%A/documents/d', '#/projects/a/documents/d?page=%FF']) {
    assert.deepEqual(parseRoute(hash),defaultRoute,hash);
  }
});
test('requested page survives before document metadata has loaded, then clamps to its actual bounds',()=>{
  const hash=serializeRoute({...documentRoute,page:900});
  assert.equal(parseRoute(hash).page,900);
  assert.equal(parseRoute(hash,0).page,900);
  assert.equal(parseRoute(hash,54).page,54);
  assert.equal(normalizeRoute({...documentRoute,page:2.9},54).page,2);
  for(const page of ['-100','Infinity','NaN','1.5','abc','0']) {
    assert.equal(parseRoute(`#/projects/p/documents/d?page=${page}`,54).page,1,page);
  }
});
test('legacy develop URLs only open documents when they contain a real document identifier',()=>{
  assert.deepEqual(parseRoute('#document?project=p&document=d&page=12&finding=f'),{view:'document',projectId:'p',documentId:'d',page:12,findingId:'f'});
  assert.deepEqual(parseRoute('#document?project=p&page=18&finding=1'),{...defaultRoute,view:'project',projectId:'p'});
  assert.deepEqual(parseRoute('#document?page=18&finding=1'),defaultRoute);
});
test('project, history, rules and documents links have no stale document selection',()=>{
  assert.deepEqual(parseRoute('#/projects/p'),{...defaultRoute,view:'project',projectId:'p'});
  for(const view of ['documents','history','rules']) {
    const route=normalizeRoute({...documentRoute,view});
    assert.deepEqual(route,{...defaultRoute,view});
    assert.deepEqual(parseRoute(serializeRoute(route)),route);
  }
});
test('invalid identifiers cannot create malformed URLs',()=>{
  assert.equal(normalizeRoute({...documentRoute,findingId:42}).findingId,null);
  assert.equal(normalizeRoute({...documentRoute,findingId:' '}).findingId,null);
  assert.equal(normalizeRoute({...documentRoute,documentId:'d\u0000'}).view,'project');
  assert.equal(serializeRoute({...documentRoute,documentId:'\ud800'}),'#/projects/'+documentRoute.projectId);
});
test('workspace and analysis styles stay scoped to their containers',()=>{
  const postcss=require('postcss');
  for(const filename of ['dashboard.css','review-enhancements.css']) {
    const css=postcss.parse(readFileSync(new URL(`../components/${filename}`,import.meta.url),'utf8'));
    css.walkRules(rule=>{
      for(const selector of rule.selectors){
        assert.match(selector,/^\.dashboard-(?:canvas|shell)\b/,`Unscoped workspace selector: ${selector}`);
      }
    });
  }
});
