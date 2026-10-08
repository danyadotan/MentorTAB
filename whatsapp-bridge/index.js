/**
 * WhatsApp bridge — connects a dedicated WhatsApp number to a group, ingests
 * every message into the API, and replies when addressed by name.
 *
 * TOS WARNING: whatsapp-web.js automates WhatsApp Web, against WhatsApp's ToS.
 * Use a DEDICATED number, moderate volume. Telegram Bot API is a compliant alt.
 *
 * Env: TALBOT_API_URL (default http://localhost:8000), GROUP_NAME (required),
 *      BOT_TRIGGER (default "טלבוט")
 */
import pkg from "whatsapp-web.js";
import qrcode from "qrcode-terminal";
const { Client, LocalAuth } = pkg;

const API_URL = process.env.TALBOT_API_URL ?? "http://localhost:8000";
const GROUP_NAME = process.env.GROUP_NAME;
const BOT_TRIGGER = process.env.BOT_TRIGGER ?? "טלבוט";
if (!GROUP_NAME) { console.error("GROUP_NAME env var is required."); process.exit(1); }

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: { args: ["--no-sandbox", "--disable-setuid-sandbox"] },
});
client.on("qr", (qr) => { console.log("Scan this QR from the dedicated phone:"); qrcode.generate(qr, { small: true }); });
client.on("ready", () => console.log(`Bridge ready. Group: "${GROUP_NAME}", trigger: "${BOT_TRIGGER}"`));

async function api(path, bodyObj) {
  const res = await fetch(`${API_URL}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(bodyObj) });
  if (!res.ok) throw new Error(`API ${path} -> ${res.status} ${await res.text().catch(() => "")}`);
  return res.json();
}

client.on("message", async (msg) => {
  try {
    const chat = await msg.getChat();
    if (!chat.isGroup || chat.name !== GROUP_NAME) return;
    const contact = await msg.getContact();
    const senderName = contact.pushname || contact.name || contact.number;
    const senderPhone = contact.number ? `+${contact.number}` : null;
    const text = (msg.body || "").trim();
    if (!text) return;
    await api("/ingest", { sender_name: senderName, content: text, sender_phone: senderPhone });
    if (!text.includes(BOT_TRIGGER)) return;
    chat.sendStateTyping();
    const question = text.replaceAll(BOT_TRIGGER, "").trim() || text;
    const { reply } = await api("/chat", { message: `${senderName}: ${question}`, session_id: `wa-${chat.id._serialized}` });
    await msg.reply(reply);
  } catch (err) { console.error("Bridge error:", err.message); }
});
client.initialize();
