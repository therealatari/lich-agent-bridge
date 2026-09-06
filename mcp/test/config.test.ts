import assert from 'node:assert/strict';
import test from 'node:test';
import { configFromEnvironment } from '../src/config.js';


const NAMES = [
  'LAB_SESSION_HUB_TOKEN',
  'LAB_SESSION_HUB_URL',
  'LAB_MCP_PORT',
] as const;


async function withEnvironment(
  values: Partial<Record<(typeof NAMES)[number], string>>,
  callback: () => void,
): Promise<void> {
  const saved = Object.fromEntries(NAMES.map((name) => [name, process.env[name]]));
  try {
    for (const name of NAMES) delete process.env[name];
    Object.assign(process.env, values);
    callback();
  } finally {
    for (const name of NAMES) {
      const value = saved[name];
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}


test('direct npm launch retains the environment adapter and defaults', async () => {
  await withEnvironment({ LAB_SESSION_HUB_TOKEN: 'direct-token' }, () => {
    const config = configFromEnvironment();
    assert.equal(config.host, '127.0.0.1');
    assert.equal(config.port, 18766);
    assert.equal(config.sessionHubUrl.href, 'http://127.0.0.1:18765/');
    assert.equal(config.sessionHubToken, 'direct-token');
  });
});


test('direct npm launch accepts explicit loopback environment values', async () => {
  await withEnvironment({
    LAB_SESSION_HUB_TOKEN: 'direct-token',
    LAB_SESSION_HUB_URL: 'http://localhost:19000',
    LAB_MCP_PORT: '19001',
  }, () => {
    const config = configFromEnvironment();
    assert.equal(config.port, 19001);
    assert.equal(config.sessionHubUrl.href, 'http://localhost:19000/');
  });
});


test('direct npm launch continues to reject non-loopback SessionHub URLs', async () => {
  await withEnvironment({
    LAB_SESSION_HUB_TOKEN: 'direct-token',
    LAB_SESSION_HUB_URL: 'https://example.com',
  }, () => {
    assert.throws(configFromEnvironment, /http:\/\/ loopback URL/);
  });
});
