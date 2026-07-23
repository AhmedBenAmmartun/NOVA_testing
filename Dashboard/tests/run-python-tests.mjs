import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const configured = process.env.NOVA_PYTHON;
const candidates = [
  configured,
  resolve(projectRoot, '.venv/Scripts/python.exe'),
  resolve(projectRoot, '.venv/bin/python'),
  resolve(projectRoot, 'venv/Scripts/python.exe'),
  resolve(projectRoot, 'venv/bin/python'),
  'python',
  'python3',
].filter(Boolean);

for (const executable of candidates) {
  if (executable.includes('/') || executable.includes('\\')) {
    if (!existsSync(executable)) continue;
  }
  const result = spawnSync(
    executable,
    ['-m', 'unittest', 'discover', '-s', 'Dashboard/tests', '-p', 'test_*.py', '-v'],
    { cwd: projectRoot, encoding: 'utf8' },
  );
  if (result.error?.code === 'ENOENT') continue;
  process.stdout.write(result.stdout || '');
  process.stderr.write(result.stderr || '');
  process.exit(result.status ?? 1);
}

throw new Error('Python was not found. Set NOVA_PYTHON to the NOVA venv interpreter.');
