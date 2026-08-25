import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const sourceRoot = process.env.OMNIROUTE_SOURCE_ROOT;

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

test(
  "bundled plugin crosses the exact OmniRoute loader with declared Secret env only",
  { skip: !sourceRoot },
  async () => {
    const productRoot = new URL("../../..", import.meta.url);
    const pluginPath = new URL(
      "media_bridge_adapters/omniroute/plugin/index.mjs",
      productRoot
    );
    const pluginSource = await readFile(pluginPath);
    const [{ PluginManifestSchema, applyDefaults }, { loadPlugin, computeIntegrity }] =
      await Promise.all([
        import(pathToFileURL(join(sourceRoot, "src/lib/plugins/manifest.ts")).href),
        import(pathToFileURL(join(sourceRoot, "src/lib/plugins/loader.ts")).href),
      ]);
    const decisionSecret = "decision-secret-material-at-least-32-bytes";
    const credential = "mbc_loader_integration_private";
    const sanitized = {
      model: "text-model",
      messages: [{ role: "user", content: "converted through exact loader" }],
    };
    const server = createServer((request, response) => {
      let raw = "";
      request.setEncoding("utf-8");
      request.on("data", (chunk) => {
        raw += chunk;
      });
      request.on("end", () => {
        assert.equal(request.headers.authorization, `Bearer ${credential}`);
        const payload = JSON.parse(raw);
        const result = {
          status: "prepared",
          provider: payload.provider,
          target_model: payload.target_model,
          capability: "non_vision",
          body: sanitized,
          original_media_removed: true,
          input_digest: digest(payload.body),
          output_digest: digest(sanitized),
          decision_token: "",
          error: null,
        };
        const signed = [
          result.provider,
          result.target_model,
          result.capability,
          result.status,
          result.input_digest,
          result.output_digest,
          "1",
        ].join("\0");
        result.decision_token = createHmac("sha256", decisionSecret)
          .update(signed)
          .digest("base64url");
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify(result));
      });
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.notEqual(address, null);
    assert.equal(typeof address, "object");
    process.env.MEDIA_BRIDGE_ADAPTER_ENDPOINT =
      `http://127.0.0.1:${address.port}/adapter/v1/pre-upstream`;
    process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL = credential;
    process.env.MEDIA_BRIDGE_ADAPTER_DECISION_HMAC = decisionSecret;
    process.env.MEDIA_BRIDGE_UNDECLARED_VALUE = "must_not_be_forwarded";
    const manifest = applyDefaults(
      PluginManifestSchema.parse({
        name: "media-bridge-pre-upstream",
        version: "0.1.0",
        main: "index.mjs",
        integrity: computeIntegrity(pluginSource.toString("utf-8")),
        hooks: { onRequest: true, securityCritical: true },
        requires: {
          omniroute: "=3.8.50",
          permissions: ["network", "env"],
          secretEnv: [
            "MEDIA_BRIDGE_ADAPTER_ENDPOINT",
            "MEDIA_BRIDGE_ADAPTER_CREDENTIAL",
            "MEDIA_BRIDGE_ADAPTER_DECISION_HMAC",
          ],
        },
      })
    );
    const loaded = await loadPlugin(pluginPath.pathname, manifest);
    try {
      const result = await loaded.plugin.onRequest({
        requestId: "req-loader-integration",
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
      });
      assert.deepEqual(result, { body: sanitized });
      assert.equal(JSON.stringify(result).includes("data:image"), false);
    } finally {
      loaded.cleanup();
      await new Promise((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve()))
      );
      delete process.env.MEDIA_BRIDGE_ADAPTER_ENDPOINT;
      delete process.env.MEDIA_BRIDGE_ADAPTER_CREDENTIAL;
      delete process.env.MEDIA_BRIDGE_ADAPTER_DECISION_HMAC;
      delete process.env.MEDIA_BRIDGE_UNDECLARED_VALUE;
    }
  }
);
