# MicroPython USB-CDC Regression on RP2350 (Pico 2W)

## Summary

MicroPython versions v1.26.0 through v1.27.0 (and likely v1.28.0+) fail to enumerate USB-CDC on the RP2350 (Raspberry Pi Pico 2W). The device does not appear as a serial port on the host. The last working version is v1.25.0-preview (commit f187c77da).

## Root Cause

In the transition from v1.25.0 to v1.26.0, the `--wrap=dcd_event_handler` linker flag and its corresponding `__wrap_dcd_event_handler()` function were removed from `ports/rp2/CMakeLists.txt` and `shared/tinyusb/mp_usbd.c`.

The removal was intentional -- TinyUSB added a `tud_event_hook_cb()` callback (called from `usbd.c:383`) meant to replace the linker wrap. MicroPython v1.26.0+ implements this hook via `MICROPY_WRAP_TUD_EVENT_HOOK_CB` in `shared/tinyusb/mp_usbd.c`.

However, on the RP2350, the TinyUSB hook alone is not sufficient for USB device enumeration to succeed. The linker wrap is still needed. The RP2040 may not be affected (untested).

## The Fix

Two changes restore USB functionality on RP2350 while keeping all v1.27.0 features (including BLE security):

### 1. `ports/rp2/CMakeLists.txt` -- Re-add linker wrap

```diff
 target_link_options(${MICROPY_TARGET} PRIVATE
     -Wl,--defsym=__micropy_c_heap_size__=${MICROPY_C_HEAP_SIZE}
+    -Wl,--wrap=dcd_event_handler
     -Wl,--wrap=runtime_init_clocks
 )
```

### 2. `shared/tinyusb/mp_usbd.c` -- Re-add wrapper function

Add before the `tud_event_hook_cb` function:

```c
extern void __real_dcd_event_handler(dcd_event_t const *event, bool in_isr);

TU_ATTR_FAST_FUNC void __wrap_dcd_event_handler(dcd_event_t const *event, bool in_isr) {
    __real_dcd_event_handler(event, in_isr);
    mp_usbd_schedule_task();
    mp_hal_wake_main_task_from_isr();
}
```

Both the hook (`tud_event_hook_cb`) and the wrap (`__wrap_dcd_event_handler`) can coexist safely -- v1.25.0-preview had both. The wrap ensures the USB task is scheduled from the ISR context, which appears to be required on RP2350 for enumeration to complete.

## Affected Versions

| Version | USB on RP2350 | BLE Security |
|---------|---------------|--------------|
| v1.25.0-preview (f187c77da) | Works | No (config params unknown) |
| v1.26.0 | Broken | Yes |
| v1.27.0 | Broken | Yes |
| v1.27.0 + patch (above) | Works | Yes |
| v1.28.0-preview | Broken (untested, assumed) | Yes |

## How to Reproduce

1. Build MicroPython v1.27.0 for `BOARD=RPI_PICO2_W`
2. Flash the .uf2 to a Raspberry Pi Pico 2W
3. Connect via USB -- no serial port appears (`ls /dev/tty.usbmodem*` on macOS returns nothing)
4. Apply the two-line fix above, rebuild, reflash
5. USB serial port appears and works normally

## Environment

- Hardware: Raspberry Pi Pico 2W (RP2350)
- Host: macOS (tested), should affect all platforms
- Build: Docker (Ubuntu 24.04, gcc-arm-none-eabi)
- pico-sdk: 2.1.1
- TinyUSB: bundled with MicroPython (commit aa0fc2e in v1.27.0)

## Upstream Bug Report

https://github.com/micropython/micropython/issues/18990

## Discovered

2026-03-24 by LofiFren (PicoCalc project)
https://github.com/LofiFren/PicoCalc
