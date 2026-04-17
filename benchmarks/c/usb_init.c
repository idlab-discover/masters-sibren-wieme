// usb_init.c — Meet de initialisatie-overhead van de USB-stack.
//
// Fases per iteratie:
//   1. libusb_init
//   2. libusb_get_device_list + get_device_descriptor loop (enumerate)
//   3. libusb_open_device_with_vid_pid
//   4. libusb_claim_interface
//   5. libusb_release_interface + libusb_close + libusb_exit (teardown)
//
// Elke fase wordt apart getimed — zo kun je in de thesis onderscheiden welk
// deel van de "USB-stack startup" duurder wordt in WASM (vooral init + open
// gaan door de component-model grens).
//
// Usage: usb_init <vid> <pid> <iface> <iterations> [variant]
#include "libusb.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

static double get_time_ms(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000.0 + ts.tv_nsec / 1000000.0;
}

int main(int argc, char *argv[]) {
  if (argc < 5) {
    printf("Usage: %s <vid> <pid> <iface> <iterations> [variant]\n", argv[0]);
    return 1;
  }

  uint16_t vid = (uint16_t)strtol(argv[1], NULL, 16);
  uint16_t pid = (uint16_t)strtol(argv[2], NULL, 16);
  int iface = atoi(argv[3]);
  int iterations = atoi(argv[4]);
  const char *variant = (argc > 5) ? argv[5] : "libusb_native";

  if (iterations <= 0) {
    fprintf(stderr, "iterations moet > 0 zijn\n");
    return 1;
  }

  mkdir("results", 0755);
  char csv_path[256];
  snprintf(csv_path, sizeof(csv_path),
           "results/init_results_%s.csv", variant);
  FILE *f = fopen(csv_path, "w");
  if (!f) {
    fprintf(stderr, "Kon %s niet openen\n", csv_path);
    return 1;
  }
  fprintf(f, "iteration,init_ms,enumerate_ms,open_ms,claim_ms,teardown_ms,total_ms\n");

  printf("Starting init benchmark (%d iterations) voor %04x:%04x [%s]\n",
         iterations, vid, pid, variant);

  double sum_total = 0;
  for (int i = 0; i < iterations; i++) {
    libusb_context *ctx = NULL;
    libusb_device **list = NULL;
    libusb_device_handle *handle = NULL;

    /* Fase 1: init */
    double t0 = get_time_ms();
    if (libusb_init(&ctx) < 0) {
      fprintf(stderr, "libusb_init faalde op iter %d\n", i);
      break;
    }
    double t1 = get_time_ms();

    /* Fase 2: enumerate (list + descriptors) */
    ssize_t cnt = libusb_get_device_list(ctx, &list);
    if (cnt < 0) {
      fprintf(stderr, "get_device_list faalde (%ld)\n", (long)cnt);
      libusb_exit(ctx);
      break;
    }
    for (ssize_t k = 0; k < cnt; k++) {
      struct libusb_device_descriptor desc;
      libusb_get_device_descriptor(list[k], &desc);
    }
    double t2 = get_time_ms();

    /* Fase 3: open doel-device */
    handle = libusb_open_device_with_vid_pid(ctx, vid, pid);
    double t3 = get_time_ms();
    if (!handle) {
      fprintf(stderr, "open faalde voor %04x:%04x op iter %d\n", vid, pid, i);
      libusb_free_device_list(list, 1);
      libusb_exit(ctx);
      break;
    }

    /* Fase 4: claim */
    if (libusb_kernel_driver_active(handle, iface) == 1)
      libusb_detach_kernel_driver(handle, iface);
    int cr = libusb_claim_interface(handle, iface);
    double t4 = get_time_ms();
    if (cr < 0) {
      fprintf(stderr, "claim faalde (%d) op iter %d\n", cr, i);
      libusb_close(handle);
      libusb_free_device_list(list, 1);
      libusb_exit(ctx);
      break;
    }

    /* Fase 5: teardown */
    libusb_release_interface(handle, iface);
    libusb_close(handle);
    libusb_free_device_list(list, 1);
    libusb_exit(ctx);
    double t5 = get_time_ms();

    double init_ms = t1 - t0;
    double enum_ms = t2 - t1;
    double open_ms = t3 - t2;
    double claim_ms = t4 - t3;
    double tear_ms = t5 - t4;
    double total = t5 - t0;
    sum_total += total;

    fprintf(f, "%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n",
            i + 1, init_ms, enum_ms, open_ms, claim_ms, tear_ms, total);
  }

  fclose(f);
  printf("Gemiddeld totaal: %.3f ms  — CSV: %s\n",
         sum_total / iterations, csv_path);
  return 0;
}
