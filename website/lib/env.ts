import fs from "node:fs";
import path from "node:path";

/**
 * Server-side only: read the agent project's .env (one folder up) so the
 * website shares NOVA's LiveKit credentials instead of duplicating them.
 * Real process env vars win over file values (for Vercel deployment later).
 */
export function loadAgentEnv(): Record<string, string> {
  const out: Record<string, string> = {};
  const envPath = path.resolve(process.cwd(), "..", ".env");
  try {
    for (const line of fs.readFileSync(envPath, "utf-8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
      if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  } catch {
    // no file (e.g. deployed) - rely on process.env
  }
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined) out[k] = v;
  }
  return out;
}
