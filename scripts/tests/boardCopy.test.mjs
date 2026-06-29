import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

async function loadTsModule(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
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

test('maps lead statuses to Chinese labels', async () => {
  const { statusDisplayLabel } = await loadTsModule('../../src/lib/statusDisplay.ts');

  assert.equal(statusDisplayLabel('RPA_BLOCKED'), '加微受阻');
  assert.equal(statusDisplayLabel('WECHAT_ACCEPTED'), '已添加');
  assert.equal(statusDisplayLabel('WECHAT_TARGET_NOT_FOUND'), '未找到账号');
  assert.equal(statusDisplayLabel('NEW_LEAD'), '新线索');
});

test('formats recent lead list count without English words', async () => {
  const { leadListCountText, LEAD_LIST_HINT } = await loadTsModule('../../src/lib/leadListCopy.ts');

  assert.equal(leadListCountText(100, 206), '显示 100 / 共 206');
  assert.equal(leadListCountText(4, null), '显示 4 条');
  assert.equal(LEAD_LIST_HINT, '按最近更新时间排序，点击线索查看执行步骤与日志');
});

test('uses Chinese labels for lead detail tabs', async () => {
  const { LEAD_DETAIL_TAB_LABELS, normalizeLeadDetailTab } = await loadTsModule('../../src/lib/leadDetailTabs.ts');

  assert.deepEqual(LEAD_DETAIL_TAB_LABELS, {
    overview: '概览',
    process: '过程',
    history: '历史',
  });
  assert.equal(normalizeLeadDetailTab('steps'), 'process');
  assert.equal(normalizeLeadDetailTab('timeline'), 'process');
  assert.equal(normalizeLeadDetailTab('raw'), 'process');
  assert.equal(normalizeLeadDetailTab('jobs'), 'history');
  assert.equal(normalizeLeadDetailTab('unknown'), 'overview');
});
