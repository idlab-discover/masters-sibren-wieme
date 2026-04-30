/*
 * wasm_reactor.c — WASM reactor entry point for C2 (wasi-libusb) builds.
 *
 * When linking against libusb-wasi.a, cguest.o exports the WASM function
 * "wasi:cli/run@0.2.0#run" via a generated wrapper that calls the C symbol
 * exports_wasi_cli_run_run(). Each benchmark defines main() in the normal way;
 * this file bridges the two so no benchmark source file needs modification.
 *
 * Compiled only for WASM targets (CMAKE_SYSTEM_NAME == WASI).
 */

#include <stdbool.h>
#include <stddef.h>

/* Provided by each benchmark's main file. */
int main(int argc, char **argv);

bool exports_wasi_cli_run_run(void) {
    return main(0, NULL) == 0;
}
