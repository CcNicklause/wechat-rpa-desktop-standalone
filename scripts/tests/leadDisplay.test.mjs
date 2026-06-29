import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

async function loadLeadDisplayModule() {
  const source = readFileSync(new URL('../../src/lib/leadDisplay.ts', import.meta.url), 'utf8');
  const transpiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      verbatimModuleSyntax: false,
    },
  }).outputText;

  const moduleUrl = `data:text/javascript;base64,${Buffer.from(transpiled).toString('base64')}`;
  return import(moduleUrl);
}

test('formats backend lead as account plus remark', async () => {
  const { getLeadDisplay } = await loadLeadDisplayModule();

  const display = getLeadDisplay({
    lead_id: 'lead_1',
    customer_name: 'Alice',
    phone_masked: '138****1234',
    status: 'NEW_LEAD',
  });

  assert.deepEqual(display, {
    account: '138****1234',
    remark: 'Alice',
  });
});

test('prefers explicit wechat account and explicit remark when present', async () => {
  const { getLeadDisplay } = await loadLeadDisplayModule();

  const display = getLeadDisplay({
    id: 'lead_2',
    account: 'wxid_alice',
    phone: '13800001234',
    remark: '重点客户',
    customer_name: 'Alice',
  });

  assert.deepEqual(display, {
    account: 'wxid_alice',
    remark: '重点客户',
  });
});

test('omits remark when no independent remark exists', async () => {
  const { getLeadDisplay } = await loadLeadDisplayModule();

  const display = getLeadDisplay({
    id: 'lead_3',
    phone: 'wxid_only',
    name: 'wxid_only',
  });

  assert.deepEqual(display, {
    account: 'wxid_only',
    remark: null,
  });
});
