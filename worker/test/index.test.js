import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";

import worker, {
  handlePostback,
  makeSwitchBotHeaders,
  pressSwitchBot,
  verifyLineSignature,
} from "../src/index.js";

const encoder = new TextEncoder();

class FakeD1 {
  constructor() {
    this.events = new Set();
  }

  prepare(sql) {
    const database = this;
    return {
      args: [],
      bind(...args) {
        this.args = args;
        return this;
      },
      async run() {
        if (sql.startsWith("INSERT OR IGNORE INTO processed_events")) {
          const [eventId] = this.args;
          if (database.events.has(eventId)) return { meta: { changes: 0 } };
          database.events.add(eventId);
          return { meta: { changes: 1 } };
        }
        throw new Error(`Unexpected SQL in test: ${sql}`);
      },
    };
  }
}

function testEnv() {
  return {
    DB: new FakeD1(),
    LINE_CHANNEL_ACCESS_TOKEN: "line-access-token",
    LINE_CHANNEL_SECRET: "line-secret",
    LINE_USER_ID: "U123",
    SWITCHBOT_TOKEN: "switchbot-token",
    SWITCHBOT_SECRET: "switchbot-secret",
    SWITCHBOT_INTERCOM_DEVICE_ID: "intercom-device",
    SWITCHBOT_UNLOCK_DEVICE_ID: "unlock-device",
  };
}

test("LINE webhook signature is verified against the raw body", async () => {
  const body = encoder.encode('{"events":[]}');
  const signature = createHmac("sha256", "channel-secret")
    .update(body)
    .digest("base64");

  assert.equal(
    await verifyLineSignature(body, signature, "channel-secret"),
    true,
  );
  assert.equal(await verifyLineSignature(body, signature, "wrong-secret"), false);
  assert.equal(await verifyLineSignature(body, "invalid", "channel-secret"), false);
});

test("SwitchBot headers use the OpenAPI v1.1 signature", async () => {
  const headers = await makeSwitchBotHeaders(
    "token",
    "secret",
    "1700000000000",
    "fixed-nonce",
  );
  const expected = createHmac("sha256", "secret")
    .update("token1700000000000fixed-nonce")
    .digest("base64");

  assert.equal(headers.Authorization, "token");
  assert.equal(headers.sign, expected);
  assert.equal(headers.t, "1700000000000");
  assert.equal(headers.nonce, "fixed-nonce");
});

test("SwitchBot press sends the press command", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ statusCode: 100 }), {
      headers: { "content-type": "application/json" },
    });
  };

  await pressSwitchBot(
    { SWITCHBOT_TOKEN: "token", SWITCHBOT_SECRET: "secret" },
    "AA/BB",
  );

  assert.equal(
    captured.url,
    "https://api.switch-bot.com/v1.1/devices/AA%2FBB/commands",
  );
  assert.deepEqual(JSON.parse(captured.options.body), {
    command: "press",
    parameter: "default",
    commandType: "command",
  });
});

test("intercom postback presses only the intercom device", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    const body = url.includes("switch-bot.com")
      ? { statusCode: 100 }
      : { sentMessages: [{ id: "1" }] };
    return new Response(JSON.stringify(body));
  };

  await handlePostback(testEnv(), {
    type: "postback",
    webhookEventId: "event-intercom",
    replyToken: "reply-token",
    source: { userId: "U123" },
    postback: { data: "action=intercom" },
  });

  assert.equal(requests.length, 2);
  assert.match(requests[0].url, /intercom-device\/commands$/);
  assert.equal(JSON.parse(requests[0].options.body).command, "press");
  assert.equal(JSON.parse(requests[1].options.body).messages[0].type, "text");
});

test("unlock postback presses the unlock device in one tap", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  const env = testEnv();
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    const body = url.includes("switch-bot.com")
      ? { statusCode: 100 }
      : { sentMessages: [{ id: "1" }] };
    return new Response(JSON.stringify(body));
  };

  await handlePostback(env, {
    type: "postback",
    webhookEventId: "event-unlock",
    replyToken: "reply-token",
    source: { userId: "U123" },
    postback: { data: "action=unlock" },
  });
  assert.equal(requests.length, 2);
  assert.match(requests[0].url, /unlock-device\/commands$/);
  assert.equal(JSON.parse(requests[0].options.body).command, "press");
  assert.match(
    JSON.parse(requests[1].options.body).messages[0].text,
    /解錠ボタン/,
  );
});

test("health endpoint does not require secrets", async () => {
  const response = await worker.fetch(
    new Request("https://example.workers.dev/health"),
    {},
    {},
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
});

test("webhook rejects an invalid signature", async () => {
  const response = await worker.fetch(
    new Request("https://example.workers.dev/line/webhook", {
      method: "POST",
      headers: { "x-line-signature": "wrong" },
      body: '{"events":[]}',
    }),
    {
      LINE_CHANNEL_ACCESS_TOKEN: "access-token",
      LINE_CHANNEL_SECRET: "channel-secret",
      LINE_USER_ID: "U123",
      SWITCHBOT_TOKEN: "switchbot-token",
      SWITCHBOT_SECRET: "switchbot-secret",
      SWITCHBOT_INTERCOM_DEVICE_ID: "intercom",
      SWITCHBOT_UNLOCK_DEVICE_ID: "unlock",
      DB: {},
    },
    {},
  );
  assert.equal(response.status, 401);
});

test("valid empty LINE webhook is acknowledged", async () => {
  const body = '{"events":[]}';
  const signature = createHmac("sha256", "channel-secret")
    .update(body)
    .digest("base64");
  const pending = [];
  const db = {
    prepare() {
      return {
        bind() {
          return this;
        },
      };
    },
    async batch() {},
  };
  const response = await worker.fetch(
    new Request("https://example.workers.dev/line/webhook", {
      method: "POST",
      headers: { "x-line-signature": signature },
      body,
    }),
    {
      LINE_CHANNEL_ACCESS_TOKEN: "access-token",
      LINE_CHANNEL_SECRET: "channel-secret",
      LINE_USER_ID: "U123",
      SWITCHBOT_TOKEN: "switchbot-token",
      SWITCHBOT_SECRET: "switchbot-secret",
      SWITCHBOT_INTERCOM_DEVICE_ID: "intercom",
      SWITCHBOT_UNLOCK_DEVICE_ID: "unlock",
      DB: db,
    },
    { waitUntil: (promise) => pending.push(promise) },
  );

  assert.equal(response.status, 200);
  assert.equal(await response.text(), "OK");
  await Promise.all(pending);
});
