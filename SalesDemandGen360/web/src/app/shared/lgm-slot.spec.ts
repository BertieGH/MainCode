import { TouchView } from '../core/pipeline.service';
import {
  channelDisagrees,
  noSubjectReason,
  sendingChannel,
  slotWire,
} from './lgm-slot';

describe('LGM slot labelling', () => {
  it('spells a slot the way LGM does', () => {
    // Ours is snake_case everywhere inside Gen360; LGM only knows this form,
    // and showing our spelling would not match what a rep sees in LGM.
    expect(slotWire('custom_attribute_3')).toBe('customAttribute3');
    expect(slotWire('custom_attribute_20')).toBe('customAttribute20');
    expect(slotWire(null)).toBe('');
  });

  it('passes through anything it does not recognise', () => {
    expect(slotWire('somethingElse')).toBe('somethingElse');
  });

  it('shows the channel LGM will send on, not the one drafted', () => {
    // Found on a real arc: step 1 was drafted `linkedin_connect` and LGM sends
    // it as an email. The slot beside it was labelled "email 1 body", so the
    // row contradicted itself.
    const t = { channel: 'linkedin_connect', lgm_channel: 'email' } as TouchView;
    expect(sendingChannel(t)).toBe('email');
    expect(channelDisagrees(t)).toBeTrue();
  });

  it('falls back to the drafted channel when LGM has not been read', () => {
    const t = { channel: 'linkedin_message', lgm_channel: null } as TouchView;
    expect(sendingChannel(t)).toBe('linkedin message');
    expect(channelDisagrees(t)).toBeFalse();
  });

  it('does not cry disagreement over two spellings of the same channel', () => {
    const t = { channel: 'linkedin_connect', lgm_channel: 'linkedin' } as TouchView;
    expect(channelDisagrees(t)).toBeFalse();
  });

  it('says why a step carries no subject of ours', () => {
    const touch = (channel: string) => ({ channel }) as TouchView;
    expect(noSubjectReason(touch('linkedin_message'))).toContain('LinkedIn');
    expect(noSubjectReason(touch('email'))).toContain("LGM's own");
  });
});
