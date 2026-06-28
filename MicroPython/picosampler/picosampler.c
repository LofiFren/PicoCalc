// picosampler - DMA-paced PWM audio mixer for PicoCalc (RP2350 / Pico 2W).
//
// Milestone 1 of the "Strudel on PicoCalc" port (option C1): a native C audio
// engine that mixes short 8-bit PCM one-shots and streams them out the audio
// PWM pins via DMA, so the device can actually play sampled sounds (bd/sd/hh...)
// instead of pulse-wave chiptune.
//
// Design (standard Pico PWM-audio method):
//   - Each audio PWM slice runs AT the sample rate: period = sys_clk / SR cycles,
//     so each PWM wrap is one output sample and the duty is the sample value.
//     With sys_clk 150MHz and SR ~22kHz that gives ~12-13 bits of duty
//     resolution. The speaker/headphone path reconstructs the waveform.
//   - The PWM's per-wrap DREQ paces ping-pong DMA channels that copy duty values
//     into the PWM compare register - exactly one transfer per sample, so the
//     DMA can never free-run.
//   - We drive BOTH audio pins (GPIO 28 left, GPIO 27 right) with the same mono
//     mix. They are on different PWM slices, so a second DMA pair feeds the right
//     slice from the same buffers; both pairs start atomically and stay locked.
//     Each duty value is written into both halves of the 32-bit CC word
//     ((level<<16)|level) so it lands in whichever channel (A or B) the pin uses.
//   - On block completion the DMA IRQ mixes the next block of all active voices
//     into the buffer the LEFT pair just drained; the right pair only rewinds.
//
// Notes:
//   - irq_set must be a SHARED handler: MicroPython's rp2 port already installs
//     a shared handler on DMA_IRQ_0; an exclusive claim panics and hangs.
//   - Samples live in MicroPython bytes/bytearray objects passed to register();
//     a GC root keeps them alive (non-moving GC keeps the raw pointer valid).

#include "py/runtime.h"
#include "py/obj.h"
#include "py/mphal.h"
#include <string.h>

#include "pico/stdlib.h"
#include "hardware/pwm.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"

#define AUDIO_GPIO_L    28      // left audio PWM pin
#define AUDIO_GPIO_R    27      // right audio PWM pin
#define BLOCK           256     // samples per DMA block (per ping-pong half)
#define MAX_VOICES      8
#define MAX_SAMPLES     16
#define DEFAULT_SR      22050

typedef struct {
    const uint8_t *data;   // pointer into a kept-alive bytes object
    uint32_t len;
} sample_t;

typedef struct {
    const uint8_t *data;
    uint32_t len;
    uint32_t pos;
    int32_t gain;          // 8.8 fixed point (256 = unity)
    volatile bool active;
} voice_t;

// Two output blocks for ping-pong DMA. Each word holds the duty in both
// half-words so one DMA write drives whichever channel (A/B) a pin uses, and
// narrow-write byte-replication on RP2xxx is never an issue.
static uint32_t audio_buf[2][BLOCK];

static sample_t samples[MAX_SAMPLES];
static int n_samples = 0;

static voice_t voices[MAX_VOICES];

static uint slice_l, slice_r;
static uint32_t pwm_wrap;      // PWM TOP = full-scale duty value
static int dma_la = -1, dma_lb = -1, dma_ra = -1, dma_rb = -1;
static volatile bool running = false;
static volatile uint32_t irq_count = 0;   // proves the DMA/IRQ is actually firing
static float actual_sr = 0.0f;

// Keep registered sample buffers alive across GC. Scanned by the collector.
MP_REGISTER_ROOT_POINTER(mp_obj_t picosampler_keepalive[MAX_SAMPLES]);

// Mix all active voices into one block (called from the DMA IRQ).
static void mix_block(uint32_t *buf) {
    for (int i = 0; i < BLOCK; i++) {
        int32_t acc = 0;
        for (int v = 0; v < MAX_VOICES; v++) {
            voice_t *vp = &voices[v];
            if (!vp->active) {
                continue;
            }
            // 8-bit unsigned PCM centered at 128 -> signed, scaled by gain.
            acc += (((int32_t)vp->data[vp->pos] - 128) * vp->gain) >> 8;
            if (++vp->pos >= vp->len) {
                vp->active = false;
            }
        }
        int32_t out = acc + 128;       // back to 0..255 unsigned
        if (out < 0) {
            out = 0;
        } else if (out > 255) {
            out = 255;
        }
        // Scale 8-bit sample up to the PWM full-scale duty; duplicate into both
        // half-words so it drives channel A or B of whatever slice gets it.
        uint32_t level = (uint32_t)out * pwm_wrap / 255;
        buf[i] = (level << 16) | level;
    }
}

static void __isr dma_handler(void) {
    irq_count++;
    // Mix only on the LEFT pair's completion (that advances the voices once).
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
    // Right pair plays the same buffers; just rewind it.
    if (dma_hw->ints0 & (1u << dma_ra)) {
        dma_hw->ints0 = 1u << dma_ra;
        dma_channel_set_read_addr(dma_ra, audio_buf[0], false);
    }
    if (dma_hw->ints0 & (1u << dma_rb)) {
        dma_hw->ints0 = 1u << dma_rb;
        dma_channel_set_read_addr(dma_rb, audio_buf[1], false);
    }
}

// Configure a ping-pong DMA pair feeding one PWM slice's CC register.
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

    // PWM period = top cycles -> output sample rate = sys_clk / top.
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

    // Prime both blocks with silence (midpoint duty in both half-words).
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

    // Shared (not exclusive) handler: MicroPython's rp2 port owns DMA_IRQ_0 with
    // a shared handler; an exclusive claim would panic() and hang the board.
    irq_add_shared_handler(DMA_IRQ_0, dma_handler,
                           PICO_SHARED_IRQ_HANDLER_DEFAULT_ORDER_PRIORITY);
    irq_set_enabled(DMA_IRQ_0, true);

    running = true;
    // Start both left and right lead channels atomically so they stay locked.
    dma_start_channel_mask((1u << dma_la) | (1u << dma_ra));
    return mp_obj_new_float(actual_sr);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ps_init_obj, 0, 1, ps_init);

// register(buf) -> sample id. buf is bytes/bytearray of 8-bit unsigned PCM.
static mp_obj_t ps_register(mp_obj_t buf_in) {
    if (n_samples >= MAX_SAMPLES) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("sample table full"));
    }
    mp_buffer_info_t bi;
    mp_get_buffer_raise(buf_in, &bi, MP_BUFFER_READ);
    samples[n_samples].data = (const uint8_t *)bi.buf;
    samples[n_samples].len = bi.len;
    MP_STATE_PORT(picosampler_keepalive)[n_samples] = buf_in;  // pin against GC
    return MP_OBJ_NEW_SMALL_INT(n_samples++);
}
static MP_DEFINE_CONST_FUN_OBJ_1(ps_register_obj, ps_register);

// play(id, gain=256) -> voice index, or -1 if no free voice.
static mp_obj_t ps_play(size_t n_args, const mp_obj_t *args) {
    int id = mp_obj_get_int(args[0]);
    if (id < 0 || id >= n_samples) {
        mp_raise_ValueError(MP_ERROR_TEXT("bad sample id"));
    }
    int32_t gain = (n_args >= 2) ? mp_obj_get_int(args[1]) : 256;

    for (int v = 0; v < MAX_VOICES; v++) {
        if (!voices[v].active) {
            voices[v].data = samples[id].data;
            voices[v].len = samples[id].len;
            voices[v].pos = 0;
            voices[v].gain = gain;
            __dmb();
            voices[v].active = true;
            return MP_OBJ_NEW_SMALL_INT(v);
        }
    }
    return MP_OBJ_NEW_SMALL_INT(-1);  // voice stealing is a later enhancement
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ps_play_obj, 1, 2, ps_play);

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

// stats() -> dict of live engine state for diagnostics.
static mp_obj_t ps_stats(void) {
    mp_obj_t d = mp_obj_new_dict(0);
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_running), mp_obj_new_bool(running));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_irq_count), mp_obj_new_int(irq_count));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_slice_l), mp_obj_new_int(slice_l));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_slice_r), mp_obj_new_int(slice_r));
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_wrap), mp_obj_new_int(pwm_wrap));
    uint32_t cc = running ? (pwm_hw->slice[slice_l].cc & 0xffff) : 0;
    mp_obj_dict_store(d, MP_ROM_QSTR(MP_QSTR_cc), mp_obj_new_int(cc));
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(ps_stats_obj, ps_stats);

// deinit() -> release PWM/DMA/IRQ so the pins can be handed back to machine.PWM.
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
