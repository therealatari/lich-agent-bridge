import { isIP } from 'node:net';

export interface AdapterConfig {
  host: string;
  port: number;
  sessionHubUrl: URL;
  sessionHubToken: string;
}

function integerEnv(name: string, fallback: number, minimum: number, maximum: number): number {
  const raw = process.env[name];
  const parsed = raw === undefined ? fallback : Number(raw);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function loopbackUrl(raw: string): URL {
  const url = new URL(raw);
  const host = url.hostname.replace(/^\[|\]$/g, '');
  const loopback = host === 'localhost' || host === '::1' || (isIP(host) === 4 && host.startsWith('127.'));
  if (url.protocol !== 'http:' || !loopback) {
    throw new Error('LAB_SESSION_HUB_URL must be an http:// loopback URL');
  }
  return url;
}

export function configFromEnvironment(): AdapterConfig {
  const token = process.env.LAB_SESSION_HUB_TOKEN?.trim();
  if (!token) throw new Error('LAB_SESSION_HUB_TOKEN is required');
  return {
    host: '127.0.0.1',
    port: integerEnv('LAB_MCP_PORT', 18766, 1, 65_535),
    sessionHubUrl: loopbackUrl(process.env.LAB_SESSION_HUB_URL ?? 'http://127.0.0.1:18765'),
    sessionHubToken: token,
  };
}
