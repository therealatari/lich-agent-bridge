import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { generatedSdkTypes } from './sdk-type-generator.js';

const output = fileURLToPath(new URL('../src/sdk-types.generated.ts', import.meta.url));
if (readFileSync(output, 'utf8') !== generatedSdkTypes()) {
  process.stderr.write('src/sdk-types.generated.ts is stale; run npm run generate:sdk-types\n');
  process.exitCode = 1;
}
