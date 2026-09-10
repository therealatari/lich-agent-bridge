import assert from 'node:assert/strict';
import test from 'node:test';
import { invokeDirectTool } from '../src/direct-tools.js';
import { createBridge, MAX_ISOLATE_WATCH_MS, type BridgeState } from '../src/sdk-bridge.js';
import { SessionHubClient, SessionHubError, type BridgeMetadata, type SessionHubCaller } from '../src/session-hub-client.js';
import type { SessionHubRoute } from '../src/routes.js';

class FakeHub implements SessionHubCaller {
  calls: Array<{ route: SessionHubRoute; payload: Record<string, unknown>; metadata?: BridgeMetadata }> = [];
  failRoute?: SessionHubRoute;

  async call(route: SessionHubRoute, payload: Record<string, unknown>, metadata?: BridgeMetadata): Promise<unknown> {
    this.calls.push({ route, payload, metadata });
    if (route === this.failRoute) throw new SessionHubError('denied by hub', 409, 'denied', { reason: 'policy' });
    return { route, payload };
  }
}

function bridgeState(): BridgeState {
  return { operationId: 'op-test', performCalls: 0, steps: [] };
}

test('direct tools validate with the shared strict Zod schema before calling SessionHub', async () => {
  const hub = new FakeHub();
  await assert.rejects(
    invokeDirectTool(hub, 'lab.snapshot', { character: '', extra: true }),
    /Invalid params for 'lab.snapshot'/,
  );
  assert.equal(hub.calls.length, 0);
  assert.deepEqual(await invokeDirectTool(hub, 'lab.snapshot', { character: '  Testmage  ' }), {
    route: 'snapshot', payload: { character: 'Testmage' },
  });
  assert.deepEqual(await invokeDirectTool(hub, 'lab.capabilities', {}), {
    route: 'capabilities', payload: {},
  });
  await assert.rejects(
    invokeDirectTool(hub, 'lab.capabilities', { character: 'Testmage', extra: true }),
    /Invalid params for 'lab.capabilities'/,
  );
});

test('SessionHub client applies bearer auth, central route mapping, and operation headers', async () => {
  let request: Request | undefined;
  const fakeFetch: typeof fetch = async (input, init) => {
    request = new Request(input, init);
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  const client = new SessionHubClient(new URL('http://127.0.0.1:18765'), 'secret-token', fakeFetch);
  await client.call('inventoryFind', { character: 'Testwarrior', query: 'herb' }, { operationId: 'op-1', stepId: 2 });
  assert.equal(request?.url, 'http://127.0.0.1:18765/v1/session/inventory/find');
  assert.equal(request?.headers.get('authorization'), 'Bearer secret-token');
  assert.equal(request?.headers.get('x-lab-operation-id'), 'op-1');
  assert.equal(request?.headers.get('x-lab-step-id'), '2');
});

test('perform returns the SessionHub operation ticket without waiting inside one MCP call', async () => {
  const paths: string[] = [];
  const fakeFetch: typeof fetch = async (input) => {
    const request = new Request(input);
    paths.push(new URL(request.url).pathname);
    if (paths.length > 1) throw new Error('MCP transport budget exceeded');
    return new Response(JSON.stringify({ operation_id: 'op-long', status: 'requested' }), { status: 202 });
  };
  const client = new SessionHubClient(new URL('http://127.0.0.1:18765'), 'secret-token', fakeFetch);

  const result = await client.call('perform', {
    character: 'Testwarrior', capability: 'controller.refuge-test', timeout_seconds: 180,
  });

  assert.deepEqual(result, { operation_id: 'op-long', status: 'requested' });
  assert.deepEqual(paths, ['/v1/session/perform']);
});

test('perform accepts only a positive finite operation budget up to 300 seconds', async () => {
  const hub = new FakeHub();
  const request = { character: 'Testmage', capability: 'controller.refuge-test' };
  for (const timeout_seconds of [0.5, 30, 120, 300]) {
    await invokeDirectTool(hub, 'lab.perform', { ...request, timeout_seconds });
    assert.equal(hub.calls.at(-1)?.payload.timeout_seconds, timeout_seconds);
  }
  const accepted = hub.calls.length;
  for (const timeout_seconds of [0, -1, 300.1, Number.NaN, Number.POSITIVE_INFINITY, '120', null]) {
    await assert.rejects(
      invokeDirectTool(hub, 'lab.perform', { ...request, timeout_seconds }),
      /Invalid params for 'lab.perform'/,
    );
  }
  assert.equal(hub.calls.length, accepted);
  await invokeDirectTool(hub, 'lab.perform', request);
  assert.equal('timeout_seconds' in hub.calls.at(-1)!.payload, false);
});

test('execute-code bridge forwards the validated operation budget', async () => {
  const hub = new FakeHub();
  await createBridge(hub, bridgeState()).call('perform', {
    character: 'Testmage', capability: 'controller.refuge-test', timeout_seconds: 120,
  });
  assert.equal(hub.calls[0].payload.timeout_seconds, 120);
});

test('operation watch is an explicit bounded request over the returned ticket', async (context) => {
  let request: Request | undefined;
  const transportTimeouts: number[] = [];
  context.mock.method(AbortSignal, 'timeout', (milliseconds: number) => {
    transportTimeouts.push(milliseconds);
    return new AbortController().signal;
  });
  const fakeFetch: typeof fetch = async (input, init) => {
    request = new Request(input, init);
    return new Response(JSON.stringify({
      operation: { operation_id: 'op-refuge', status: 'running' },
      items: [], total: 0, cursor: '7', timed_out: true,
    }), { status: 200 });
  };
  const client = new SessionHubClient(new URL('http://127.0.0.1:18765'), 'test-token', fakeFetch);

  const page = await client.call('operationWatch', {
    operation_id: 'op-refuge', cursor: '4', timeout_ms: 30_000,
  });

  assert.equal(request && new URL(request.url).pathname, '/v1/session/operation/watch');
  assert.deepEqual(JSON.parse(String(await request?.clone().text())), {
    operation_id: 'op-refuge', cursor: '4', timeout_ms: 30_000,
  });
  assert.equal((page as { cursor: string }).cursor, '7');
  assert.deepEqual(transportTimeouts, [32_000]);
});

test('operation watch validates its cursor and timeout before calling SessionHub', async () => {
  const hub = new FakeHub();
  await invokeDirectTool(hub, 'lab.operation_watch', {
    operation_id: 'op-7', cursor: '0', timeout_ms: 10_000,
  });
  assert.deepEqual(hub.calls[0]?.payload, {
    operation_id: 'op-7', cursor: '0', timeout_ms: 10_000,
  });
  for (const invalid of [
    { operation_id: '', cursor: '0' },
    { operation_id: 'op-7', cursor: '-1' },
    { operation_id: 'op-7', cursor: '1.5' },
    { operation_id: 'op-7', timeout_ms: 30_001 },
  ]) {
    await assert.rejects(
      invokeDirectTool(hub, 'lab.operation_watch', invalid),
      /Invalid params for 'lab.operation_watch'/,
    );
  }
  assert.equal(hub.calls.length, 1);
});

test('bridge validates calls, preserves hub throws, and records ordered step metadata', async () => {
  const hub = new FakeHub();
  const state = bridgeState();
  const bridge = createBridge(hub, state);
  await bridge.call('snapshot', { character: 'Testmage' });
  await assert.rejects(bridge.call('inventoryFind', { character: 'Testmage' }), /query/);
  hub.failRoute = 'wikiSearch';
  await assert.rejects(bridge.call('wikiSearch', { query: 'ensorcell' }), (error: unknown) => {
    assert.ok(error instanceof SessionHubError);
    assert.equal(error.code, 'denied');
    return true;
  });
  assert.deepEqual(state.steps.map((step) => [step.step_id, step.tool, step.success]), [
    [1, 'lab.snapshot', true],
    [2, 'lab.inventory_find', false],
    [3, 'lab.wiki_search', false],
  ]);
  assert.deepEqual(hub.calls[0].metadata, { operationId: 'op-test', stepId: 1 });
});

test('bridge permits many reads, caps isolate watch, one perform, and recursion', async () => {
  const hub = new FakeHub();
  const state = bridgeState();
  const bridge = createBridge(hub, state);
  await bridge.call('snapshot', { character: 'Testmage' });
  await bridge.call('watch', { character: 'Testmage', timeout_ms: MAX_ISOLATE_WATCH_MS });
  await assert.rejects(
    bridge.call('watch', { character: 'Testmage', timeout_ms: MAX_ISOLATE_WATCH_MS + 1 }),
    /use direct lab.watch/,
  );
  await bridge.call('perform', { character: 'Testmage', capability: 'hunt.prepare' });
  await assert.rejects(
    bridge.call('perform', { character: 'Testmage', capability: 'room.loot' }),
    /At most one lab.perform/,
  );
  await assert.rejects(bridge.call('executeCode', {}), /Recursive lab.execute_code is forbidden/);
  assert.equal(hub.calls.filter((call) => call.route === 'perform').length, 1);
});
