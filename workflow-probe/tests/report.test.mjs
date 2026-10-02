import assert from 'node:assert/strict';
import test from 'node:test';
import { safeJson } from '../tools/build-report.mjs';

test('embedded report data cannot close its script element', () => {
  const value = { message: '</script><script>alert(1)</script> & visible' };
  const output = safeJson(value);
  assert.equal(output.includes('<'), false);
  assert.equal(output.includes('>'), false);
  assert.equal(output.includes('&'), false);
  assert.deepEqual(JSON.parse(output), value);
});
