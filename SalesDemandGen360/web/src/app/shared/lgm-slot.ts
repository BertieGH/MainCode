import { TouchView } from '../core/pipeline.service';

/**
 * How a draft is labelled with the LGM attribute it will occupy.
 *
 * The binding is the whole integration — Gen360 writes each touch into a
 * `customAttributeN` and LGM's step template decides which one it reads — and
 * it was invisible on every screen. A rep could not tell where a body landed,
 * and could not tell that a subject line they had written would never appear.
 *
 * Shared rather than written twice: the drawer and the campaign arc show the
 * same fact, and two copies drift.
 */

/** `custom_attribute_3` as LGM spells it: `customAttribute3`. */
export function slotWire(slot: string | null): string {
  if (!slot) return '';
  const n = /^custom_attribute_(\d{1,2})$/.exec(slot);
  return n ? `customAttribute${n[1]}` : slot;
}

/** The chip's second line: what we call that slot, when we have a name. */
export function slotLabel(label: string | null): string {
  return label ?? '';
}

/**
 * The channel that actually sends.
 *
 * LGM decides it; the model only proposed one while drafting, and they can
 * disagree — a touch drafted as a LinkedIn message that LGM sends as an email.
 * Showing the drafted one beside a slot named for the real one reads as a bug,
 * because one of the two is simply wrong.
 */
export function sendingChannel(t: TouchView): string {
  return (t.lgm_channel ?? t.channel ?? '').replace('_', ' ');
}

/** Whether what we drafted disagrees with what LGM will do. */
export function channelDisagrees(t: TouchView): boolean {
  if (!t.lgm_channel) return false;
  const drafted = t.channel ?? '';
  const ours = drafted.startsWith('linkedin') || drafted === 'inmail' ? 'linkedin' : 'email';
  return ours !== t.lgm_channel;
}

/** Why a step has no subject of ours, said in the step's own terms. */
export function noSubjectReason(t: TouchView): string {
  return (t.lgm_channel ?? t.channel) === 'email' || t.channel === 'inmail'
    ? "LGM's own subject line"
    : 'LinkedIn steps have none';
}
