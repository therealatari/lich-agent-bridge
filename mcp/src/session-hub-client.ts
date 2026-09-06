import { SESSION_HUB_ROUTES, type SessionHubRoute } from './routes.js';

export interface BridgeMetadata {
  operationId?: string;
  stepId?: number;
}

export class SessionHubError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly payload: unknown,
  ) {
    super(message);
    this.name = 'SessionHubError';
  }
}

export interface SessionHubCaller {
  call(route: SessionHubRoute, payload: Record<string, unknown>, metadata?: BridgeMetadata): Promise<unknown>;
}

export class SessionHubClient implements SessionHubCaller {
  constructor(
    private readonly baseUrl: URL,
    private readonly token: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async call(routeName: SessionHubRoute, payload: Record<string, unknown>, metadata: BridgeMetadata = {}): Promise<unknown> {
    const result = await this.callOnce(routeName, payload, metadata);
    if (routeName !== 'perform') return result;
    return this.waitForOperation(result, metadata);
  }

  private async callOnce(routeName: SessionHubRoute, payload: Record<string, unknown>, metadata: BridgeMetadata = {}): Promise<unknown> {
    const route = SESSION_HUB_ROUTES[routeName];
    const target = new URL(route.path, this.baseUrl);
    const watchTimeout = (routeName === 'watch' || routeName === 'operationWatch')
      && typeof payload.timeout_ms === 'number' ? payload.timeout_ms : 0;
    const timeoutMs = Math.max(12_000, watchTimeout + 2_000);
    const headers: Record<string, string> = {
      authorization: `Bearer ${this.token}`,
      'content-type': 'application/json',
      accept: 'application/json',
    };
    if (metadata.operationId) headers['x-lab-operation-id'] = metadata.operationId;
    if (metadata.stepId !== undefined) headers['x-lab-step-id'] = String(metadata.stepId);

    let response: Response;
    try {
      response = await this.fetchImpl(target, {
        method: route.method,
        headers,
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (error) {
      throw new SessionHubError(
        `SessionHub request failed: ${error instanceof Error ? error.message : String(error)}`,
        0,
        'transport_error',
        null,
      );
    }

    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try { body = JSON.parse(text); }
      catch { body = text; }
    }
    if (!response.ok) {
      const record = body && typeof body === 'object' ? body as Record<string, unknown> : {};
      const code = typeof record.error === 'string' ? record.error : `http_${response.status}`;
      const detail = typeof record.detail === 'string' ? `: ${record.detail}` : '';
      throw new SessionHubError(`SessionHub ${routeName} failed [${code}]${detail}`, response.status, code, body);
    }
    return body;
  }

  private async waitForOperation(started: unknown, metadata: BridgeMetadata): Promise<unknown> {
    if (!started || typeof started !== 'object') {
      throw new SessionHubError('SessionHub perform returned an invalid operation', 0, 'invalid_operation', started);
    }
    let operation = started as Record<string, unknown>;
    const operationId = operation.operation_id;
    if (typeof operationId !== 'string' || !operationId) {
      throw new SessionHubError('SessionHub perform omitted operation_id', 0, 'invalid_operation', started);
    }
    const terminal = new Set(['succeeded', 'failed', 'timed_out', 'interrupted']);
    let cursor = '0';
    const deadline = Date.now() + 35_000;
    while (!terminal.has(String(operation.status))) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        throw new SessionHubError('SessionHub operation outcome timed out', 0, 'operation_timeout', operation);
      }
      const page = await this.callOnce(
        'operationWatch',
        {
          operation_id: operationId,
          cursor,
          timeout_ms: Math.min(10_000, remaining),
        },
        { ...metadata, operationId },
      );
      if (!page || typeof page !== 'object') {
        throw new SessionHubError('SessionHub operation watch returned invalid data', 0, 'invalid_operation', page);
      }
      const record = page as Record<string, unknown>;
      if (!record.operation || typeof record.operation !== 'object') {
        throw new SessionHubError('SessionHub operation watch omitted operation', 0, 'invalid_operation', page);
      }
      operation = record.operation as Record<string, unknown>;
      if (typeof record.cursor === 'string') cursor = record.cursor;
    }
    return operation;
  }
}
