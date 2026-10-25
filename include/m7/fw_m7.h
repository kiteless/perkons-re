/* Perkons M7 firmware interface for patch code (v1.3.0).
 * Addresses come from the generated fw_syms.h (symbols/v1.3.0-m7.json). */
#pragma once
#include <stdint.h>
#include "fw_syms.h"

/* --- firmware objects ------------------------------------------------------------ */

typedef struct cVoice cVoice;
typedef struct {
    void (*trigger)(cVoice *);
    void (*init)(cVoice *);
    void (*update)(cVoice *);
    int16_t (*render)(cVoice *);
} cVoice_vtbl;

struct cVoice {                 /* only the fields we touch; see docs/architecture.md */
    const cVoice_vtbl *vtbl;
    uint8_t algo, mode, velocity, accent;
};

#define FW_SLOTS            ((cVoice **)SYM_slots)              /* cVoice *slots[4] */
#define FW_PARAMS           ((int32_t (*)[4])SYM_params)        /* int params[4][4] */
#define FW_SAMPLER_OFF      0x2a90u                             /* cSamplePlayer inside cFourthSlot */
#define FW_P2CFG_OFF        0x2c6du                             /* sampler P2-config byte in cFourthSlot */
#define FW_SAMPLE_VOICE     3                                   /* original voice index with the sampler */
#define FW_MUTE_OFF         0xb8u                               /* cVoice: mute flag */
#define FW_GAIN_OFF         0xbcu                               /* cVoice: mute fade gain */

#define FW_CALL(sym, type)  ((type)((uintptr_t)(sym) | 1u))
#define fw_wire_voices      FW_CALL(SYM_wire_voices, void (*)(void))
#define fw_ipc_recv         FW_CALL(SYM_ipc_recv, int (*)(int, uint32_t *, uint8_t *))
#define fw_sample_load_a    FW_CALL(SYM_cSamplePlayer_load_a, void (*)(void *, int))
#define fw_sample_load_b    FW_CALL(SYM_cSamplePlayer_load_b, void (*)(void *))
#define fw_sampler_render   FW_CALL(SYM_cSamplePlayer_render, int16_t (*)(void *))
#define fw_crush_render     FW_CALL(SYM_cNoiseCrush_render, int16_t (*)(void *))

/* Function-static state inside engine render functions. Stock firmware has one instance
 * of each engine, so these act as per-instance state. Code that runs more than one
 * instance of these engines must give each instance its own copy. */
#define FW_SAMPLER_STATIC   ((volatile uint32_t *)SYM_sampler_static)
#define FW_CRUSH_STATIC     ((volatile uint32_t *)SYM_crush_static)
#define FW_CRUSH_OFF        0x320u                              /* cNoiseCrush inside cFourthSlot */
