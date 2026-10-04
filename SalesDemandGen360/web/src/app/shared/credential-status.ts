/**
 * How a credential's stored status is worded on screen.
 *
 * `status` is a four-value vocabulary and it cannot say enough on its own. The
 * case that forced this: a key that works on an account with no credit is
 * stored as `expired`, and rendering that word tells the reader their key has
 * expired — sending them to re-issue a key that was never the problem. The new
 * one fails identically.
 *
 * So the label comes from the *reason code* where there is one, and falls back
 * to the status. The explanation is the persisted detail, shown on hover, with
 * a per-code fallback for rows tested before the reason was recorded.
 */

/** Short label for the badge. Kept to two or three words. */
export function statusLabel(status: string, code?: string | null): string {
  switch (code) {
    case 'no_credit':
      // The distinction that matters most: the key is fine.
      return 'valid · no credit';
    case 'rejected':
      return 'rejected';
    case 'undecryptable':
      return 'unreadable';
    case 'unreachable':
      return 'unreachable';
    case 'endpoint_moved':
    case 'bad_request':
      return 'check failed';
    case 'tls_untrusted':
      return 'certificate not trusted';
    case 'not_checkable':
      return 'not checkable';
    case 'demo':
      return 'not checked';
    case 'rate_limited':
      return 'valid · rate limited';
    default:
      return status;
  }
}

/** Whether the badge should read as good, bad, or neither. */
export function statusTone(status: string, code?: string | null): string {
  if (status === 'valid') return 'badge-good';
  // A key the provider accepted is not a bad key, whatever else is wrong with
  // the account — so `no_credit` is a warning, not a failure.
  if (code === 'no_credit' || code === 'rate_limited') return 'badge-warn';
  if (status === 'invalid') return 'badge-critical';
  return 'badge-neutral';
}

/** The tooltip. Persisted detail first; a fallback so hover is never empty. */
export function statusExplanation(
  status: string,
  code?: string | null,
  detail?: string | null,
): string {
  if (detail) return detail;
  switch (code) {
    case 'no_credit':
      return 'The provider accepted this key. The account has no credit, so calls fail.';
    case 'rejected':
      return 'The provider refused this key. Re-issue it and paste the new one.';
    case 'undecryptable':
      return 'The stored value will not decrypt — SECRET_KEY changed. Re-enter it.';
    case 'unreachable':
      return 'The provider could not be reached, so nothing was learned about this key.';
    case 'endpoint_moved':
      return 'The endpoint we check has moved. The key may be fine; the check needs updating.';
    case 'tls_untrusted':
      return (
        'The provider is reachable, but its certificate is not trusted by this machine — ' +
        'usually a corporate TLS-inspecting proxy. The key was not tested.'
      );
    case 'not_checkable':
      return 'This build has no live check for this provider, so the key is unverified.';
    case 'demo':
      return 'Demo mode — the key is stored but no provider was contacted.';
  }
  return status === 'untested'
    ? 'Never tested. A stored key that has not round-tripped proves nothing.'
    : `Status: ${status}.`;
}
