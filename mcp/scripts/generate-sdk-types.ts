import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { generatedSdkTypes } from './sdk-type-generator.js';

const output = fileURLToPath(new URL('../src/sdk-types.generated.ts', import.meta.url));
writeFileSync(output, generatedSdkTypes());
