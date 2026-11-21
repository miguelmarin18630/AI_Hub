import { AsyncLocalStorage } from "node:async_hooks";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { UserConfig } from "./types.ts";

export const APP_DIR = path.resolve(
  process.env.AIHUB_DATA_DIR || path.join(os.tmpdir(), "aihub-data")
);

const activeDirStorage = new AsyncLocalStorage<string | null>();

export function runWithAppDir<T>(dir: string | null, fn: () => T): T {
  return activeDirStorage.run(dir ? path.resolve(dir) : null, fn);
}

export function appDir(): string {
  return activeDirStorage.getStore() || APP_DIR;
}

export function configPath(): string {
  return path.join(appDir(), "config.json");
}

export function cachePath(): string {
  return path.join(appDir(), "cache.json");
}

export function defaultProjectsRoot(baseDir?: string): string {
  return path.join(baseDir || appDir(), "proyectos");
}

export function defaultOutputRoot(baseDir?: string): string {
  return path.join(baseDir || appDir(), "salida");
}

export function defaultConfig(baseDir?: string): UserConfig {
  const base = baseDir || appDir();
  return {
    openrouter_api_key: "",
    workdir: "",
    projects_root: defaultProjectsRoot(base),
    output_root: defaultOutputRoot(base),
    auto_refresh: true,
    last_provider: "openrouter",
    last_category: "code",
    last_models: {},
    custom_providers: [],
    usage: {},
    favorite_models: [],
  };
}

export function loadConfig(): UserConfig {
  const data = defaultConfig();
  try {
    const raw = JSON.parse(fs.readFileSync(configPath(), "utf-8"));
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      Object.assign(data, raw);
    }
  } catch {
    // Use defaults if config does not exist yet
  }
  if (!data.output_root) {
    data.output_root = defaultOutputRoot();
  }
  if (!data.projects_root) {
    data.projects_root = defaultProjectsRoot();
  }
  if (!Array.isArray(data.custom_providers)) {
    data.custom_providers = [];
  }
  if (!Array.isArray(data.favorite_models)) {
    data.favorite_models = [];
  }
  if (!data.usage || typeof data.usage !== "object") {
    data.usage = {};
  }
  return data;
}

export function saveConfig(cfg: UserConfig): void {
  const base = appDir();
  fs.mkdirSync(base, { recursive: true });
  const target = configPath();
  const tmp = `${target}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(cfg, null, 2), "utf-8");
  fs.renameSync(tmp, target);
}

export function updateConfig(changes: Partial<UserConfig>): UserConfig {
  const data = loadConfig();
  Object.assign(data, changes);
  saveConfig(data);
  return data;
}

export function openrouterKey(cfg?: UserConfig, allowEnv = true): string {
  const current = cfg || loadConfig();
  const stored = String(current.openrouter_api_key || "").trim();
  if (stored) return stored;
  if (!allowEnv) return "";
  return String(process.env.OPENROUTER_API_KEY || "").trim();
}

export function imageDir(cfg?: UserConfig): string {
  const current = cfg || loadConfig();
  const dir = path.join(current.output_root || defaultOutputRoot(), "imagenes");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

export function videoDir(cfg?: UserConfig): string {
  const current = cfg || loadConfig();
  const dir = path.join(current.output_root || defaultOutputRoot(), "videos");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}
