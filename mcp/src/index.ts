import { configFromEnvironment } from './config.js';
import { createApp } from './server.js';

const config = configFromEnvironment();
const app = createApp(config);
app.listen(config.port, config.host, () => {
  process.stdout.write(`LAB MCP listening on http://${config.host}:${config.port}/mcp\n`);
});
