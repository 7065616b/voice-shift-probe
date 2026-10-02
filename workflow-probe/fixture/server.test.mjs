import assert from 'node:assert/strict';
import test from 'node:test';
import { startFixture } from './server.mjs';

test('ordinary saves work in every profile and sessions remain isolated', async (t) => {
  const fixture = await startFixture();
  t.after(() => fixture.close());
  for (const profile of ['healthy', 'total-drift', 'duplicate-save', 'reload-loss', 'cosmetic-only']) {
    const endpoint = `${fixture.url}/api/orders?profile=${profile}&session=session-${profile}`;
    const first = await (await fetch(endpoint)).json();
    assert.equal(first.items.reduce((sum, item) => sum + item.price * item.quantity, 0), 32000);
    assert.equal(first.orders.length, 0);
    const saved = await (await fetch(endpoint, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ intentId: 'one' }),
    })).json();
    assert.equal(saved.orders.length, 1, profile);
    assert.equal((await (await fetch(endpoint)).json()).orders.length, 1, profile);
  }
});

test('repeat intent only duplicates in seeded profile; refresh hides only its seeded case', async (t) => {
  const fixture = await startFixture();
  t.after(() => fixture.close());
  for (const profile of ['healthy', 'total-drift', 'duplicate-save', 'reload-loss', 'cosmetic-only']) {
    const endpoint = `${fixture.url}/api/orders?profile=${profile}&session=repeat-${profile}`;
    const save = () => fetch(endpoint, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ intentId: 'same' }),
    });
    await Promise.all([save(), save()]);
    const retained = await (await fetch(endpoint)).json();
    assert.equal(retained.orders.length, profile === 'duplicate-save' ? 2 : 1, profile);
    const reloaded = await (await fetch(`${endpoint}&reloaded=1`)).json();
    assert.equal(reloaded.orders.length, profile === 'reload-loss' ? 0 : retained.orders.length, profile);
  }
});
