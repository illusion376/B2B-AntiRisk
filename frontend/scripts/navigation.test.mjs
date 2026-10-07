import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const ts=require('typescript');
require.extensions['.ts']=(module,filename)=>module._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,filename);
const {parseRoute,serializeRoute,normalizeRoute}=require('../lib/navigation.ts');

test('document links restore project, page and selected finding',()=>{
  const route={view:'document',projectId:'contract-project',page:24,findingId:2};
  assert.deepEqual(parseRoute(serializeRoute(route),54),route);
});
test('project identifiers survive URL encoding',()=>{
  const route={view:'project',projectId:'проект & # 20',page:18,findingId:null};
  assert.equal(parseRoute(serializeRoute(route),54).projectId,route.projectId);
});
test('invalid and out-of-range page numbers remain within document bounds',()=>{
  assert.equal(parseRoute('#document?page=-100',54).page,1);
  assert.equal(parseRoute('#document?page=900',54).page,54);
  assert.equal(parseRoute('#document?page=Infinity',54).page,18);
});
test('unknown views and invalid selected findings have safe defaults',()=>{
  const route=parseRoute('#unknown?finding=-1',54);
  assert.equal(route.view,'documents');
  assert.equal(route.findingId,null);
  assert.equal(normalizeRoute({...route,projectId:'   '},54).projectId,'contract-project');
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
