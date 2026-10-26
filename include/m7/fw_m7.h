/* Perkons M7 firmware interface for patch code.
 * Every address and offset comes from the generated fw_syms.h (symbols/<version>-m7.json),
 * so code using only these names builds unchanged for any firmware version that has
 * a symbols file. */
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

struct cVoice {                 /* C++ object: vptr first; other fields via OFF_cVoice_* */
    const cVoice_vtbl *vtbl;
};

#define FW_FIELD(obj, off, type) (*(type *)((uint8_t *)(obj) + (off)))

#define FW_SLOTS            ((cVoice **)SYM_slots)              /* cVoice *slots[4] */
#define FW_PARAMS           ((int32_t (*)[4])SYM_params)        /* int params[4][4] */
#define FW_ALGO_OFF         OFF_cVoice_algo                     /* u8 algo, mode, velocity, accent */
#define FW_MODE_OFF         OFF_cVoice_mode
#define FW_VELOCITY_OFF     OFF_cVoice_velocity
#define FW_ACCENT_OFF       OFF_cVoice_accent
#define FW_MUTE_OFF         OFF_cVoice_mute                     /* u8 mute flag */
#define FW_GAIN_OFF         OFF_cVoice_gain                     /* i32 mute fade gain */
#define FW_SAMPLER_OFF      OFF_cFourthSlot_sampler             /* cSamplePlayer inside cFourthSlot */
#define FW_P2CFG_OFF        OFF_cFourthSlot_p2cfg               /* sampler P2-config byte in cFourthSlot */
#define FW_CRUSH_OFF        OFF_cFourthSlot_crush               /* cNoiseCrush inside cFourthSlot */
#define FW_SAMPLE_VOICE     CONST_sampler_voice                 /* stock voice index with the sampler */

#define FW_CALL(sym, type)  ((type)((uintptr_t)(sym) | 1u))
#define fw_wire_voices      FW_CALL(SYM_wire_voices, void (*)(void))
#define fw_ipc_recv         FW_CALL(SYM_ipc_recv, int (*)(int, uint32_t *, uint8_t *))
#define fw_sample_load_a    FW_CALL(SYM_cSamplePlayer_load_a, void (*)(void *, int))
#define fw_sample_load_b    FW_CALL(SYM_cSamplePlayer_load_b, void (*)(void *))
#define fw_sampler_render   FW_CALL(SYM_cSamplePlayer_render, int16_t (*)(void *))
#define fw_crush_render     FW_CALL(SYM_cNoiseCrush_render, int16_t (*)(void *))
#define fw_tick_mute_fade   FW_CALL(SYM_cVoice_tick_mute_fade, void (*)(cVoice *))  /* per sample, as slot renders do */
#define FW_PARAM_PTRS_OFF   OFF_cVoice_param_ptrs                /* int *param[4] */

/* Function-static state inside engine render functions. Stock firmware has one instance
 * of each engine, so these act as per-instance state. Code that runs more than one
 * instance of these engines must give each instance its own copy. */
#define FW_SAMPLER_STATIC   ((volatile uint32_t *)SYM_sampler_static)
#define FW_CRUSH_STATIC     ((volatile uint32_t *)SYM_crush_static)
