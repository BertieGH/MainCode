/**
 * Turning an API failure into a sentence.
 *
 * The bug this exists to stop: `detail` is a string on most endpoints and an
 * object on a few, and every screen read it directly. The setup gate answers
 * with `{error, message, blockers}`, so refusing to create a campaign showed a
 * red box containing **`[object Object]`** — no information at all, in front of
 * exactly the situation that most needed explaining.
 */

import { apiError, apiErrorCode } from './api-error';

/** An HttpErrorResponse, as far as this code cares. */
const fail = (detail: unknown) => ({ error: { detail } });

describe('apiError', () => {
  it('passes a plain string through', () => {
    expect(apiError(fail('that service does not exist'))).toBe(
      'that service does not exist',
    );
  });

  describe('the structured refusals that produced [object Object]', () => {
    it('reads the setup gate, message and blockers together', () => {
      // The message says a gate refused; the blockers say what to go and do.
      // Both, because only one of them is actionable.
      const text = apiError(
        fail({
          error: 'setup_incomplete',
          message: 'Connect outreach before running this.',
          blockers: ['No outreach delivery provider is configured.'],
        }),
      );
      expect(text).toContain('Connect outreach before running this.');
      expect(text).toContain('No outreach delivery provider is configured.');
      expect(text).not.toContain('[object Object]');
    });

    it('reads a preflight summary, which uses a different key', () => {
      expect(apiError(fail({ summary: 'Two touches have no copy.' }))).toBe(
        'Two touches have no copy.',
      );
    });

    it('shows blockers even when there is no message', () => {
      expect(apiError(fail({ blockers: ['No model provider.'] }))).toBe(
        'No model provider.',
      );
    });

    it('dumps an unrecognised object rather than hiding it', () => {
      // Something unfamiliar is precisely when the detail matters, and
      // `[object Object]` is the one rendering that helps nobody.
      const text = apiError(fail({ weird: 'shape', code: 7 }));
      expect(text).toContain('weird');
      expect(text).not.toContain('[object Object]');
    });
  });

  describe('validation errors', () => {
    it('names the field, not the place it travelled in', () => {
      // `loc` is ["query", "service_id"]; "query" is machinery.
      expect(
        apiError(fail([{ loc: ['query', 'service_id'], msg: 'Field required' }])),
      ).toBe('service_id: Field required');
    });

    it('strips the "Value error," that FastAPI adds', () => {
      expect(
        apiError(
          fail([{ loc: ['body', 'weights'], msg: 'Value error, must total 100' }]),
        ),
      ).toBe('weights: must total 100');
    });

    it('joins several so one round trip reports every bad field', () => {
      const text = apiError(
        fail([
          { loc: ['body', 'name'], msg: 'Field required' },
          { loc: ['body', 'code'], msg: 'too long' },
        ]),
      );
      expect(text).toBe('name: Field required; code: too long');
    });
  });

  describe('when the server said nothing', () => {
    it('uses the screen\'s own fallback', () => {
      expect(apiError({}, 'Could not save the ICP.')).toBe('Could not save the ICP.');
    });

    it('prefers a raw string body over the fallback', () => {
      expect(apiError({ error: 'upstream timed out' }, 'x')).toBe('upstream timed out');
    });

    it('survives null and undefined', () => {
      expect(apiError(null, 'fallback')).toBe('fallback');
      expect(apiError(undefined, 'fallback')).toBe('fallback');
    });

    it('ignores an empty detail rather than showing blank red text', () => {
      expect(apiError(fail('   '), 'fallback')).toBe('fallback');
    });
  });
});

describe('apiErrorCode', () => {
  it('returns the code a screen branches on', () => {
    expect(apiErrorCode(fail({ error: 'demo_data_present', message: 'x' }))).toBe(
      'demo_data_present',
    );
  });

  it('is null when there is no structured code', () => {
    // Which is the point of keeping it separate: "what do I show" and "which
    // refusal was it" are different questions, and only one has an answer here.
    expect(apiErrorCode(fail('a plain message'))).toBeNull();
    expect(apiErrorCode(fail([{ msg: 'bad' }]))).toBeNull();
    expect(apiErrorCode({})).toBeNull();
  });
});
