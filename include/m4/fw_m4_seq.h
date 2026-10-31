/* Perkons M4: panel, sequencer, patterns and the modulation LFO, for patch code.
 * See docs/architecture.md ("Transport, keys and sequencer", "Panel and UI"). Offsets are
 * v1.3.0 layouts; addresses come from fw_syms.h. Included by fw_m4.h. */
#pragma once
#include <stdint.h>

/* ---- panel: key ids (events {id, type, value}, key_held) -------------------------- */
#define FW_KEY_STEP(row, col)   ((row) * 16 + (col))    /* rows 0-3, cols 0-15 */
#define FW_KEY_PATTERN      0x40    /* RATCHET */
#define FW_KEY_KIT          0x41    /* ODDS1 */
#define FW_KEY_SYNC         0x42    /* ODDS2 */
#define FW_KEY_MOD          0x43    /* PROB */
#define FW_KEY_RESET        0x44
#define FW_KEY_PLAY         0x45
#define FW_KEY_REC          0x46
#define FW_KEY_SHIFT        0x47
#define FW_KEY_SHUFFLE      0x48
#define FW_KEY_LAST         0x49
#define FW_KEY_CLEAR        0x4a
#define FW_KEY_TRIG(v)      (0x4b + (v))    /* trigger keys, voices 0-3 */
#define FW_EV_DOWN          0x11
#define FW_EV_UP            0x10

/* LEDs (set_led): steps 0-0x3f as their keys, then these */
#define FW_LED_SHIFT        0x43
#define FW_LED_REC          0x45
#define FW_LED_MOD          0x46
#define FW_LED_SYNC         0x47
#define FW_LED_KIT          0x48
#define FW_LED_PATTERN      0x49
#define FW_LED_LFO          0x4b
#define FW_LED_TRIG(v)      (0x4f - (v))    /* reversed: voice 1 = 0x4f */

/* UI modes (set_mode / get_mode) */
#define FW_MODE_MAIN        0
#define FW_MODE_SHIFT       1
#define FW_MODE_LAST        2
#define FW_MODE_MOD         3
#define FW_MODE_PATTERN     4
#define FW_MODE_KIT         5
#define FW_MODE_CONFIG      7
#define FW_MODE_ROLL        9
#define FW_MODE_BANK        0xf

/* pots: 0x00-0x1f = track * 8 + slot (0-7), then the globals */
#define FW_POT(track, slot) ((track) * 8 + (slot))
#define FW_POT_TEMPO        0x20
#define FW_POT_LFO_RATE     0x21
#define FW_POT_LFO_WAVE     0x22
#define FW_POT_MOD_LVL      0x23

/* the 11 control slots of a track (CC chart order: CC 70 + slot) */
#define FW_SLOT_TUNE        0
#define FW_SLOT_PARAM1      1
#define FW_SLOT_CUTOFF      2
#define FW_SLOT_FX_SEND     3
#define FW_SLOT_DECAY       4
#define FW_SLOT_PARAM2      5
#define FW_SLOT_DRIVE       6
#define FW_SLOT_LEVEL       7
#define FW_SLOT_ALGO        8
#define FW_SLOT_MODE        9
#define FW_SLOT_FILTER      10
#define FW_NSLOTS           11

/* ---- sequencer object (*SYM_seq_ptr) ----------------------------------------------- */
#define FW_SEQ_PLAY         0x00    /* 0 stopped, 1 playing, 2 paused */
#define FW_SEQ_COUNT        0x03    /* track count */
#define FW_SEQ_STATES       0x04    /* -> track states */
#define FW_SEQ_CURRENT      0x08    /* -> pattern header playing */
#define FW_SEQ_QUEUED       0x0c

/* track state (voice_state(t)), CONST_track_state bytes */
#define FW_VS_INDEX         0x00
#define FW_VS_BLOCK         0x04    /* -> the track's pattern block */
#define FW_VS_PENDING       0x08    /* block to move to at the track's loop end */
#define FW_VS_STEP          0x1c
#define FW_VS_NEXT          0x20
#define FW_VS_SUBTICK       0x26
#define FW_VS_FIRED         0x31
#define FW_VS_CLOCK         0x44    /* -> clock_state */
#define FW_VS_LOCKS         0x4c    /* -> the block's lock records */
#define FW_VS_VALUE         0x50    /* u16 x 11: the values playing now */
#define FW_VS_BASE          0x6a    /* u16 x 11 + masks (26 B): knob/kit value of each slot */
#define FW_VS_STORED        0x84    /* their copy from SHIFT down (store_values) */
#define FW_VS_CATCH         0xf8    /* u8 x 11: pot catch armed */
#define FW_VS_MUTE          0x108

/* pattern header (SYM_pat_headers, 64 x 0x20) */
#define FW_HDR_SIZE         0x20
#define FW_HDR_REPEATS      0x14    /* master length */
#define FW_HDR_BLOCK        0x18    /* -> 4 track blocks */

/* track block (CONST_track_block bytes): 16 steps, settings, 16 lock records */
#define FW_STEPS            16
#define FW_STEP_SIZE        8       /* +0 on, +4 ratchet, +5 condition, +6 note, +7 velocity */
#define FW_BLK_FIRST        0x80
#define FW_BLK_LAST         0x81
#define FW_BLK_PLAY_MODE    0x82
#define FW_BLK_RATE         0x86
#define FW_BLK_SHUFFLE      0x87
#define FW_BLK_GROOVE       0x88
#define FW_BLK_LOCKS        0x8c
#define FW_LOCK_SIZE        0x1a    /* u16 x 11, u16 locked mask, u16 glide mask */

/* ---- modulation LFO object (SYM_mod_lfo) -------------------------------------------- */
#define FW_LFO_SIZE         0x30
#define FW_LFO_PHASE        0x00
#define FW_LFO_INC          0x04
#define FW_LFO_WAVETABLE    0x14    /* -> {tables, length, count u16, sample-and-hold s16} */
#define FW_LFO_WAVETABLE_SIZE 12
#define FW_LFO_WAVE         0x18
#define FW_LFO_LEVEL        0x1c
#define FW_LFO_OUT          0x20
#define FW_LFO_SYNC         0x24
#define FW_LFO_STORED       0x28    /* -> the kit's {rate, wave, level, sync}; pot catch */
#define FW_LFO_CATCH        0x2c    /* bit 0 rate, 1 wave, 2 level: hold the stored value */

/* ---- device_config bytes (SYM_device_config) ---------------------------------------- */
#define FW_DC_POT_CATCH     0x04
#define FW_DC_SEQ_OUT       0x19
#define FW_DC_MULTI         0x1d    /* MIDI: 0 single channel, 1 multi */
#define FW_DC_CH_SINGLE     0x22

/* ---- calls ------------------------------------------------------------------------- */
#define fw_key_held         FW_CALL(SYM_key_held, int (*)(int key))
#define fw_steps_held       FW_CALL(SYM_steps_held, int (*)(void))
#define fw_set_mode         FW_CALL(SYM_set_mode, void (*)(int mode))
#define fw_get_mode         FW_CALL(SYM_get_mode, int (*)(void))
#define fw_pot_moved        FW_CALL(SYM_pot_moved, int (*)(int pot))
#define fw_voice_state      FW_CALL(SYM_voice_state, uint8_t *(*)(int track))
#define fw_midi_out         FW_CALL(SYM_midi_out_bytes, void (*)(int port, uint32_t packed))
#define fw_f_read           FW_CALL(SYM_f_read, int (*)(void *fil, void *buf, unsigned n, unsigned *got))
#define fw_f_unlink         FW_CALL(SYM_f_unlink, int (*)(const char *path))
#define fw_record           FW_CALL(SYM_seq_record, void (*)(uint8_t *locks, uint32_t slot, uint32_t value, int track, uint32_t step))
#define fw_clear_slot       FW_CALL(SYM_seq_clear_slot, void (*)(uint8_t *locks, uint32_t slot))
#define fw_track_clear      FW_CALL(SYM_track_clear, void (*)(uint8_t *vs))
#define fw_track_auto_clear FW_CALL(SYM_track_auto_clear, void (*)(uint8_t *locks))
#define fw_pattern_init     FW_CALL(SYM_pattern_init, void (*)(uint8_t *hdr))
#define fw_store_values     FW_CALL(SYM_store_values, void (*)(uint8_t *locks))
#define fw_voice_play       FW_CALL(SYM_voice_play, void (*)(int voice, int on, int note, int vel))
#define fw_trig_active      FW_CALL(SYM_trig_active, int (*)(int track))

#define FW_FA_READ          0x01u
