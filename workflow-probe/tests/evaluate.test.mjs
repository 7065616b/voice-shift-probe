import assert from 'node:assert/strict';
import test from 'node:test';
import { evaluate, observedStatus, profiles, relations } from '../tools/evaluate.mjs';

const initialOrder = ['microphone', 'cable', 'notebook'];
const sortedOrder = ['notebook', 'cable', 'microphone'];
const planted = {
  'total-drift': 'SORT_TOTAL',
  'duplicate-save': 'SAVE_DUPLICATE',
  'reload-loss': 'REFRESH_PERSIST',
};

function makeCase(profile, relation, repetition) {
  const id = `${profile}_${relation}_${String(repetition).padStart(2, '0')}`;
  const before = { total: 32000, orderCount: relation === 'REFRESH_PERSIST' ? 1 : 0, pendingCount: 0, itemOrder: [...initialOrder] };
  const after = {
    total: profile === 'total-drift' && relation === 'SORT_TOTAL' ? 29000 : 32000,
    orderCount: profile === 'duplicate-save' && relation === 'SAVE_DUPLICATE' ? 2 :
      profile === 'reload-loss' && relation === 'REFRESH_PERSIST' ? 0 : 1,
    pendingCount: 0,
    itemOrder: relation === 'SORT_TOTAL' ? [...sortedOrder] : [...initialOrder],
  };
  if (relation === 'SORT_TOTAL') after.orderCount = 0;
  if (relation === 'SAVE_DUPLICATE') after.saveRequests = 2;
  const status = planted[profile] === relation ? 'violation' : 'pass';
  return {
    id, profile, relation, repetition,
    baselinePassed: true,
    baseline: { initialTotal: 32000, initialOrderCount: 0, savedOrderCount: 1, pendingCount: 0 },
    before, after, status,
    artifacts: {
      before: `artifacts/${id}/before.png`,
      after: `artifacts/${id}/after.png`,
      trace: status === 'violation' ? `artifacts/${id}/trace.zip` : null,
    },
  };
}

function matrix() {
  return {
    schemaVersion: 1,
    cases: profiles.flatMap((profile) =>
      relations.flatMap((relation) => [1, 2, 3].map((repetition) => makeCase(profile, relation, repetition)))),
  };
}

test('independent evaluation accepts the complete observed 45-case matrix', () => {
  const result = evaluate(matrix());
  assert.equal(result.passed, true, result.issues.join('\n'));
  assert.equal(result.totalChecks, 45);
  assert.equal(result.ordinaryPassed, 45);
  assert.equal(result.violations, 9);
  assert.equal(result.defectsDetected, 3);
  assert.equal(result.executionErrors, 0);
  assert.equal(result.controlFalseAlarms, 0);
  assert.equal(result.offTargetAlarms, 0);
});

test('a claimed verdict cannot override the measured result', () => {
  const data = matrix();
  const c = data.cases.find((row) => row.profile === 'total-drift' && row.relation === 'SORT_TOTAL');
  c.after.total = c.before.total;
  const result = evaluate(data);
  assert.equal(result.passed, false);
  assert.ok(result.issues.some((issue) => issue.includes('Reported verdict contradicts observations')));
  assert.ok(result.issues.some((issue) => issue.includes('Ground-truth mismatch')));
});

test('a before/after pair without a completed transformation is an error', () => {
  const sort = makeCase('healthy', 'SORT_TOTAL', 1);
  sort.after.itemOrder = [...sort.before.itemOrder];
  assert.equal(observedStatus(sort), 'error');
  const save = makeCase('healthy', 'SAVE_DUPLICATE', 1);
  delete save.after.saveRequests;
  assert.equal(observedStatus(save), 'error');
  const refresh = makeCase('healthy', 'REFRESH_PERSIST', 1);
  refresh.before.orderCount = 0;
  refresh.after.orderCount = 0;
  assert.equal(observedStatus(refresh), 'error');
});

test('invalid ordinary baseline cannot be counted as discovered defect', () => {
  const data = matrix();
  data.cases.find((row) => row.profile === 'total-drift' && row.relation === 'SORT_TOTAL').baseline.pendingCount = 1;
  const result = evaluate(data);
  assert.equal(result.passed, false);
  assert.equal(result.ordinaryPassed, 44);
  assert.equal(result.executionErrors, 1);
  assert.equal(result.defectsDetected, 2);
  assert.ok(result.issues.some((issue) => issue.includes('Ordinary path failed')));
});

test('missing, duplicated, and malformed cases fail acceptance', () => {
  const missing = matrix();
  missing.cases.pop();
  assert.equal(evaluate(missing).passed, false);
  const duplicated = matrix();
  duplicated.cases[1] = structuredClone(duplicated.cases[0]);
  const result = evaluate(duplicated);
  assert.equal(result.passed, false);
  assert.ok(result.issues.some((issue) => issue.includes('Duplicate case')));
  const malformed = matrix();
  malformed.cases[0].after.total = '29000';
  assert.equal(evaluate(malformed).executionErrors, 1);
});

test('unsafe or absent evidence paths fail acceptance', () => {
  const data = matrix();
  data.cases[0].artifacts.before = '../outside.png';
  assert.ok(evaluate(data).issues.some((issue) => issue.includes('Malformed artifact paths')));
  const data2 = matrix();
  data2.cases.find((row) => row.status === 'violation').artifacts.trace = null;
  assert.ok(evaluate(data2).issues.some((issue) => issue.includes('Malformed artifact paths')));
});

test('negative-control alarms are counted and rejected', () => {
  const data = matrix();
  const c = data.cases.find((row) => row.profile === 'cosmetic-only' && row.relation === 'SORT_TOTAL');
  c.after.total = 29000;
  c.status = 'violation';
  c.artifacts.trace = `artifacts/${c.id}/trace.zip`;
  const result = evaluate(data);
  assert.equal(result.controlFalseAlarms, 1);
  assert.equal(result.passed, false);
});
