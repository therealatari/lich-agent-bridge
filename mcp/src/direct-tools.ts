import { z } from 'zod';
import { entryByToolName, type DirectToolName } from './tool-registry.js';
import type { BridgeMetadata, SessionHubCaller } from './session-hub-client.js';

export function formatZodError(error: z.ZodError): string {
  return error.issues.map((issue) => `${issue.path.join('.') || '<root>'}: ${issue.message}`).join('; ');
}

export async function invokeDirectTool(
  client: SessionHubCaller,
  toolName: DirectToolName,
  input: unknown,
  metadata?: BridgeMetadata,
): Promise<unknown> {
  const entry = entryByToolName(toolName);
  if (!entry) throw new Error(`Unknown direct LAB tool '${toolName}'`);
  const parsed = entry.input.safeParse(input);
  if (!parsed.success) throw new Error(`Invalid params for '${toolName}': ${formatZodError(parsed.error)}`);
  return client.call(entry.route, parsed.data, metadata);
}
