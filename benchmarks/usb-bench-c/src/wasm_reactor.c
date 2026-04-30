/*
 * wasm_reactor.c — WASM reactor entry point for C2 (wasi-libusb) builds.
 *
 * When linking against libusb-wasi.a, cguest.o calls the C symbol
 * exports_wasi_cli_run_run() which must bridge to main().
 *
 * WASI SDK >= 25 (e.g. macOS arm64 release) ships __main_void.o in libc.a
 * which already provides a *strong* exports_wasi_cli_run_run → main() bridge.
 * Older SDK versions (common on Linux) do not include it, so cguest.o ends
 * up with an undefined reference.
 *
 * Marking our definition __attribute__((weak)) makes it compatible with both:
 *   - SDK >= 25: the strong symbol from libc wins; our weak copy is discarded
 *     (no "duplicate symbol" linker error).
 *   - Older SDK: no strong symbol exists; our weak copy is used to satisfy
 *     the undefined reference from cguest.o.
 */

#include <stdbool.h>
#include <stddef.h>

/* Provided by each benchmark's main file. */
int main(int argc, char **argv);

__attribute__((weak))
bool exports_wasi_cli_run_run(void) {
    return main(0, NULL) == 0;
}
