// The console's agent: answers the treasury team's questions with Claude, grounded only on the numbers
// the page sends (the model's decision, today's payments, the last 14 days). It never decides amounts.
// Without ANTHROPIC_API_KEY it answers 503 and the page uses its own answers built from the same data.
import Anthropic from "@anthropic-ai/sdk";

const MODEL = process.env.ANTHROPIC_MODEL || "claude-haiku-5-5";

const SYSTEM = `Sos el agente de Prefoundly, que repone automáticamente el saldo de una billetera en su partner de pagos.
Cada día a las 09:00 un modelo (segmentación k-means de usuarios, LightGBM por segmento y Monte Carlo) pronostica los pagos hasta la próxima reposición y manda lo justo para cubrirlos con la cobertura elegida (99 % = alcanza en 99 de cada 100 escenarios). Nadie aprueba los envíos; hay límites fijos.
Respondé en español rioplatense (voseo), en 1 a 3 oraciones, concreto, como alguien de tesorería que habla en primera persona ("mandé", "proyecto").
Usá solo los números del contexto (están en pesos; escribilos como "$21,3 M"). No inventes datos.
"¿Qué cambió hoy?" se refiere a los pagos de hoy contra el pronóstico (deviation) y a la reposición estimada para mañana.
Si "applied" no es null, el usuario dio una orden: confirmá lo aplicado y su efecto con los números del contexto. Si es null, no lo menciones.`;

const client = new Anthropic();

// The endpoint spends the project's API key, so it only answers the console itself, with a bounded
// context, and a few questions per minute per IP (best effort: the counter lives in one warm instance).
const MAX_CONTEXT = 8000;
const ORIGINS = (process.env.ALLOWED_ORIGINS || "https://prefoundly.vercel.app").split(",").map((o) => o.trim());
const allowedOrigin = (o) => !!o && (ORIGINS.includes(o) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(o));
const WINDOW_MS = 60_000, PER_WINDOW = 12, hits = new Map();
function rateLimited(req) {
  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown", now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  recent.push(now); hits.set(ip, recent);
  if (hits.size > 5000) hits.clear();
  return recent.length > PER_WINDOW;
}

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  if (!process.env.ANTHROPIC_API_KEY) return res.status(503).json({ error: "no model configured" });
  if (!allowedOrigin(req.headers.origin)) return res.status(403).json({ error: "forbidden" });
  if (rateLimited(req)) return res.status(429).json({ error: "too many questions" });
  const { q, context, applied } = req.body || {};
  if (typeof q !== "string" || !q.trim() || q.length > 500) return res.status(400).json({ error: "bad question" });
  const ctx = JSON.stringify(context ?? {}), act = JSON.stringify(applied ?? null);
  if (ctx.length > MAX_CONTEXT || act.length > 200) return res.status(413).json({ error: "context too large" });
  try {
    const msg = await client.messages.create({
      model: MODEL,
      max_tokens: 600,
      thinking: { type: "disabled" }, // a short grounded answer; Haiku 5.5 accepts disabled at its default effort
      system: SYSTEM,
      messages: [{ role: "user", content: `Contexto (JSON):\n${ctx}\n\napplied: ${act}\n\nPregunta: ${q.trim()}` }],
    });
    if (msg.stop_reason === "refusal") return res.status(502).json({ error: "refused" });
    const text = msg.content.filter((b) => b.type === "text").map((b) => b.text).join("").trim();
    return text ? res.status(200).json({ text }) : res.status(502).json({ error: "empty answer" });
  } catch (error) {
    if (error instanceof Anthropic.RateLimitError) return res.status(429).json({ error: "rate limited" });
    if (error instanceof Anthropic.APIError) return res.status(502).json({ error: `model error ${error.status}` });
    return res.status(502).json({ error: "model unreachable" });
  }
}
