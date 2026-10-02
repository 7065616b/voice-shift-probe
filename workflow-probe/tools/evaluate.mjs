// Ground truth belongs to this evaluator, never to the browser probe.
export const profiles = ['healthy', 'total-drift', 'duplicate-save', 'reload-loss', 'cosmetic-only'];
export const relations = ['SORT_TOTAL', 'SAVE_DUPLICATE', 'REFRESH_PERSIST'];
const planted = {'total-drift': 'SORT_TOTAL', 'duplicate-save': 'SAVE_DUPLICATE', 'reload-loss': 'REFRESH_PERSIST'};
const controls = new Set(['healthy', 'cosmetic-only']);
const itemIds = ['cable', 'microphone', 'notebook'];

function nonnegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function validItems(value) {
  return Array.isArray(value) && value.length === itemIds.length &&
    value.every((id) => typeof id === 'string') &&
    [...value].sort().every((id, index) => id === itemIds[index]);
}

function observedNumbers(c) {
  const before = c?.before;
  const after = c?.after;
  return before && after &&
    [before.total, before.orderCount, before.pendingCount, after.total, after.orderCount, after.pendingCount]
      .every(nonnegativeInteger) &&
    before.total === 32000 && before.pendingCount === 0 && after.pendingCount === 0 &&
    validItems(before.itemOrder) && validItems(after.itemOrder);
}

export function observedStatus(c) {
  if (c?.status === 'error' || !observedNumbers(c)) return 'error';
  const b = c.before;
  const a = c.after;
  if (c.relation === 'SORT_TOTAL') {
    if (b.itemOrder.join('|') === a.itemOrder.join('|') || b.orderCount !== 0 || a.orderCount !== 0) return 'error';
    return a.total === b.total ? 'pass' : 'violation';
  }
  if (c.relation === 'SAVE_DUPLICATE') {
    if (b.orderCount !== 0 || a.saveRequests !== 2 || b.itemOrder.join('|') !== a.itemOrder.join('|')) return 'error';
    return a.orderCount === 1 ? 'pass' : 'violation';
  }
  if (c.relation === 'REFRESH_PERSIST') {
    if (b.orderCount !== 1 || b.itemOrder.join('|') !== a.itemOrder.join('|')) return 'error';
    return a.orderCount === 1 ? 'pass' : 'violation';
  }
  return 'error';
}

function validArtifactPath(value, id, name) {
  return value === `artifacts/${id}/${name}`;
}

function validBaseline(c) {
  const b = c?.baseline;
  return c?.baselinePassed === true && b?.initialTotal === 32000 &&
    b.initialOrderCount === 0 && b.savedOrderCount === 1 && b.pendingCount === 0;
}

export function evaluate(data, repetitions = 3) {
  if (!Number.isSafeInteger(repetitions) || repetitions < 1) throw new Error('repetitions must be a positive integer');
  const cases = Array.isArray(data?.cases) ? data.cases : [];
  const issues = [];
  const expectedCount = profiles.length * relations.length * repetitions;
  if (data?.schemaVersion !== 1) issues.push('Unsupported or absent schemaVersion');
  if (!Array.isArray(data?.cases)) issues.push('Missing cases array');
  if (cases.length !== expectedCount) issues.push(`Expected ${expectedCount} cases, observed ${cases.length}`);
  const keys = new Set();
  let violations = 0, errors = 0, baselinePassed = 0, falseAlarms = 0, offTargetAlarms = 0;
  const reproduced = Object.fromEntries(Object.keys(planted).map((profile) => [profile, 0]));
  for (const c of cases) {
    if (!c || typeof c !== 'object') { errors++; issues.push('Malformed case record'); continue; }
    const key = `${c.profile}/${c.relation}/${c.repetition}`;
    if (keys.has(key)) issues.push(`Duplicate case: ${key}`);
    keys.add(key);
    if (!profiles.includes(c.profile) || !relations.includes(c.relation) || !Number.isInteger(c.repetition) || c.repetition < 1 || c.repetition > repetitions) issues.push(`Unexpected case: ${key}`);
    const id = `${c.profile}_${c.relation}_${String(c.repetition).padStart(2, '0')}`;
    if (c.id !== id) issues.push(`Unexpected case id: ${key}`);
    if (!validBaseline(c)) {
      errors++;
      issues.push(`Ordinary path failed or lacks observations: ${key}`);
      continue;
    }
    baselinePassed++;
    const status = observedStatus(c);
    if (status === 'error') { errors++; issues.push(`Execution/observation error: ${key}`); continue; }
    if (!validArtifactPath(c.artifacts?.before, id, 'before.png') || !validArtifactPath(c.artifacts?.after, id, 'after.png') ||
        (status === 'violation' && !validArtifactPath(c.artifacts?.trace, id, 'trace.zip')) ||
        (status === 'pass' && c.artifacts?.trace != null)) {
      issues.push(`Malformed artifact paths: ${key}`);
    }
    if (status !== c.status) issues.push(`Reported verdict contradicts observations: ${key}`);
    const expected = planted[c.profile] === c.relation ? 'violation' : 'pass';
    if (status !== expected) issues.push(`Ground-truth mismatch: ${key}`);
    if (status === 'violation') {
      violations++;
      if (controls.has(c.profile)) falseAlarms++;
      else if (expected === 'pass') offTargetAlarms++;
      else reproduced[c.profile]++;
    }
  }
  for (const profile of profiles) for (const relation of relations) for (let r = 1; r <= repetitions; r++) {
    if (!keys.has(`${profile}/${relation}/${r}`)) issues.push(`Missing case: ${profile}/${relation}/${r}`);
  }
  return {
    passed: issues.length === 0,
    scope: 'Controlled seeded fixture; not general real-world accuracy',
    repetitions,
    totalChecks: cases.length,
    expectedChecks: expectedCount,
    ordinaryPassed: baselinePassed,
    violations,
    executionErrors: errors,
    defectsDetected: Object.values(reproduced).filter((n) => n === repetitions).length,
    seededDefects: 3,
    controlChecks: 2 * 3 * repetitions,
    controlFalseAlarms: falseAlarms,
    offTargetChecks: 3 * 2 * repetitions,
    offTargetAlarms,
    reproduced,
    issues,
  };
}
