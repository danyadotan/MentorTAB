/**
 * MentorTAB · Desk — WhatsApp bridge
 * ----------------------------------
 * Runs on a computer (e.g. your laptop), linked to a DEDICATED WhatsApp number
 * as a "linked device". Every message in the configured group is stored in the
 * class's memory; when someone writes the trigger word (default "טלבוט"), the
 * bot answers in the group.
 *
 * Settings: edit config.json (or override with env vars API_URL, PROFILE,
 * GROUP_NAME, BOT_TRIGGER).
 *
 * TOS NOTE: whatsapp-web.js automates WhatsApp Web, which WhatsApp's terms do
 * not allow. Use a dedicated number (never your personal one) and keep volume
 * moderate. A fully compliant alternative is Telegram's official Bot API.
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import pkg from "whatsapp-web.js";
import qrcodeTerminal from "qrcode-terminal";
import QRCode from "qrcode";

const { Client, LocalAuth } = pkg;
const HERE = path.dirname(fileURLToPath(import.meta.url));

async function loadConfig() {
  let file = {};
  try {
    file = JSON.parse(await readFile(path.join(HERE, "config.json"), "utf8"));
  } catch {
    // no config.json — env vars only
  }
  return {
    apiUrl: (process.env.API_URL || file.apiUrl || "https://mentortab.onrender.com").replace(/\/+$/, ""),
    profile: process.env.PROFILE || file.profile || "hiphop",
    groupName: (process.env.GROUP_NAME || file.groupName || "").trim(),
    triggers: (process.env.BOT_TRIGGER || file.trigger || "טלבוט")
      .split(",").map((t) => t.trim()).filter(Boolean),
  };
}

const cfg = await loadConfig();
if (!cfg.groupName) {
  console.log("⚠️  groupName is empty in config.json — the bot will start and list your groups,");
  console.log("   but will not answer anywhere until you set groupName and restart.\n");
}

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: path.join(HERE, ".wwebjs_auth") }),
  puppeteer: { args: ["--no-sandbox", "--disable-setuid-sandbox"] },
});

client.on("qr", async (qr) => {
  const png = path.join(HERE, "qr.png");
  await QRCode.toFile(png, qr, { width: 420 });
  console.log("\n📱 Link the bot's phone: WhatsApp → Settings → Linked devices → Link a device");
  console.log(`   Scan the QR below, or open this image: ${png}\n`);
  qrcodeTerminal.generate(qr, { small: true });
});

client.on("ready", async () => {
  console.log(`\n✅ Bot connected. Class: "${cfg.profile}" · trigger: ${cfg.triggers.join(" / ")}`);
  const chats = await client.getChats();
  const groups = chats.filter((c) => c.isGroup).map((c) => c.name);
  console.log("   Groups this number is in:");
  groups.forEach((g) => console.log(`     • ${g}${matchesGroup(g) ? "   ← watching" : ""}`));
  if (cfg.groupName && !groups.some(matchesGroup)) {
    console.log(`\n⚠️  No group matches "${cfg.groupName}". Copy a name from the list into config.json.`);
  }
});

client.on("auth_failure", (m) => console.error("❌ Login failed:", m, "— delete the .wwebjs_auth folder and scan again."));
client.on("disconnected", (r) => console.error("🔌 Disconnected:", r, "— restart with: npm start"));

function matchesGroup(name) {
  return Boolean(cfg.groupName) && (name || "").toLowerCase().includes(cfg.groupName.toLowerCase());
}

async function api(route, body, timeoutMs = 120_000) {
  // Generous timeout: a sleeping free server can take ~50s to wake up.
  const res = await fetch(`${cfg.apiUrl}${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, profile: cfg.profile }),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`${route} → ${res.status} ${await res.text().catch(() => "")}`);
  return res.json();
}

const busy = new Set(); // one answer at a time per group

client.on("message", async (msg) => {
  try {
    const chat = await msg.getChat();
    if (!chat.isGroup || !matchesGroup(chat.name)) return;
    const text = (msg.body || "").trim();
    if (!text) return;

    const contact = await msg.getContact();
    const senderName = contact.pushname || contact.name || contact.number || "הורה";

    // Every group message becomes part of this class's memory.
    await api("/ingest", { sender_name: senderName, content: text });

    const trigger = cfg.triggers.find((t) => text.includes(t));
    if (!trigger) return;

    const chatId = chat.id._serialized;
    if (busy.has(chatId)) return;
    busy.add(chatId);

    const typing = setInterval(() => chat.sendStateTyping().catch(() => {}), 20_000);
    chat.sendStateTyping().catch(() => {});
    try {
      const question = text.split(trigger).join("").trim() || text;
      const { reply } = await api("/chat", {
        message: `${senderName}: ${question}`,
        session_id: `wa-${chatId}`,
      });
      await msg.reply(reply);
    } catch (err) {
      console.error("Answer failed:", err.message);
      await msg.reply("מצטער, יש לי תקלה רגעית 🙏 נסו לשאול שוב בעוד דקה.");
    } finally {
      clearInterval(typing);
      busy.delete(chatId);
    }
  } catch (err) {
    console.error("Bridge error:", err.message);
  }
});

console.log(`Starting MentorTAB bridge → ${cfg.apiUrl} (class: ${cfg.profile}) …`);
client.initialize();
