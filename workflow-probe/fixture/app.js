const params = new URLSearchParams(location.search);
const profile = params.get('profile') ?? 'healthy';
const session = params.get('session') ?? 'demo';
const api = new URL('/api/orders', location.origin);
api.searchParams.set('profile', profile);
api.searchParams.set('session', session);
const nav = performance.getEntriesByType('navigation')[0];
if (nav?.type === 'reload') api.searchParams.set('reloaded', '1');

const $ = (testId) => document.querySelector(`[data-testid="${testId}"]`);
const itemList = document.getElementById('items');
const status = document.getElementById('status');
let items = [];
let orders = [];
let sorted = false;
let pending = 0;
const intentId = 'current-order';

function total() {
  const correct = items.reduce((sum, item) => sum + item.price * item.quantity, 0);
  return profile === 'total-drift' && sorted ? correct - 3000 : correct;
}

function render() {
  const ordered = sorted ? [...items].sort((a, b) => a.price - b.price) : items;
  itemList.replaceChildren(...ordered.map((item) => {
    const li = document.createElement('li');
    li.className = 'item';
    li.dataset.testid = 'cart-item';
    li.dataset.itemId = item.id;
    const name = document.createElement('span');
    name.textContent = item.name;
    const meta = document.createElement('span');
    meta.textContent = `${item.price.toLocaleString('ko-KR')}원 × ${item.quantity}`;
    li.append(name, meta);
    return li;
  }));
  $('cart-total').textContent = String(total());
  $('order-count').textContent = String(orders.length);
  $('pending-count').textContent = String(pending);
}

if (profile === 'cosmetic-only') document.body.classList.add('cosmetic');

$('sort-items').addEventListener('click', () => {
  sorted = !sorted;
  render();
  status.textContent = sorted ? '가격순으로 정렬했어요.' : '원래 순서로 되돌렸어요.';
});

$('save-order').addEventListener('click', async () => {
  // Two requests remain possible. The server must honor the shared intent.
  pending += 1;
  render();
  try {
    const saveApi = new URL(api);
    saveApi.searchParams.delete('reloaded');
    const response = await fetch(saveApi, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ intentId }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    orders = payload.orders;
    status.textContent = '주문을 저장했어요.';
  } catch {
    status.textContent = '저장에 실패했어요. 다시 시도해 주세요.';
  } finally {
    pending -= 1;
    render();
  }
});

try {
  const response = await fetch(api);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  items = payload.items;
  orders = payload.orders;
  render();
  $('app-ready').textContent = 'ready';
  status.textContent = '준비됐어요.';
} catch {
  $('app-ready').textContent = 'error';
  status.textContent = '데이터를 불러오지 못했어요.';
}
