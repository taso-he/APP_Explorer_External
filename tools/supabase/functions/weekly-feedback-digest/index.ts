// Weekly email summarising new feedback from the TASO APP Explorer page.
//
// Runs as a Supabase Edge Function, called once a week by the schedule in
// 4_schedule_feedback_digest.sql. It reads the last 7 days of site_feedback and
// sends one email through Resend (resend.com).
//
// Secrets to set in Supabase (Edge Functions > Secrets), never in this file:
//   RESEND_API_KEY   from resend.com
//   DIGEST_TO        who receives the email; separate several addresses with commas
//   DIGEST_FROM      the sender, e.g. "APP Explorer <feedback@taso.org.uk>" (a domain verified in Resend).
//                    Without a verified domain, use "APP Explorer <onboarding@resend.dev>": Resend then
//                    only delivers to the email address the Resend account was set up with.
//   DIGEST_SECRET    any long random string; the schedule sends it so only the schedule can run this
//   DIGEST_DAYS      optional: how many days each email covers (default 7; use 31 for monthly)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided by Supabase automatically.

const TYPES: Record<string, string> = {
  "general": "General feedback on the page",
  "impact": "How they have used the APP Explorer",
  "targets": "Targets that are missing or incorrect",
  "interventions": "Interventions that are missing or incorrect",
  "provider-info": "Provider information that is missing or incorrect",
  // Earlier categories, kept so older feedback still appears
  "wrong-target": "A target is wrong",
  "missing-target": "A target is missing",
  "intervention": "An intervention is wrong or missing",
  "other": "Other",
};

type Feedback = {
  id: number; created_at: string; feedback_type: string; institution: string | null;
  detail: string; email: string | null; page_task: string | null; status: string;
};

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

Deno.serve(async (req) => {
  if (req.headers.get("x-digest-secret") !== Deno.env.get("DIGEST_SECRET")) {
    return new Response("Not allowed", { status: 401 });
  }

  // DIGEST_DAYS: how far back each email looks. 7 for a weekly email, 31 for a monthly one.
  const days = Number(Deno.env.get("DIGEST_DAYS") || "7");
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  const url = `${Deno.env.get("SUPABASE_URL")}/rest/v1/site_feedback` +
    `?select=*&created_at=gte.${since.toISOString()}&order=created_at.asc`;
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const res = await fetch(url, { headers: { apikey: key, Authorization: `Bearer ${key}` } });
  if (!res.ok) return new Response(`Could not read feedback: ${res.status}`, { status: 500 });
  const rows: Feedback[] = await res.json();

  const week = `${since.toLocaleDateString("en-GB", { day: "numeric", month: "long" })} to ` +
    new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  const subject = rows.length
    ? `APP Explorer: ${rows.length} new feedback ${rows.length === 1 ? "message" : "messages"} (${week})`
    : `APP Explorer: no new feedback (${week})`;

  // Group by type, so corrections and impact stories are easy to pick out
  const byType: Record<string, Feedback[]> = {};
  rows.forEach((r) => (byType[r.feedback_type] ||= []).push(r));
  const sections = Object.keys(TYPES).filter((t) => byType[t]).map((t) => `
    <h3 style="margin:24px 0 8px">${esc(TYPES[t])} (${byType[t].length})</h3>
    ${byType[t].map((r) => `
      <div style="border-left:4px solid #214eab;padding:8px 12px;margin:0 0 12px;background:#f7f6f1">
        <p style="margin:0 0 6px;color:#485866;font-size:13px">
          ${new Date(r.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/London" })}
          ${r.institution ? ` &middot; ${esc(r.institution)}` : ""}
          ${r.email ? ` &middot; <a href="mailto:${esc(r.email)}">${esc(r.email)}</a>` : " &middot; no email given"}
        </p>
        <p style="margin:0;white-space:pre-line">${esc(r.detail)}</p>
      </div>`).join("")}`).join("");

  const html = `<div style="font-family:Arial,sans-serif;color:#0f2847;max-width:680px">
    <h2 style="margin:0 0 8px">APP Explorer feedback: ${esc(week)}</h2>
    <p>${rows.length ? `${rows.length} new ${rows.length === 1 ? "message" : "messages"} in this period.` : "No new feedback in this period."}
       All feedback, and its status, is in the <strong>site_feedback</strong> table in Supabase.</p>
    ${sections}
  </div>`;

  const send = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${Deno.env.get("RESEND_API_KEY")}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: Deno.env.get("DIGEST_FROM"),
      to: (Deno.env.get("DIGEST_TO") || "").split(",").map((s) => s.trim()).filter(Boolean),
      subject,
      html,
    }),
  });
  if (!send.ok) return new Response(`Email not sent: ${await send.text()}`, { status: 502 });
  return new Response(JSON.stringify({ sent: true, messages: rows.length }), { headers: { "Content-Type": "application/json" } });
});
