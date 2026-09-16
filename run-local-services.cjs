const { spawn } = require('node:child_process');
const fs = require('node:fs');

const root = 'E:\\PaperGuideAI';
const python = `${root}\\.venv\\Scripts\\python.exe`;
const cli = `${root}\\.venv\\Scripts\\paperguide.exe`;
const node = 'F:\\nodejs22\\node.exe';

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;

  const contents = fs.readFileSync(filePath, 'utf8');
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    const separator = line.indexOf('=');
    if (separator < 1) continue;

    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    // Process-level variables take priority. Loading .env.local first gives it
    // priority over .env without ever printing credential values.
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadEnvFile(`${root}\\.env.local`);
loadEnvFile(`${root}\\.env`);

const productionEnv = {
  PAPERGUIDE_MODE: 'production',
  PAPERGUIDE_LLM_PROVIDER: process.env.PAPERGUIDE_LLM_PROVIDER || 'openai',
  PAPERGUIDE_MODEL_NAME: process.env.PAPERGUIDE_MODEL_NAME || 'gpt-5.4',
};

const requiredCredential = {
  deepseek: 'DEEPSEEK_API_KEY',
  openai: 'OPENAI_API_KEY',
  anthropic: 'ANTHROPIC_API_KEY',
}[productionEnv.PAPERGUIDE_LLM_PROVIDER.toLowerCase()];

if (requiredCredential && !process.env[requiredCredential]) {
  console.error(
    `Production mode is enabled, but ${requiredCredential} is missing. ` +
    `Set it in ${root}\\.env.local before submitting a task.`,
  );
}

function launch(command, args, cwd, env = {}) {
  const label = args.some((arg) => arg.endsWith('vite.js'))
    ? 'vite'
    : args.includes('paperguide.api.__main__')
      ? 'api'
      : 'host';
  const out = fs.openSync(`${root}\\${label}.log`, 'a');
  const err = fs.openSync(`${root}\\${label}.err.log`, 'a');
  const child = spawn(command, args, {
    cwd,
    detached: true,
    windowsHide: true,
    stdio: ['ignore', out, err],
    env: { ...process.env, ...env },
  });
  child.unref();
  console.log(`${command} pid=${child.pid}`);
}

launch(python, ['-m', 'paperguide.api.__main__'], root, productionEnv);
launch(cli, ['server', 'start'], root, productionEnv);
launch(node, [
  `${root}\\frontend-runtime\\node_modules\\vite\\bin\\vite.js`,
  '--config', `${root}\\frontend-runtime\\vite.config.mjs`,
  '--host', '127.0.0.1', '--port', '5173',
], `${root}\\frontend-runtime`);
