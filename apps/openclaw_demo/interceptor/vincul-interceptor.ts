/**
 * OpenClaw tool.before interceptor for Vincul enforcement.
 *
 * Intercepts tool calls before execution and validates them against
 * the Vincul enforcement service. Blocks unauthorized actions.
 *
 * Install: place in ~/.openclaw/hooks/ or reference in openclaw.json
 */

const VINCUL_URL = process.env.VINCUL_ENFORCE_URL || "http://localhost:8100/enforce";

interface ToolCall {
  agent: string;
  tool: string;
  action: string;
  params: Record<string, unknown>;
}

interface EnforceResponse {
  allowed: boolean;
  failure_code?: string;
  message?: string;
  receipt_hash?: string;
  pipeline_step?: string;
}

export async function beforeToolCall(call: ToolCall): Promise<{ allow: boolean; reason?: string }> {
  // Extract target from params (for message:send, target is the recipient)
  const target = (call.params?.target as string) ||
                 (call.params?.userId as string) ||
                 (call.params?.to as string) ||
                 null;

  try {
    const resp = await fetch(VINCUL_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent: call.agent,
        tool: call.tool,
        action: call.action || "default",
        target,
        params: call.params,
      }),
    });

    if (!resp.ok) {
      // Fail-closed: enforcement service down = deny
      return { allow: false, reason: `Vincul enforcement service error: ${resp.status}` };
    }

    const result: EnforceResponse = await resp.json();

    if (!result.allowed) {
      const reason = [
        `VINCUL DENIED: ${result.failure_code}`,
        result.pipeline_step ? `(${result.pipeline_step})` : "",
        result.message || "",
        result.receipt_hash ? `[receipt: ${result.receipt_hash.slice(0, 16)}...]` : "",
      ].filter(Boolean).join(" ");

      return { allow: false, reason };
    }

    return { allow: true };
  } catch (err) {
    // Fail-closed: network error = deny
    return { allow: false, reason: `Vincul enforcement unreachable: ${err}` };
  }
}
