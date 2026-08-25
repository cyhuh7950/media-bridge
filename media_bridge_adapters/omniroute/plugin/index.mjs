import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const ERROR_MESSAGE = "Media Bridge pre-upstream unavailable";
const CONTRACT_VERSION = "media-bridge-pre-upstream/v1";
const ENDPOINT_PATH = "/adapter/v1/pre-upstream";
const MAX_RESPONSE_BYTES = 512 * 1024;
const TIMEOUT_MS = 10_000;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const RESULT_KEYS = new Set([
  "body",
  "capability",
  "decision_token",
  "error",
  "input_digest",
  "original_media_removed",
  "output_digest",
  "provider",
  "status",
  "target_model",
]);
const MEDIA_TYPES = new Set(["input_image", "input_file", "image_url"]);
const MEDIA_KEYS = new Set(["asset_id", "file_data", "file_id", "file_url", "image_url"]);

function fail() {
  throw new Error(ERROR_MESSAGE);
}

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function canonical(value, seen = new Set()) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail();
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => canonical(item, seen));
  if (!plainObject(value) || seen.has(value)) fail();
  seen.add(value);
  const output = {};
  for (const key of Object.keys(value).sort()) {
    if (value[key] === undefined) fail();
    output[key] = canonical(value[key], seen);
  }
  seen.delete(value);
  return output;
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(canonical(value))).digest("hex");
}

function hasMedia(value) {
  if (typeof value === "string") {
    const lowered = value.toLowerCase();
    return lowered.startsWith("data:image/") || lowered.startsWith("data:application/pdf");
  }
  if (Array.isArray(value)) return value.some(hasMedia);
  if (!plainObject(value)) return false;
  if (typeof value.type === "string" && MEDIA_TYPES.has(value.type)) return true;
  for (const key of MEDIA_KEYS) {
    if (typeof value[key] === "string" && value[key] !== "") return true;
  }
  return Object.values(value).some(hasMedia);
}

function endpoint() {
  const raw = process.env.MEDIA_BRIDGE_ADAPTER_ENDPOINT;
  if (!raw || raw.trim() !== raw) fail();
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    fail();
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  if (
    (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.pathname !== ENDPOINT_PATH ||
    parsed.search !== "" ||
    parsed.hash !== ""
  ) {
    fail();
  }
  return parsed.toString();
}

function secrets() {
  const credential = process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL;
  const decisionSecret = process.env.MEDIA_BRIDGE_ADAPTER_DECISION_HMAC;
  if (
    !credential ||
    !credential.startsWith("mbc_") ||
    credential.trim() !== credential ||
    credential.length > 160 ||
    !decisionSecret ||
    decisionSecret.length < 32 ||
    decisionSecret.trim() !== decisionSecret
  ) {
    fail();
  }
  return { credential, decisionSecret };
}

async function boundedBody(response) {
  if (!response.body) fail();
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_RESPONSE_BYTES) fail();
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function validateDecision(result, context, decisionSecret) {
  if (!plainObject(result) || Object.keys(result).some((key) => !RESULT_KEYS.has(key))) fail();
  if (
    !["prepared", "unchanged"].includes(result.status) ||
    !["vision", "non_vision"].includes(result.capability) ||
    result.provider !== context.provider ||
    result.target_model !== context.model ||
    result.error !== null ||
    !plainObject(result.body) ||
    typeof result.original_media_removed !== "boolean" ||
    !DIGEST.test(result.input_digest) ||
    !DIGEST.test(result.output_digest) ||
    !TOKEN.test(result.decision_token)
  ) {
    fail();
  }
  if (result.input_digest !== digest(context.body) || result.output_digest !== digest(result.body)) {
    fail();
  }
  if (
    result.capability === "non_vision" &&
    (!result.original_media_removed || hasMedia(result.body))
  ) {
    fail();
  }
  const signed = [
    result.provider,
    result.target_model,
    result.capability,
    result.status,
    result.input_digest,
    result.output_digest,
    result.original_media_removed ? "1" : "0",
  ].join("\0");
  const expected = createHmac("sha256", decisionSecret).update(signed).digest();
  const actual = Buffer.from(result.decision_token, "base64url");
  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) fail();
  return result.body;
}

export async function onRequest(context) {
  try {
    if (
      !plainObject(context) ||
      !IDENTIFIER.test(context.requestId) ||
      !IDENTIFIER.test(context.provider) ||
      !IDENTIFIER.test(context.model) ||
      !plainObject(context.body)
    ) {
      fail();
    }
    const url = endpoint();
    const { credential, decisionSecret } = secrets();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        redirect: "manual",
        signal: controller.signal,
        headers: {
          accept: "application/json",
          authorization: `Bearer ${credential}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          contract_version: CONTRACT_VERSION,
          request_id: context.requestId,
          wire_format: "openai-responses",
          provider: context.provider,
          target_model: context.model,
          body: canonical(context.body),
        }),
      });
    } finally {
      clearTimeout(timer);
    }
    if (
      response.status !== 200 ||
      response.headers.get("content-type")?.split(";", 1)[0] !== "application/json"
    ) {
      fail();
    }
    const text = await boundedBody(response);
    let result;
    try {
      result = JSON.parse(text);
    } catch {
      fail();
    }
    return { body: validateDecision(result, context, decisionSecret) };
  } catch {
    fail();
  }
}
