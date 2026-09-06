import { entryBySdkMethod } from './tool-registry.js';
import { formatZodError } from './direct-tools.js';
import type { SessionHubCaller } from './session-hub-client.js';

export const MAX_ISOLATE_WATCH_MS = 1_000;

export interface ExecutionStep {
  step_id: number;
  tool: string;
  success: boolean;
  error?: string;
}

export interface BridgeState {
  operationId: string;
  performCalls: number;
  steps: ExecutionStep[];
}

export function createBridge(client: SessionHubCaller, state: BridgeState) {
  return {
    async call(method: string, params: unknown): Promise<unknown> {
      const stepId = state.steps.length + 1;
      const step: ExecutionStep = { step_id: stepId, tool: `lab.${method}`, success: false };
      state.steps.push(step);
      try {
        if (method === 'executeCode' || method === 'execute_code') {
          throw new Error('Recursive lab.execute_code is forbidden');
        }
        const entry = entryBySdkMethod(method);
        if (!entry) throw new Error(`Unknown LAB SDK method '${method}'`);
        step.tool = entry.toolName;
        if (entry.route === 'perform') {
          state.performCalls += 1;
          if (state.performCalls > 1) throw new Error('At most one lab.perform call is allowed per execute_code operation');
        }
        const parsed = entry.input.safeParse(params ?? {});
        if (!parsed.success) {
          throw new Error(`Invalid params for SDK method '${method}' (${entry.toolName}): ${formatZodError(parsed.error)}`);
        }
        if (entry.route === 'watch') {
          const timeout = (parsed.data as { timeout_ms?: number }).timeout_ms ?? 0;
          if (timeout > MAX_ISOLATE_WATCH_MS) {
            throw new Error(`Isolate watch timeout is capped at ${MAX_ISOLATE_WATCH_MS}ms; use direct lab.watch for blocking watches`);
          }
        }
        const result = await client.call(entry.route, parsed.data, { operationId: state.operationId, stepId });
        step.success = true;
        return result;
      } catch (error) {
        step.error = error instanceof Error ? error.message : String(error);
        throw error;
      }
    },
  };
}
