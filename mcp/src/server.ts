import express, { type Request } from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import type { AdapterConfig } from './config.js';
import { DIRECT_TOOLS, EXECUTE_CODE_INPUT } from './tool-registry.js';
import { invokeDirectTool } from './direct-tools.js';
import { executeCode } from './executor.js';
import { SDK_TYPE_DECLARATIONS } from './sdk-types.generated.js';
import { SessionHubClient } from './session-hub-client.js';

export const SERVER_INSTRUCTIONS = `LAB exposes one local GemStone IV session authority. Read lab.snapshot before acting; it is current live state and costs no game command. lab.inventory_find locations are historical observations, never proof of current possession. Use lab.watch for meaningful changes. Use lab.perform only for registered outcome-oriented capabilities; the Python SessionHub and ActionBroker remain final policy authorities. Prefer direct tools for one call and lab.execute_code for three or more dependent reads or compact filtering. Never infer success from command dispatch.`;

function connectionId(req: Request): string {
  const explicit = req.header('x-lab-connection-id') ?? req.header('mcp-session-id');
  return explicit?.slice(0, 256) || `${req.socket.remoteAddress ?? 'local'}:${req.socket.remotePort ?? 0}`;
}

function textResult(value: unknown) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(value) }] };
}

export function createApp(config: AdapterConfig) {
  const app = express();
  const client = new SessionHubClient(config.sessionHubUrl, config.sessionHubToken);
  app.disable('x-powered-by');
  app.use(express.json({ limit: '256kb', strict: true }));

  app.get('/health', (_req, res) => {
    res.json({ service: 'lich-agent-bridge-mcp', version: '0.1.0', status: 'ok', transport: 'streamable-http' });
  });

  app.post('/mcp', async (req, res) => {
    const server = new McpServer(
      { name: 'lich-agent-bridge', version: '0.1.0' },
      { instructions: SERVER_INSTRUCTIONS },
    );
    const connId = connectionId(req);
    for (const entry of DIRECT_TOOLS) {
      server.registerTool(
        entry.toolName,
        {
          description: entry.description,
          inputSchema: entry.input,
          annotations: {
            readOnlyHint: entry.route !== 'perform' && entry.route !== 'operationStop',
            destructiveHint: entry.route === 'perform' || entry.route === 'operationStop',
            idempotentHint: entry.route !== 'perform' && entry.route !== 'operationStop',
            openWorldHint: false,
          },
        },
        async (input: unknown) => textResult(await invokeDirectTool(client, entry.toolName, input)),
      );
    }
    server.registerTool(
      'lab.execute_code',
      {
        description: `Execute bounded TypeScript against the isolated LAB SDK. Use for dependent reads, compact aggregation, or reads followed by at most one perform or stop. Long watches must use direct lab.watch.\n${SDK_TYPE_DECLARATIONS}`,
        inputSchema: EXECUTE_CODE_INPUT,
        annotations: {
          readOnlyHint: false,
          destructiveHint: true,
          idempotentHint: false,
          openWorldHint: false,
        },
      },
      async ({ code, timeout_ms }) => textResult(await executeCode(code, connId, client, { timeout_ms })),
    );

    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } finally {
      await transport.close();
      await server.close();
    }
  });

  app.get('/mcp', (_req, res) => res.status(405).json({ error: 'method_not_allowed', detail: 'Stateless MCP endpoint accepts POST only.' }));
  app.delete('/mcp', (_req, res) => res.status(405).json({ error: 'method_not_allowed', detail: 'Stateless MCP endpoint accepts POST only.' }));
  return app;
}
