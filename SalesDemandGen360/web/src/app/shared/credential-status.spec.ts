import {
  statusExplanation,
  statusLabel,
  statusTone,
} from './credential-status';

/**
 * How a credential's state is worded.
 *
 * The case that forced this file: a key that works on an account with no
 * credit is stored as `expired`. Rendering that word tells the reader their
 * key expired, so they re-issue it — and the new one fails identically,
 * because the key was never the problem.
 */
describe('credential status wording', () => {
  describe('no credit', () => {
    it('does not call a working key expired', () => {
      expect(statusLabel('expired', 'no_credit')).toBe('valid · no credit');
      expect(statusLabel('expired', 'no_credit')).not.toContain('expired');
    });

    it('reads as a warning, not a failure', () => {
      // The provider accepted the key. Whatever else is wrong is not the key.
      expect(statusTone('expired', 'no_credit')).toBe('badge-warn');
    });

    it('explains that re-issuing will not help', () => {
      const detail = statusExplanation('expired', 'no_credit');
      expect(detail).toContain('accepted this key');
      expect(detail).toContain('no credit');
    });
  });

  describe('a genuinely rejected key', () => {
    it('says so and reads as a failure', () => {
      expect(statusLabel('invalid', 'rejected')).toBe('rejected');
      expect(statusTone('invalid', 'rejected')).toBe('badge-critical');
      expect(statusExplanation('invalid', 'rejected')).toContain('Re-issue');
    });
  });

  describe('failures that are ours, not the key\'s', () => {
    it('does not blame the credential for a moved endpoint', () => {
      expect(statusLabel('untested', 'endpoint_moved')).toBe('check failed');
      expect(statusTone('untested', 'endpoint_moved')).toBe('badge-neutral');
      expect(statusExplanation('untested', 'endpoint_moved')).toContain('may be fine');
    });

    it('says nothing was learned when the provider was unreachable', () => {
      expect(statusExplanation('untested', 'unreachable')).toContain('nothing was learned');
    });
  });

  describe('the tooltip', () => {
    it('prefers the stored detail over the generic fallback', () => {
      const stored = 'the workspace has no credit balance';
      expect(statusExplanation('expired', 'no_credit', stored)).toBe(stored);
    });

    it('is never empty, even for a row tested before reasons were recorded', () => {
      for (const status of ['valid', 'invalid', 'untested', 'expired']) {
        expect(statusExplanation(status, null, null).length).toBeGreaterThan(0);
      }
    });
  });

  describe('falling back', () => {
    it('shows the raw status when there is no reason code', () => {
      expect(statusLabel('valid', null)).toBe('valid');
      expect(statusTone('valid', null)).toBe('badge-good');
    });

    it('does not treat an unknown code as good news', () => {
      expect(statusTone('untested', 'something_new')).toBe('badge-neutral');
    });
  });
});
