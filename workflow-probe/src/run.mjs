import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const PROFILES = ['healthy', 'total-drift', 'duplicate-save', 'reload-loss', 'cosmetic-only'];
const RELATIONS = ['SORT_TOTAL', 'SAVE_DUPLICATE', 'REFRESH_PERSIST'];
const EXPECTED_CART_TOTAL = 32000;
const WAIT_MS = 6000;

async function loadPlaywright(packageSpecifier) {
  if (packageSpecifier && typeof packageSpecifier === 'object') return packageSpecifier;
  const specifier = packageSpecifier ?? process.env.PLAYWRIGHT_PACKAGE ?? 'playwright';
  const importTarget = path.isAbsolute(specifier)
    ? pathToFileURL(specifier).href
    : specifier;
  const loaded = await import(importTarget);
  const playwright = loaded.chromium ? loaded : loaded.default;
  if (!playwright?.chromium) throw new Error(`Playwright Chromium을 불러오지 못했습니다: ${specifier}`);
  return playwright;
}

function runUrl(baseUrl, profile, session) {
  const url = new URL(baseUrl);
  url.searchParams.set('profile', profile);
  url.searchParams.set('session', session);
  return url.href;
}

function integerText(value, label) {
  const stripped = (value ?? '').replace(/[^0-9-]/g, '');
  const parsed = Number(stripped);
  if (!stripped || !Number.isSafeInteger(parsed)) {
    throw new Error(`${label}에서 정수를 읽지 못했습니다: ${JSON.stringify(value)}`);
  }
  return parsed;
}

async function readNumber(page, testId) {
  const raw = await page.getByTestId(testId).textContent();
  return integerText(raw, testId);
}

async function snapshot(page) {
  const [total, orderCount, pendingCount, itemOrder] = await Promise.all([
    readNumber(page, 'cart-total'),
    readNumber(page, 'order-count'),
    readNumber(page, 'pending-count'),
    page.getByTestId('cart-item').evaluateAll((items) => items.map((item) => item.getAttribute('data-item-id'))),
  ]);
  return { total, orderCount, pendingCount, itemOrder };
}

async function until(read, predicate, label, timeoutMs = WAIT_MS) {
  const deadline = Date.now() + timeoutMs;
  let last;
  let lastError;
  while (Date.now() < deadline) {
    try {
      last = await read();
      if (predicate(last)) return last;
      lastError = undefined;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
  throw new Error(`${label} 대기 시간 초과 (마지막 값: ${JSON.stringify(last)}${lastError ? `, 오류: ${lastError.message}` : ''})`);
}

async function ready(page, url) {
  const response = await page.goto(url, { waitUntil: 'domcontentloaded' });
  if (!response?.ok()) throw new Error(`앱 요청 실패: ${response?.status() ?? '응답 없음'} ${url}`);
  await until(
    () => page.getByTestId('app-ready').textContent(),
    (value) => value?.trim() === 'ready',
    '앱 준비',
  );
  await until(() => readNumber(page, 'pending-count'), (count) => count === 0, '초기 요청 완료');
}

async function ordinaryBaseline(browser, baseUrl, profile) {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await ready(page, runUrl(baseUrl, profile, `baseline-${randomUUID()}`));
    const initialTotal = await readNumber(page, 'cart-total');
    const initialOrderCount = await readNumber(page, 'order-count');
    const steps = ['새 세션에서 장바구니 열기', '초기 합계와 주문 수 관찰'];
    await page.getByTestId('save-order').click();
    steps.push('저장 버튼을 한 번 누르기');
    const savedOrderCount = await until(
      () => readNumber(page, 'order-count'),
      (count) => count >= 1,
      '단일 저장 표시',
    );
    const pendingCount = await until(
      () => readNumber(page, 'pending-count'),
      (count) => count === 0,
      '단일 저장 처리 완료',
    );
    return {
      baseline: { initialTotal, initialOrderCount, savedOrderCount, pendingCount },
      baselinePassed: initialTotal === EXPECTED_CART_TOTAL && initialOrderCount === 0 && savedOrderCount === 1 && pendingCount === 0,
      steps,
    };
  } finally {
    await context.close();
  }
}

function relativeArtifact(id, name) {
  return `artifacts/${id}/${name}`;
}

async function capture(page, outputDir, record, which) {
  const relative = relativeArtifact(record.id, `${which}.png`);
  await page.screenshot({ path: path.join(outputDir, ...relative.split('/')), fullPage: true });
  record.artifacts[which] = relative;
}

async function runRelation(browser, baseUrl, outputDir, record) {
  const context = await browser.newContext();
  let page;
  let traceStarted = false;
  const saveRequests = new Set();
  const failedRequests = [];
  try {
    await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
    traceStarted = true;
    page = await context.newPage();
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.includes('/api/')) saveRequests.add(request);
    });
    page.on('response', (response) => {
      if (response.request().method() === 'POST' && !response.ok()) {
        failedRequests.push(`${response.status()} ${response.url()}`);
      }
    });
    page.on('requestfailed', (request) => {
      if (request.method() === 'POST') failedRequests.push(`${request.failure()?.errorText ?? '요청 실패'} ${request.url()}`);
    });
    await ready(page, runUrl(baseUrl, record.profile, `relation-${randomUUID()}`));
    record.steps.push('새로운 세션에서 장바구니 열기');

    if (record.relation === 'REFRESH_PERSIST') {
      await page.getByTestId('save-order').click();
      record.steps.push('주문을 한 번 저장하고 완료 표시를 기다리기');
      await until(() => readNumber(page, 'order-count'), (count) => count >= 1, '새 주문 표시');
      await until(() => readNumber(page, 'pending-count'), (count) => count === 0, '저장 완료');
    }

    record.before = await snapshot(page);
    await capture(page, outputDir, record, 'before');
    record.steps.push('변경 전 화면과 수치 기록');

    if (record.relation === 'SORT_TOTAL') {
      await page.getByTestId('sort-items').click();
      record.steps.push('항목 순서를 바꾸기');
      await until(
        () => page.getByTestId('cart-item').evaluateAll((items) => items.map((item) => item.getAttribute('data-item-id'))),
        (itemOrder) => itemOrder.join('|') !== record.before.itemOrder.join('|'),
        '항목 순서 변경',
      );
    } else if (record.relation === 'SAVE_DUPLICATE') {
      const button = page.getByTestId('save-order');
      const box = await button.boundingBox();
      if (!box) throw new Error('저장 버튼 위치를 찾지 못했습니다.');
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.click(x, y);
      await page.mouse.click(x, y);
      record.steps.push('같은 주문 의도로 저장 버튼을 빠르게 두 번 누르기');
      await until(() => saveRequests.size, (count) => count >= 2, '두 저장 요청 전송');
      await until(() => readNumber(page, 'pending-count'), (count) => count === 0, '두 저장 요청 완료');
      if (saveRequests.size !== 2) throw new Error(`저장 요청 ${saveRequests.size}건이 발생했습니다. 정확히 두 번의 클릭을 검증해야 합니다.`);
      record.steps.push(`실제 저장 요청 ${saveRequests.size}건 확인`);
    } else if (record.relation === 'REFRESH_PERSIST') {
      const response = await page.reload({ waitUntil: 'domcontentloaded' });
      if (!response?.ok()) throw new Error(`새로고침 실패: ${response?.status() ?? '응답 없음'}`);
      await until(
        () => page.getByTestId('app-ready').textContent(),
        (value) => value?.trim() === 'ready',
        '새로고침 후 앱 준비',
      );
      await until(() => readNumber(page, 'pending-count'), (count) => count === 0, '새로고침 후 요청 완료');
      record.steps.push('화면 새로고침 후 데이터 다시 불러오기');
    } else {
      throw new Error(`알 수 없는 관계: ${record.relation}`);
    }

    record.after = await snapshot(page);
    if (record.relation === 'SAVE_DUPLICATE') record.after.saveRequests = saveRequests.size;
    await capture(page, outputDir, record, 'after');
    record.steps.push('변경 후 화면과 수치 기록');
    if (failedRequests.length) throw new Error(`저장 요청 실패: ${failedRequests.join('; ')}`);
    if (record.relation === 'SORT_TOTAL') {
      const beforeOrder = record.before.itemOrder;
      const afterOrder = record.after.itemOrder;
      if (beforeOrder.length < 2 || beforeOrder.join('|') === afterOrder.join('|')) {
        throw new Error('정렬 버튼을 눌렀지만 항목 순서가 바뀌지 않았습니다.');
      }
      if (beforeOrder.slice().sort().join('|') !== afterOrder.slice().sort().join('|')) {
        throw new Error('정렬 과정에서 항목의 종류나 개수가 바뀌었습니다.');
      }
    }
    record.status = violated(record) ? 'violation' : 'pass';
    record.message = messageFor(record);
  } catch (error) {
    record.status = 'error';
    record.message = error instanceof Error ? error.message : String(error);
    if (page && !record.artifacts.after) {
      try { await capture(page, outputDir, record, 'after'); } catch { /* Preserve the original execution error. */ }
    }
  } finally {
    if (traceStarted) {
      try {
        if (record.status === 'violation' || record.status === 'error') {
          const relative = relativeArtifact(record.id, 'trace.zip');
          await context.tracing.stop({ path: path.join(outputDir, ...relative.split('/')) });
          record.artifacts.trace = relative;
        } else {
          await context.tracing.stop();
        }
      } catch (error) {
        record.status = 'error';
        record.message = `추적 기록 저장 실패: ${error.message}`;
      }
    }
    await context.close();
  }
}

function violated({ relation, before, after }) {
  if (relation === 'SORT_TOTAL') return after.total !== before.total;
  if (relation === 'SAVE_DUPLICATE') return after.orderCount !== before.orderCount + 1;
  if (relation === 'REFRESH_PERSIST') return after.orderCount !== before.orderCount;
  throw new Error(`알 수 없는 관계: ${relation}`);
}

function messageFor(record) {
  const { relation, before, after, status } = record;
  if (relation === 'SORT_TOTAL') return `정렬 전 ${before.total}원, 정렬 후 ${after.total}원: ${status === 'pass' ? '합계 유지' : '합계 변경'}`;
  if (relation === 'SAVE_DUPLICATE') return `두 번 클릭 전 ${before.orderCount}건, 후 ${after.orderCount}건: ${status === 'pass' ? '한 건만 저장' : '중복 저장'}`;
  return `새로고침 전 ${before.orderCount}건, 후 ${after.orderCount}건: ${status === 'pass' ? '저장 내역 표시 유지' : '저장 내역 표시 누락'}`;
}

export async function runSuite({ baseUrl, outputDir, repetitions = 3, playwrightPackage } = {}) {
  if (!Number.isSafeInteger(repetitions) || repetitions < 1) throw new Error('repetitions는 1 이상의 정수여야 합니다.');
  const targetDir = path.resolve(outputDir ?? path.join(process.cwd(), 'evidence', 'latest'));
  await mkdir(targetDir, { recursive: true });
  const playwright = await loadPlaywright(playwrightPackage);
  let fixture;
  let browser;
  const results = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    repetitions,
    environment: { node: process.version, platform: process.platform, arch: process.arch },
    cases: [],
  };
  try {
    if (!baseUrl) {
      const { startFixture } = await import('../fixture/server.mjs');
      fixture = await startFixture({ port: 0, host: '127.0.0.1', reportDir: targetDir });
      baseUrl = fixture.url;
    }
    browser = await playwright.chromium.launch({ headless: true });
    results.environment.browser = `Chromium ${browser.version()}`;
    results.environment.fixtureUrl = baseUrl;

    for (const profile of PROFILES) {
      for (const relation of RELATIONS) {
        for (let repetition = 1; repetition <= repetitions; repetition++) {
          const record = {
            id: `${profile}_${relation}_${String(repetition).padStart(2, '0')}`,
            profile,
            relation,
            repetition,
            baselinePassed: false,
            baseline: null,
            before: null,
            after: null,
            status: 'error',
            message: '',
            steps: [],
            artifacts: { before: null, after: null, trace: null },
          };
          results.cases.push(record);
          await mkdir(path.join(targetDir, 'artifacts', record.id), { recursive: true });
          try {
            const ordinary = await ordinaryBaseline(browser, baseUrl, profile);
            record.baseline = ordinary.baseline;
            record.baselinePassed = ordinary.baselinePassed;
            record.steps.push(...ordinary.steps);
            if (!ordinary.baselinePassed) throw new Error(`보통 사용 경로가 실패했습니다: ${JSON.stringify(ordinary.baseline)}`);
            await runRelation(browser, baseUrl, targetDir, record);
          } catch (error) {
            record.status = 'error';
            record.message = error instanceof Error ? error.message : String(error);
          }
          await writeFile(path.join(targetDir, 'results.json'), JSON.stringify(results, null, 2) + '\n', 'utf8');
        }
      }
    }
    return results;
  } finally {
    try { if (browser) await browser.close(); } finally { if (fixture) await fixture.close(); }
  }
}

function parseArgs(args) {
  const options = {};
  for (let index = 0; index < args.length; index++) {
    const flag = args[index];
    if (!['--output', '--repetitions', '--base-url'].includes(flag) || !args[index + 1]) {
      throw new Error(`잘못된 인수: ${flag}`);
    }
    const value = args[++index];
    if (flag === '--output') options.outputDir = value;
    if (flag === '--repetitions') options.repetitions = Number(value);
    if (flag === '--base-url') options.baseUrl = value;
  }
  return options;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  runSuite(parseArgs(process.argv.slice(2))).then((results) => {
    const count = (status) => results.cases.filter((item) => item.status === status).length;
    console.log(`검증 ${results.cases.length}건: 통과 ${count('pass')}, 규칙 위반 ${count('violation')}, 실행 오류 ${count('error')}`);
    if (count('error')) process.exitCode = 1;
  }).catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
