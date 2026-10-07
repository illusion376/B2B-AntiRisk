// Загружает модули из lib/*.ts в тестах node --test без дополнительных зависимостей:
// исходники транспилируются уже установленным typescript во временную папку как .mjs.
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const libDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'lib');
let outDir;

function compileLib() {
  outDir = mkdtempSync(path.join(tmpdir(), 'antirisk-lib-'));
  for (const file of readdirSync(libDir).filter(name => name.endsWith('.ts'))) {
    const source = readFileSync(path.join(libDir, file), 'utf8');
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: false },
      fileName: file,
    });
    // ESM в Node требует расширения: './labels' -> './labels.mjs'
    const code = outputText.replace(/(from\s+|import\s+)(['"])(\.\/[^'"]+)\2/g, '$1$2$3.mjs$2');
    writeFileSync(path.join(outDir, file.replace(/\.ts$/, '.mjs')), code);
  }
}

export async function loadLib(name) {
  if (!outDir) compileLib();
  return import(pathToFileURL(path.join(outDir, `${name}.mjs`)).href);
}
