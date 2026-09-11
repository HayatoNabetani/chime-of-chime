const LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply";
const SWITCHBOT_API_BASE = "https://api.switch-bot.com/v1.1";
const WEBHOOK_PATH = "/line/webhook";
const MAX_BODY_BYTES = 1_000_000;
const UNLOCK_CONFIRMATION_TTL_MS = 60_000;
const EVENT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

const encoder = new TextEncoder();

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function importHmacKey(secret, usage) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    [usage],
  );
}

export async function verifyLineSignature(body, signature, channelSecret) {
  if (!signature || !channelSecret) return false;
  try {
    const key = await importHmacKey(channelSecret, "verify");
    return await crypto.subtle.verify(
      "HMAC",
      key,
      base64ToBytes(signature),
      body,
    );
  } catch {
    return false;
  }
}

export async function makeSwitchBotHeaders(
  token,
  secret,
  timestamp = String(Date.now()),
  nonce = crypto.randomUUID(),
) {
  const key = await importHmacKey(secret, "sign");
  const signature = new Uint8Array(
    await crypto.subtle.sign(
      "HMAC",
      key,
      encoder.encode(`${token}${timestamp}${nonce}`),
    ),
  );
  return {
    Authorization: token,
    "Content-Type": "application/json; charset=utf8",
    sign: bytesToBase64(signature),
    t: timestamp,
    nonce,
  };
}

export async function pressSwitchBot(env, deviceId) {
  const headers = await makeSwitchBotHeaders(
    env.SWITCHBOT_TOKEN,
    env.SWITCHBOT_SECRET,
  );
  const response = await fetch(
    `${SWITCHBOT_API_BASE}/devices/${encodeURIComponent(deviceId)}/commands`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        command: "press",
        parameter: "default",
        commandType: "command",
      }),
    },
  );

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`SwitchBot API HTTP ${response.status}`);
  }
  if (!response.ok || data?.statusCode !== 100) {
    throw new Error(
      `SwitchBot API ${data?.statusCode ?? response.status} ${data?.message ?? ""}`.trim(),
    );
  }
}

async function replyLine(env, replyToken, messages) {
  if (typeof replyToken !== "string" || replyToken.length === 0) return;
  const response = await fetch(LINE_REPLY_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ replyToken, messages }),
  });
  if (!response.ok) {
    throw new Error(`LINE reply API HTTP ${response.status}`);
  }
}

function replyText(env, replyToken, text) {
  return replyLine(env, replyToken, [{ type: "text", text }]);
}

function replyUnlockConfirmation(env, replyToken, token) {
  return replyLine(env, replyToken, [
    {
      type: "template",
      altText: "玄関を解錠しますか？",
      template: {
        type: "confirm",
        text: "玄関を解錠しますか？",
        actions: [
          {
            type: "postback",
            label: "解錠する",
            data: `action=unlock_confirmed&token=${token}`,
          },
          {
            type: "postback",
            label: "キャンセル",
            data: `action=unlock_cancel&token=${token}`,
          },
        ],
      },
    },
  ]);
}

async function claimEvent(db, eventId, now) {
  const result = await db
    .prepare(
      "INSERT OR IGNORE INTO processed_events (event_id, processed_at) VALUES (?, ?)",
    )
    .bind(eventId, now)
    .run();
  return result.meta?.changes === 1;
}

async function createUnlockConfirmation(db, now) {
  const token = crypto.randomUUID();
  await db
    .prepare(
      "INSERT INTO unlock_confirmations (token, expires_at, used_at) VALUES (?, ?, NULL)",
    )
    .bind(token, now + UNLOCK_CONFIRMATION_TTL_MS)
    .run();
  return token;
}

async function claimUnlockConfirmation(db, token, now) {
  if (!token) return false;
  const result = await db
    .prepare(
      "UPDATE unlock_confirmations SET used_at = ? WHERE token = ? AND used_at IS NULL AND expires_at > ?",
    )
    .bind(now, token, now)
    .run();
  return result.meta?.changes === 1;
}

export async function handlePostback(env, event) {
  if (event?.type !== "postback") return;
  if (event.source?.userId !== env.LINE_USER_ID) {
    console.warn("Rejected a LINE postback from an unauthorized user");
    return;
  }

  const data = event.postback?.data;
  const eventId = event.webhookEventId;
  if (typeof data !== "string" || typeof eventId !== "string") return;

  const params = new URLSearchParams(data);
  const action = params.get("action");
  if (
    !["intercom", "unlock", "unlock_confirmed", "unlock_cancel"].includes(
      action,
    )
  ) {
    return;
  }

  const now = Date.now();
  if (!(await claimEvent(env.DB, eventId, now))) return;
  const replyToken = event.replyToken;

  if (action === "unlock") {
    const token = await createUnlockConfirmation(env.DB, now);
    await replyUnlockConfirmation(env, replyToken, token);
    return;
  }

  const confirmationToken = params.get("token") ?? "";
  if (action === "unlock_cancel") {
    await env.DB.prepare(
      "DELETE FROM unlock_confirmations WHERE token = ? AND used_at IS NULL",
    )
      .bind(confirmationToken)
      .run();
    await replyText(env, replyToken, "玄関の解錠をキャンセルしました");
    return;
  }

  if (action === "unlock_confirmed") {
    if (!(await claimUnlockConfirmation(env.DB, confirmationToken, now))) {
      await replyText(
        env,
        replyToken,
        "⌛ 解錠確認の有効期限が切れました。最初から操作してください",
      );
      return;
    }
    await pressSwitchBot(env, env.SWITCHBOT_UNLOCK_DEVICE_ID);
    await replyText(env, replyToken, "🔓 玄関の解錠ボタンを押しました");
    return;
  }

  await pressSwitchBot(env, env.SWITCHBOT_INTERCOM_DEVICE_ID);
  await replyText(env, replyToken, "🎧 インターホン用ボタンを押しました");
}

async function processEvents(env, events) {
  for (const event of events) {
    try {
      await handlePostback(env, event);
    } catch (error) {
      console.error("Failed to process LINE event", error);
      try {
        await replyText(env, event?.replyToken, "❌ SwitchBotの操作に失敗しました");
      } catch (replyError) {
        console.error("Failed to send LINE error reply", replyError);
      }
    }
  }

  const now = Date.now();
  await env.DB.batch([
    env.DB
      .prepare("DELETE FROM processed_events WHERE processed_at < ?")
      .bind(now - EVENT_RETENTION_MS),
    env.DB
      .prepare("DELETE FROM unlock_confirmations WHERE expires_at < ?")
      .bind(now - EVENT_RETENTION_MS),
  ]);
}

function hasRuntimeConfiguration(env) {
  return [
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_CHANNEL_SECRET",
    "LINE_USER_ID",
    "SWITCHBOT_TOKEN",
    "SWITCHBOT_SECRET",
    "SWITCHBOT_INTERCOM_DEVICE_ID",
    "SWITCHBOT_UNLOCK_DEVICE_ID",
  ].every((key) => typeof env[key] === "string" && env[key].length > 0) && env.DB;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({ ok: true });
    }
    if (request.method !== "POST" || url.pathname !== WEBHOOK_PATH) {
      return new Response("Not Found", { status: 404 });
    }
    if (!hasRuntimeConfiguration(env)) {
      console.error("Worker secrets or D1 binding are missing");
      return new Response("Service Unavailable", { status: 503 });
    }

    const declaredLength = Number(request.headers.get("content-length") ?? "0");
    if (declaredLength > MAX_BODY_BYTES) {
      return new Response("Payload Too Large", { status: 413 });
    }
    const body = new Uint8Array(await request.arrayBuffer());
    if (body.byteLength === 0 || body.byteLength > MAX_BODY_BYTES) {
      return new Response("Bad Request", { status: 400 });
    }

    const valid = await verifyLineSignature(
      body,
      request.headers.get("x-line-signature") ?? "",
      env.LINE_CHANNEL_SECRET,
    );
    if (!valid) return new Response("Unauthorized", { status: 401 });

    let payload;
    try {
      payload = JSON.parse(new TextDecoder().decode(body));
    } catch {
      return new Response("Bad Request", { status: 400 });
    }
    if (!payload || !Array.isArray(payload.events)) {
      return new Response("Bad Request", { status: 400 });
    }

    ctx.waitUntil(processEvents(env, payload.events));
    return new Response("OK");
  },
};
