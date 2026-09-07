import assert from 'node:assert/strict';
import test from 'node:test';
import { EXECUTOR_LIMITS, executeCode, transpileTypeScript } from '../src/executor.js';
import { SessionHubError, type BridgeMetadata, type SessionHubCaller } from '../src/session-hub-client.js';
import type { SessionHubRoute } from '../src/routes.js';

class ExecutorHub implements SessionHubCaller {
  calls: Array<{ route: SessionHubRoute; payload: Record<string, unknown>; metadata?: BridgeMetadata }> = [];
  async call(route: SessionHubRoute, payload: Record<string, unknown>, metadata?: BridgeMetadata): Promise<unknown> {
    this.calls.push({ route, payload, metadata });
    if (payload.query === 'throw') throw new SessionHubError('bridge said no', 400, 'bad_query', { query: 'throw' });
    if (route === 'snapshot') return { character: payload.character, room: { id: '42' }, noisy: 'x'.repeat(10_000) };
    if (route === 'inventoryFind') return { items: [{ id: 'a', name: 'black crystal' }, { id: 'b', name: 'black crystal' }] };
    if (route === 'wikiSearch') return { items: [{ title: 'Ensorcell' }, { title: 'Necromancy' }] };
    if (route === 'watch') return { items: [] };
    if (route === 'perform') return { status: 'succeeded', capability: payload.capability };
    return {};
  }
}

test('TypeScript transpilation accepts annotations and rejects malformed syntax', () => {
  assert.ok('code' in transpileTypeScript("const x: string = 'ok'; return x;"));
  const invalid = transpileTypeScript('const x: : = 1; return x;');
  assert.ok('error' in invalid);
});

test('execute_code chains and batches reads but returns only compact aggregation', async () => {
  const hub = new ExecutorHub();
  const result = await executeCode(`
    const state: CharacterSnapshot = await lab.snapshot({ character: 'Testmage' });
    const [items, knowledge] = await Promise.all([
      lab.inventoryFind({ character: 'Testmage', query: 'black crystal' }),
      lab.wikiSearch({ query: 'ensorcell', character: 'Testmage', limit: 2 }),
    ]);
    return { room: (state.room as { id: string }).id, item_count: items.items.length, topics: knowledge.items.map((x: any) => x.title) };
  `, 'compact', hub);
  assert.equal(result.success, true, result.error);
  assert.deepEqual(result.result, { room: '42', item_count: 2, topics: ['Ensorcell', 'Necromancy'] });
  assert.equal(result.lab_calls, 3);
  assert.equal(typeof result.startup_time_ms, 'number');
  assert.ok((result.startup_time_ms ?? -1) >= 0);
  assert.match(result.operation_id, /^op-/);
  assert.deepEqual(result.steps.map((step) => step.step_id), [1, 2, 3]);
  assert.ok(JSON.stringify(result.result).length < 100);
  assert.equal(new Set(hub.calls.map((call) => call.metadata?.operationId)).size, 1);
});

test('bridge errors remain catchable inside the isolate with code and payload', async () => {
  const result = await executeCode(`
    try { await lab.wikiSearch({ query: 'throw' }); return { caught: false }; }
    catch (error: any) { return { caught: true, message: error.message, code: error.code, query: error.payload.query }; }
  `, 'errors', new ExecutorHub());
  assert.equal(result.success, true, result.error);
  assert.deepEqual(result.result, { caught: true, message: 'bridge said no', code: 'bad_query', query: 'throw' });
  assert.equal(result.steps[0]?.success, false);
});

test('at most one perform reaches SessionHub even when the script catches the second denial', async () => {
  const hub = new ExecutorHub();
  const result = await executeCode(`
    const first = await lab.perform({ character: 'Testmage', capability: 'hunt.prepare' });
    try { await lab.perform({ character: 'Testmage', capability: 'room.loot' }); }
    catch (error: any) { return { first: first.status, second: error.message }; }
  `, 'one-perform', hub);
  assert.equal(result.success, true, result.error);
  assert.deepEqual(result.result, { first: 'succeeded', second: 'At most one lab.perform or lab.stop call is allowed per execute_code operation' });
  assert.equal(hub.calls.filter((call) => call.route === 'perform').length, 1);
});

test('an already-started unawaited call settles before the operation result is returned', async () => {
  class SlowHub extends ExecutorHub {
    settled = false;
    override async call(route: SessionHubRoute, payload: Record<string, unknown>, metadata?: BridgeMetadata): Promise<unknown> {
      await new Promise((resolve) => setTimeout(resolve, 30));
      const result = await super.call(route, payload, metadata);
      this.settled = true;
      return result;
    }
  }
  const hub = new SlowHub();
  const result = await executeCode(`lab.snapshot({ character: 'Testmage' }); return 'selected';`, 'unawaited', hub);
  assert.equal(result.success, true, result.error);
  assert.equal(result.result, 'selected');
  assert.equal(hub.settled, true);
  assert.equal(result.steps[0]?.success, true);
});

test('recursive execute_code and long isolate watch are rejected and catchable', async () => {
  const result = await executeCode(`
    const errors: string[] = [];
    try { await (lab as any).executeCode({ code: 'return 1' }); } catch (error: any) { errors.push(error.message); }
    try { await lab.watch({ character: 'Testmage', timeout_ms: 5000 }); } catch (error: any) { errors.push(error.message); }
    return errors;
  `, 'exclusions', new ExecutorHub());
  assert.equal(result.success, true, result.error);
  assert.match((result.result as string[])[0], /Recursive/);
  assert.match((result.result as string[])[1], /direct lab.watch/);
});

test('isolate has no filesystem, network, process, raw socket, terminal, or module authority', async () => {
  const result = await executeCode(`
    return {
      process: typeof (globalThis as any).process,
      require: typeof (globalThis as any).require,
      fetch: typeof (globalThis as any).fetch,
      WebSocket: typeof (globalThis as any).WebSocket,
      Deno: typeof (globalThis as any).Deno,
      Bun: typeof (globalThis as any).Bun,
    };
  `, 'ambient', new ExecutorHub());
  assert.equal(result.success, true, result.error);
  assert.deepEqual(result.result, {
    process: 'undefined', require: 'undefined', fetch: 'undefined', WebSocket: 'undefined', Deno: 'undefined', Bun: 'undefined',
  });
});

test('code, timeout, call count, and per-connection concurrency limits fail closed', async () => {
  const hub = new ExecutorHub();
  const oversize = await executeCode('x'.repeat(EXECUTOR_LIMITS.maxCodeBytes + 1), 'oversize', hub);
  assert.match(oversize.error ?? '', /Code exceeds maximum size/);

  const timeout = await executeCode('while (true) {}', 'timeout', hub, { timeout_ms: 100 });
  assert.match(timeout.error ?? '', /timed out after 100ms/i);

  const calls = await executeCode(`for (let i = 0; i < 21; i++) await lab.snapshot({ character: 'Testmage' }); return true;`, 'calls', hub);
  assert.match(calls.error ?? '', /Maximum 20 lab\.\* calls/);

  const jobs = [1, 2, 3].map(() => executeCode('while (true) {}', 'same-connection', hub, { timeout_ms: 250 }));
  const concurrency = await Promise.all(jobs);
  assert.equal(concurrency.filter((result) => /Maximum 2 concurrent/.test(result.error ?? '')).length, 1);
});

test('8MB isolate memory limit is configured and memory exhaustion is classified', async () => {
  assert.equal(EXECUTOR_LIMITS.memoryMb, 8);
  const result = await executeCode(`
    const values: string[] = [];
    while (true) values.push('x'.repeat(100000));
  `, 'memory', new ExecutorHub(), { timeout_ms: 3000 });
  assert.equal(result.success, false);
  assert.match(result.error ?? '', /8MB memory limit|timed out/i);
});
