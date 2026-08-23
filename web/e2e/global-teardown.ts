import fs from "node:fs/promises";

const parent = "/tmp/media_bridge_p2a_tools_01a02e88";
const stateFile = `${parent}/e2e-state.json`;
const runtimeDirectory = `${parent}/e2e-runtime`;

async function removeOwned(path: string, kind: "file" | "directory") {
  let status: Awaited<ReturnType<typeof fs.lstat>>;
  try {
    status = await fs.lstat(path);
  } catch (error: unknown) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") return;
    throw error;
  }
  const currentUid = typeof process.getuid === "function" ? process.getuid() : null;
  if (
    status.isSymbolicLink()
    || (currentUid !== null && status.uid !== currentUid)
    || (kind === "file" ? !status.isFile() : !status.isDirectory())
  ) {
    throw new Error("unsafe e2e cleanup target");
  }
  await fs.rm(path, { force: true, recursive: kind === "directory" });
}

export default async function globalTeardown() {
  await removeOwned(stateFile, "file");
  await removeOwned(runtimeDirectory, "directory");
}
