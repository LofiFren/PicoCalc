// picosampler - DMA-paced PWM audio mixer for PicoCalc (RP2350 / Pico 2W).
//
// Strudel-on-PicoCalc audio engine (C1/C2). A native C sampler that streams
// 8-bit PCM one-shots from the SD card and mixes them to the audio PWM pins via
// DMA. Per voice it supports an ADSR amplitude envelope and a 2-stage resonant
// filter (highpass -> lowpass), like Strudel's lpf/hpf/adsr.
//
// Signal path (per sample, Q16 FIXED POINT):
//   sample(-1..1) * gain -> HPF (SVF) -> LPF (SVF) -> ADSR -> sum -> PWM
// The per-sample mix runs in the DMA IRQ, so it is INTEGER-ONLY: float in the
// audio ISR (concurrent with display rendering) was found to hard-fault the
// board. Filter/envelope coefficients are computed in float at note-on (on the
// main thread, in play()) and stored as Q16 integers; the ISR never touches the
// FPU. The PWM wrap is ~6800 (sys_clk/sample_rate) so output is ~12.7-bit.
//
// Other notes:
//   - PWM slice runs AT the sample rate; per-wrap DREQ paces ping-pong DMA, one
//     transfer per sample. Both audio pins (GPIO 28 + 27) get the same mono mix
//     via two DMA pairs (the PicoCalc speaker needs both driven).
//   - irq_add_shared_handler (NOT exclusive): MicroPython's rp2 port owns
//     DMA_IRQ_0 with a shared handler; exclusive would panic/hang.
//   - register() pins sample bytes as GC roots; the non-moving GC keeps the raw
//     pointer valid.

#include "py/runtime.h"
#include "py/obj.h"
#include "py/mphal.h"
#include <string.h>
#include <math.h>

#include "pico/stdlib.h"
#include "hardware/pwm.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

#define AUDIO_GPIO_L    28
#define AUDIO_GPIO_R    27
#define BLOCK           256
#define MAX_VOICES      8
#define MAX_SAMPLES     16
#define DEFAULT_SR      22050
#define Q               16            // fixed-point fractional bits
#define FX_ONE          (1 << Q)      // 1.0 in Q16

// Cytomic TPT state-variable filter, one stage, Q16 fixed point.
typedef struct {
    int32_t ic1, ic2;      // integrator state
    int32_t a1, a2, a3, k; // coefficients (Q16)
    int on;
} svf_t;

typedef struct {
    const uint8_t *data;
    uint32_t len;
    uint32_t pos;
    int32_t gain;          // Q16
    volatile bool active;
    // ADSR (all Q16)
    int env_stage;         // 0=attack 1=decay 2=sustain 3=release
    int32_t env, a_inc, d_inc, r_inc, sus;
    uint32_t gate, age;    // gate = samples until release (0 = none)
    // filters
    svf_t hp, lp;
} voice_t;

typedef struct {
    const uint8_t *data;
    uint32_t len;
} sample_t;

static uint32_t audio_buf[2][BLOCK];
static sample_t samples[MAX_SAMPLES];
static int n_samples = 0;
static voice_t voices[MAX_VOICES];

static uint slice_l, slice_r;
static uint32_t pwm_wrap;
static int dma_la = -1, dma_lb = -1, dma_ra = -1, dma_rb = -1;
static volatile bool running = false;
static volatile uint32_t irq_count = 0;
static float actual_sr = 0.0f;

MP_REGISTER_ROOT_POINTER(mp_obj_t picosampler_keepalive[MAX_SAMPLES]);

// ---- DSP: float coeffs at note-on (main thread), integer run (ISR) ---------

static void svf_set(svf_t *f, int cutoff, int res) {
    if (cutoff <= 0) {
        f->on = 0;
        return;
    }
    float fc = (float)cutoff;
    float nyq = actual_sr * 0.45f;
    if (fc > nyq) {
        fc = nyq;
    }
    float g = tanf(M_PI * fc / actual_sr);
    float q = (float)res / 100.0f;
    if (q < 0.5f) {
        q = 0.5f;
    }
    float k = 1.0f / q;
    float a1 = 1.0f / (1.0f + g * (g + k));
    f->a1 = (int32_t)(a1 * FX_ONE);
    f->a2 = (int32_t)(g * a1 * FX_ONE);
    f->a3 = (int32_t)(g * g * a1 * FX_ONE);
    f->k = (int32_t)(k * FX_ONE);
    f->ic1 = 0;
    f->ic2 = 0;
    f->on = 1;
}

// Integer SVF step. Returns lowpass output if low!=0, else highpass.
// always_inline so it folds into the RAM-resident mix_block (never left in flash).
static inline __attribute__((always_inline)) int32_t svf_run(svf_t *f, int32_t x, int low) {
    int32_t v3 = x - f->ic2;
    int32_t v1 = (int32_t)(((int64_t)f->a1 * f->ic1 + (int64_t)f->a2 * v3) >> Q);
    int32_t v2 = f->ic2 + (int32_t)(((int64_t)f->a2 * f->ic1 + (int64_t)f->a3 * v3) >> Q);
    f->ic1 = 2 * v1 - f->ic1;
    f->ic2 = 2 * v2 - f->ic2;
    if (low) {
        return v2;
    }
    return x - (int32_t)(((int64_t)f->k * v1) >> Q) - v2;
}

// RAM-resident: the audio ISR must never fetch its own code from flash (XIP).
// When Core 1 (display) and Core 0 (MicroPython) are both hammering flash, an
// IRQ that runs from XIP can hard-fault the board. Placing the whole mix path
// in RAM removes that dependency. svf_run is static inline and folds in here.
static void __not_in_flash_func(mix_block)(uint32_t *buf) {
    const int32_t half = (int32_t)(pwm_wrap / 2);
    for (int i = 0; i < BLOCK; i++) {
        int32_t acc = 0;
        for (int v = 0; v < MAX_VOICES; v++) {
            voice_t *vp = &voices[v];
            if (!vp->active) {
                continue;
            }
            int32_t x = ((int32_t)vp->data[vp->pos] - 128) << 9;  // ~ -1..1 Q16
            x = (int32_t)(((int64_t)x * vp->gain) >> Q);
            if (vp->hp.on) {
                x = svf_run(&vp->hp, x, 0);
            }
            if (vp->lp.on) {
                x = svf_run(&vp->lp, x, 1);
            }
            x = (int32_t)(((int64_t)x * vp->env) >> Q);
            acc += x;

            switch (vp->env_stage) {
                case 0:
                    vp->env += vp->a_inc;
                    if (vp->env >= FX_ONE) { vp->env = FX_ONE; vp->env_stage = 1; }
                    break;
                case 1:
                    vp->env -= vp->d_inc;
                    if (vp->env <= vp->sus) { vp->env = vp->sus; vp->env_stage = 2; }
                    break;
                case 2:
                    vp->env = vp->sus;
                    break;
                default:
                    vp->env -= vp->r_inc;
                    if (vp->env <= 0) { vp->env = 0; vp->active = false; }
                    break;
            }
            vp->age++;
            if (vp->gate && vp->age >= vp->gate && vp->env_stage < 3) {
                vp->env_stage = 3;
            }
            if (++vp->pos >= vp->len) {
                vp->active = false;
            }
        }
        int32_t level = (int32_t)(((int64_t)acc * (int32_t)pwm_wrap) >> (Q + 1)) + half;
        if (level < 0) {
            level = 0;
        } else if (level > (int32_t)pwm_wrap) {
            level = pwm_wrap;
        }
        buf[i] = ((uint32_t)level << 16) | (uint32_t)level;
    }
}

static void __isr __not_in_flash_func(dma_handler)(void) {
    irq_count++;
    if (dma_hw->ints0 & (1u << dma_la)) {
        dma_hw->ints0 = 1u << dma_la;
        mix_block(audio_buf[0]);
        dma_channel_set_read_addr(dma_la, audio_buf[0], false);
    }
    if (dma_hw->ints0 & (1u << dma_lb)) {
        dma_hw->ints0 = 1u << dma_lb;
        mix_block(audio_buf[1]);
        dma_channel_set_read_addr(dma_lb, audio_buf[1], false);
    }
    if (dma_hw->ints0 & (1u << dma_ra)) {
        dma_hw->ints0 = 1u << dma_ra;
        dma_channel_set_read_addr(dma_ra, audio_buf[0], false);
    }
    if (dma_hw->ints0 & (1u << dma_rb)) {
        dma_hw->ints0 = 1u << dma_rb;
        dma_channel_set_read_addr(dma_rb, audio_buf[1], false);
    }
}

// ---- DMA / PWM setup -------------------------------------------------------

static void setup_pair(int ca, int cb, uint slice) {
    volatile void *cc = &pwm_hw->slice[slice].cc;
    uint dreq = DREQ_PWM_WRAP0 + slice;

    dma_channel_config a = dma_channel_get_default_config(ca);
    channel_config_set_transfer_data_size(&a, DMA_SIZE_32);
    channel_config_set_read_increment(&a, true);
    channel_config_set_write_increment(&a, false);
    channel_config_set_dreq(&a, dreq);
    channel_config_set_chain_to(&a, cb);
    dma_channel_configure(ca, &a, (void *)cc, audio_buf[0], BLOCK, false);

    dma_channel_config b = dma_channel_get_default_config(cb);
    channel_config_set_transfer_data_size(&b, DMA_SIZE_32);
    channel_config_set_read_increment(&b, true);
    channel_config_set_write_increment(&b, false);
    channel_config_set_dreq(&b, dreq);
    channel_config_set_chain_to(&b, ca);
    dma_channel_configure(cb, &b, (void *)cc, audio_buf[1], BLOCK, false);

    dma_channel_set_irq0_enabled(ca, true);
    dma_channel_set_irq0_enabled(cb, true);
}

static void setup_slice(uint slice) {
    pwm_config cfg = pwm_get_default_config();
    pwm_config_set_wrap(&cfg, pwm_wrap);
    pwm_config_set_clkdiv(&cfg, 1.0f);
    pwm_init(slice, &cfg, true);
}

static mp_obj_t ps_init(size_t n_args, const mp_obj_t *args) {
    int sr = (n_args >= 1) ? mp_obj_get_int(args[0]) : DEFAULT_SR;
    if (running) {
        return mp_obj_new_float(actual_sr);
    }
    for (int v = 0; v < MAX_VOICES; v++) {
        voices[v].active = false;
    }

    uint32_t sysclk = clock_get_hz(clk_sys);
    uint32_t top = sysclk / (uint32_t)sr;
    if (top < 2) {
        top = 2;
    } else if (top > 65536) {
        top = 65536;
    }
    pwm_wrap = top - 1;
    actual_sr = (float)sysclk / (float)top;

    gpio_set_function(AUDIO_GPIO_L, GPIO_FUNC_PWM);
    gpio_set_function(AUDIO_GPIO_R, GPIO_FUNC_PWM);
    slice_l = pwm_gpio_to_slice_num(AUDIO_GPIO_L);
    slice_r = pwm_gpio_to_slice_num(AUDIO_GPIO_R);
    setup_slice(slice_l);
    setup_slice(slice_r);

    uint32_t s = pwm_wrap / 2;
    uint32_t silence = (s << 16) | s;
    for (int i = 0; i < BLOCK; i++) {
        audio_buf[0][i] = silence;
        audio_buf[1][i] = silence;
    }

    dma_la = dma_claim_unused_channel(true);
    dma_lb = dma_claim_unused_channel(true);
    dma_ra = dma_claim_unused_channel(true);
    dma_rb = dma_claim_unused_channel(true);
    setup_pair(dma_la, dma_lb, slice_l);
    setup_pair(dma_ra, dma_rb, slice_r);

    irq_add_shared_handler(DMA_IRQ_0, dma_handler,
                           PICO_SHARED_IRQ_HANDLER_DEFAULT_ORDER_PRIORITY);
    irq_set_enabled(DMA_IRQ_0, true);

    running = true;
    dma_start_channel_mask((1u << dma_la) | (1u << dma_ra));
    return mp_obj_new_float(actual_sr);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ps_init_obj, 0, 1, ps_init);

// ---- API -------------------------------------------------------------------

static mp_obj_t ps_register(mp_obj_t buf_in) {
    if (n_samples >= MAX_SAMPLES) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("sample table full"));
    }
    mp_buffer_info_t bi;
    mp_get_buffer_raise(buf_in, &bi, MP_BUFFER_READ);
    samples[n_samples].data = (const uint8_t *)bi.buf;
    samples[n_samples].len = bi.len;
    MP_STATE_PORT(picosampler_keepalive)[n_samples] = buf_in;
    return MP_OBJ_NEW_SMALL_INT(n_samples++);
}
static MP_DEFINE_CONST_FUN_OBJ_1(ps_register_obj, ps_register);

// play(id, gain=256, *, lpf=0, hpf=0, res=70, a=0, d=0, s=255, r=0, dur=0)
//   lpf/hpf : cutoff Hz (0 = bypass)   res : resonance/Q*100 (70 ~= 0.7)
//   a/d/r   : ms                       s   : sustain 0-255   dur : gate ms
static mp_obj_t ps_play(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    enum { ARG_id, ARG_gain, ARG_lpf, ARG_hpf, ARG_res, ARG_a, ARG_d, ARG_s, ARG_r, ARG_dur };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_id,   MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_gain, MP_ARG_INT, {.u_int = 256} },
        { MP_QSTR_lpf,  MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_hpf,  MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_res,  MP_ARG_INT, {.u_int = 70} },
        { MP_QSTR_a,    MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_d,    MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_s,    MP_ARG_INT, {.u_int = 255} },
        { MP_QSTR_r,    MP_ARG_INT, {.u_int = 0} },
        { MP_QSTR_dur,  MP_ARG_INT, {.u_int = 0} },
    };
    mp_arg_val_t a[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed), allowed, a);

    int id = a[ARG_id].u_int;
    if (id < 0 || id >= n_samples) {
        mp_raise_ValueError(MP_ERROR_TEXT("bad sample id"));
    }
    float fs = actual_sr > 0.0f ? actual_sr : DEFAULT_SR;

    for (int vi = 0; vi < MAX_VOICES; vi++) {
        voice_t *vp = &voices[vi];
        if (vp->active) {
            continue;
        }
        vp->data = samples[id].data;
        vp->len = samples[id].len;
        vp->pos = 0;
        vp->gain = (int32_t)a[ARG_gain].u_int << 8;     // 256 -> 1.0 in Q16

        int sl = a[ARG_s].u_int;
        vp->sus = (int32_t)((int64_t)sl * FX_ONE / 255);
        int ms_a = a[ARG_a].u_int, ms_d = a[ARG_d].u_int, ms_r = a[ARG_r].u_int;
        vp->a_inc = ms_a > 0 ? (int32_t)(FX_ONE / (ms_a * 0.001f * fs)) : FX_ONE + 1;
        vp->d_inc = ms_d > 0 ? (int32_t)((FX_ONE - vp->sus) / (ms_d * 0.001f * fs)) : FX_ONE + 1;
        vp->r_inc = ms_r > 0 ? (int32_t)(FX_ONE / (ms_r * 0.001f * fs)) : FX_ONE + 1;
        if (vp->a_inc < 1) vp->a_inc = 1;
        if (vp->d_inc < 1) vp->d_inc = 1;
        if (vp->r_inc < 1) vp->r_inc = 1;
        if (ms_a > 0) {
            vp->env = 0;
            vp->env_stage = 0;
        } else {
            vp->env = FX_ONE;
            vp->env_stage = 1;
        }
        int dur = a[ARG_dur].u_int;
        vp->gate = dur > 0 ? (uint32_t)(dur * 0.001f * fs) : 0;
        vp->age = 0;

        svf_set(&vp->hp, a[ARG_hpf].u_int, a[ARG_res].u_int);
        svf_set(&vp->lp, a[ARG_lpf].u_int, a[ARG_res].u_int);

        __dmb();
        vp->active = true;
        return MP_OBJ_NEW_SMALL_INT(vi);
    }
    return MP_OBJ_NEW_SMALL_INT(-1);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(ps_play_obj, 1, ps_play);

static mp_obj_t ps_stop_all(void) {
    for (int v = 0; v < MAX_VOICES; v++) {
        voices[v].active = false;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ps_stop_all_obj, ps_stop_all);

static mp_obj_t ps_sample_rate(void) {
    return mp_obj_new_float(actual_sr);
}
static MP_DEFINE_CONST_FUN_OBJ_0(ps_sample_rate_obj, ps_sample_rate);

static mp_obj_t ps_stats(void) {
    mp_obj_t d = mp_obj_new_dict(0);
    int nv = 0;
    for (int v = 0; v < MAX_VOICES; v++) {
        if (voices[v].active) {
            nv++;
        }
    }
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_running), mp_obj_new_bool(running));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_irq_count), mp_obj_new_int(irq_count));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_voices), mp_obj_new_int(nv));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_slice_l), mp_obj_new_int(slice_l));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_slice_r), mp_obj_new_int(slice_r));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_wrap), mp_obj_new_int(pwm_wrap));
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ps_stats_obj, ps_stats);

static mp_obj_t ps_deinit(void) {
    if (!running) {
        return mp_const_none;
    }
    running = false;
    int chans[4] = { dma_la, dma_lb, dma_ra, dma_rb };
    for (int i = 0; i < 4; i++) {
        dma_channel_abort(chans[i]);
        dma_channel_set_irq0_enabled(chans[i], false);
        dma_channel_unclaim(chans[i]);
    }
    irq_remove_handler(DMA_IRQ_0, dma_handler);
    pwm_set_enabled(slice_l, false);
    pwm_set_enabled(slice_r, false);
    for (int v = 0; v < MAX_VOICES; v++) {
        voices[v].active = false;
    }
    dma_la = dma_lb = dma_ra = dma_rb = -1;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ps_deinit_obj, ps_deinit);

static const mp_rom_map_elem_t picosampler_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),    MP_ROM_QSTR(MP_QSTR_picosampler) },
    { MP_ROM_QSTR(MP_QSTR_init),        MP_ROM_PTR(&ps_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_register),    MP_ROM_PTR(&ps_register_obj) },
    { MP_ROM_QSTR(MP_QSTR_play),        MP_ROM_PTR(&ps_play_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop_all),    MP_ROM_PTR(&ps_stop_all_obj) },
    { MP_ROM_QSTR(MP_QSTR_sample_rate), MP_ROM_PTR(&ps_sample_rate_obj) },
    { MP_ROM_QSTR(MP_QSTR_stats),       MP_ROM_PTR(&ps_stats_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit),      MP_ROM_PTR(&ps_deinit_obj) },
};
static MP_DEFINE_CONST_DICT(picosampler_globals, picosampler_globals_table);

const mp_obj_module_t picosampler_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&picosampler_globals,
};

MP_REGISTER_MODULE(MP_QSTR_picosampler, picosampler_user_cmodule);
