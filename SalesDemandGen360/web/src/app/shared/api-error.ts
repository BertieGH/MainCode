/**
 * Turning an API failure into a sentence.
 *
 * Every screen did `err?.error?.detail ?? 'Something went wrong.'`, which is
 * right for the many endpoints whose `detail` is a string and wrong for the
 * ones that answer with an object. Those rendered as **`[object Object]`** — a
 * red box carrying no information at all, in front of the exact situations
 * that most need explaining: a setup gate refusing an action, a validation
 * error naming a field.
 *
 * There are three shapes to handle, and they all arrive through the same
 * field:
 *
 * * a **string** — most refusals,
 * * an **object** — the setup gate's `{error, message, blockers}`,
 * * an **array** — FastAPI's validation errors, one entry per bad field.
 */

import { HttpErrorResponse } from '@angular/common/http';

const FALLBACK = 'Something went wrong.';

/** One FastAPI validation entry: `{loc: [...], msg, type}`. */
interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
}

function fromValidation(items: ValidationItem[]): string {
  const parts = items
    .map((item) => {
      // `loc` is like ["query", "service_id"] — the last segment is the field
      // a person recognises; the first is where it travelled in, which they
      // neither know nor can act on.
      const field = item.loc?.length ? String(item.loc[item.loc.length - 1]) : null;
      // FastAPI prefixes a Pydantic validator's message with "Value error, ",
      // which is true of the machinery and meaningless to a person.
      const message = (item.msg ?? 'is invalid').replace(/^Value error,\s*/, '');
      return field ? `${field}: ${message}` : message;
    })
    .filter(Boolean);
  return parts.length ? parts.join('; ') : FALLBACK;
}

function fromObject(detail: Record<string, unknown>): string {
  // `message` on the setup gate, `summary` on the execution preflight. Both
  // are the same idea under different names.
  const message =
    typeof detail['message'] === 'string'
      ? detail['message']
      : typeof detail['summary'] === 'string'
        ? (detail['summary'] as string)
        : null;
  const blockers = Array.isArray(detail['blockers'])
    ? (detail['blockers'] as unknown[]).filter((b) => typeof b === 'string')
    : [];

  // The blockers are the actionable half — "No outreach delivery provider is
  // configured" says what to go and do, where the message only says a gate
  // refused. Both, when both exist.
  if (message && blockers.length) return `${message} ${blockers.join(' ')}`;
  if (message) return message;
  if (blockers.length) return blockers.join(' ');

  // An object with neither: better a raw dump than `[object Object]`, since
  // something unrecognised is exactly when the detail matters.
  try {
    return JSON.stringify(detail);
  } catch {
    return FALLBACK;
  }
}

/**
 * A readable message for anything an endpoint can fail with.
 *
 * `fallback` is what a screen wants to say when the server offered nothing —
 * "Could not save the ICP." reads better than a generic apology.
 */
export function apiError(err: unknown, fallback: string = FALLBACK): string {
  const detail = (err as HttpErrorResponse)?.error?.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) return fromValidation(detail as ValidationItem[]);
  if (detail && typeof detail === 'object') {
    return fromObject(detail as Record<string, unknown>);
  }

  // No `detail` at all: a network failure, or a proxy that never reached the
  // API. `err.message` beats the fallback when it exists, because "Http
  // failure response for /api/lists: 0 Unknown Error" at least says the
  // request never landed.
  const raw = (err as HttpErrorResponse)?.error;
  if (typeof raw === 'string' && raw.trim()) return raw;
  const message = (err as { message?: string })?.message;
  return message && !fallback ? message : fallback;
}


/**
 * The machine-readable code on a structured failure, when there is one.
 *
 * A few screens branch on *which* refusal happened — `demo_data_present` opens
 * an acknowledgement rather than showing red text — and that is a different
 * question from what to display. Kept separate so a screen never has to pick
 * apart the response itself.
 */
export function apiErrorCode(err: unknown): string | null {
  const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const code = (detail as Record<string, unknown>)['error'];
    return typeof code === 'string' ? code : null;
  }
  return null;
}
