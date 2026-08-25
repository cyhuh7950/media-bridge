import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import test from "node:test";

import { onRequest } from "../../../media_bridge_adapters/omniroute/plugin/index.mjs";

const originalFetch = globalThis.fetch;
const secret = "decision-secret-material-at-least-32-bytes";
const credential = "mbc_adapter_private_test_value";

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonical(value[key])])
    );
  }
  return value;
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(canonical(value))).digest("hex");
}

function sign(result) {
  const signed = [
    result.provider,
    result.target_model,
    result.capability,
    result.status,
    result.input_digest,
    result.output_digest,
    result.original_media_removed ? "1" : "0",
  ].join("\0");
  return {
    ...result,
    decision_token: createHmac("sha256", secret).update(signed).digest("base64url"),
  };
}

function decision(context, body, overrides = {}) {
  return sign({
    status: "prepared",
    provider: context.provider,
    target_model: context.model,
    capability: "non_vision",
    body,
    original_media_removed: true,
    input_digest: digest(context.body),
    output_digest: digest(body),
    decision_token: "",
    error: null,
    ...overrides,
  });
}

function context() {
  return {
    requestId: "req-omniroute-product-plugin",
    provider: "openai",
    model: "text-model",
    body: {
      model: "text-model",
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: "explain" },
            { type: "image_url", image_url: { url: "data:image/png;base64,AA==" } },
          ],
        },
      ],
    },
    metadata: {},
  };
}

function setEnvironment() {
  process.env.MEDIA_BRIDGE_ADAPTER_ENDPOINT =
    "https://bridge.example/adapter/v1/pre-upstream";
  process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL = credential;
  process.env.MEDIA_BRIDGE_ADAPTER_DECISION_HMAC = secret;
}

function clearEnvironment() {
  delete process.env.MEDIA_BRIDGE_ADAPTER_ENDPOINT;
  delete process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL;
  delete process.env.MEDIA_BRIDGE_ADAPTER_DECISION_HMAC;
}

test.afterEach(() => {
  globalThis.fetch = originalFetch;
  clearEnvironment();
});

test("validated prepared text is the only body returned to OmniRoute", async () => {
  setEnvironment();
  const input = context();
  const sanitized = {
    model: "text-model",
    messages: [{ role: "user", content: "converted image context" }],
  };
  let captured;
  globalThis.fetch = async (url, init) => {
    captured = { url: String(url), init, payload: JSON.parse(init.body) };
    return Response.json(decision(input, sanitized));
  };

  const result = await onRequest(input);

  assert.deepEqual(result, { body: sanitized });
  assert.equal(captured.url, "https://bridge.example/adapter/v1/pre-upstream");
  assert.equal(captured.init.redirect, "manual");
  assert.equal(captured.init.headers.authorization, `Bearer ${credential}`);
  assert.deepEqual(captured.payload, {
    contract_version: "media-bridge-pre-upstream/v1",
    request_id: "req-omniroute-product-plugin",
    wire_format: "openai-responses",
    provider: "openai",
    target_model: "text-model",
    body: input.body,
  });
  assert.equal(JSON.stringify(result).includes("data:image"), false);
});

for (const [name, mutate] of [
  ["target mismatch", (value) => sign({ ...value, target_model: "other-model" })],
  ["invalid HMAC", (value) => ({ ...value, decision_token: "A".repeat(43) })],
  [
    "remaining media",
    (value) => sign({
      ...value,
      body: context().body,
      output_digest: digest(context().body),
      original_media_removed: true,
    }),
  ],
]) {
  test(`${name} fails closed without reflecting request or Secret data`, async () => {
    setEnvironment();
    const input = context();
    const safe = { model: "text-model", messages: [{ role: "user", content: "safe" }] };
    globalThis.fetch = async () => Response.json(mutate(decision(input, safe)));

    await assert.rejects(onRequest(input), (error) => {
      assert.equal(error.message, "Media Bridge pre-upstream unavailable");
      assert.equal(String(error).includes(credential), false);
      assert.equal(String(error).includes("data:image"), false);
      return true;
    });
  });
}

test("invalid endpoint and redirects fail closed without following another host", async () => {
  setEnvironment();
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(null, { status: 307, headers: { location: "https://other.example/" } });
  };
  await assert.rejects(onRequest(context()), /Media Bridge pre-upstream unavailable/);
  assert.equal(calls, 1);

  process.env.MEDIA_BRIDGE_ADAPTER_ENDPOINT =
    "http://bridge.internal/adapter/v1/pre-upstream";
  await assert.rejects(onRequest(context()), /Media Bridge pre-upstream unavailable/);
  assert.equal(calls, 1);
});

test("missing Secret and oversized responses fail closed", async () => {
  setEnvironment();
  delete process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response("x".repeat(600_000), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  await assert.rejects(onRequest(context()), /Media Bridge pre-upstream unavailable/);
  assert.equal(calls, 0);

  process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL = credential;
  await assert.rejects(onRequest(context()), /Media Bridge pre-upstream unavailable/);
  assert.equal(calls, 1);
});
