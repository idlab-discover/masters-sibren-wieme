#include "libusb.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#define DEFAULT_TIMEOUT 1000
#define ITERATIONS 10000
#define WARMUP_ITERATIONS 1000

void print_usage(char *name) {
  printf("Usage: %s <vid> <pid> <interface> <ep_out> <ep_in> <size_bytes> "
         "[iterations] [variant]\n",
         name);
  printf("Example: %s 0xabcd 0x1234 1 0x01 0x81 64 10000 libusb_native\n",
         name);
}

double get_time_ms() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (ts.tv_sec * 1000.0) + (ts.tv_nsec / 1000000.0);
}

int main(int argc, char *argv[]) {
  if (argc < 7) {
    print_usage(argv[0]);
    return 1;
  }

  uint16_t vid = (uint16_t)strtol(argv[1], NULL, 16);
  uint16_t pid = (uint16_t)strtol(argv[2], NULL, 16);
  int interface = atoi(argv[3]);
  uint8_t ep_out = (uint8_t)strtol(argv[4], NULL, 16);
  uint8_t ep_in = (uint8_t)strtol(argv[5], NULL, 16);
  int size_bytes = atoi(argv[6]);
  int iterations = (argc > 7) ? atoi(argv[7]) : ITERATIONS;
  const char *variant = (argc > 8) ? argv[8] : "libusb_native";

  if (size_bytes <= 0 || size_bytes % 64 != 0) {
    fprintf(stderr,
            "Fout: size_bytes (%d) moet een veelvoud van 64 zijn "
            "(USB 2.0 bulk max-packet-size).\n"
            "Geldige waarden: 64, 128, 192, 256, 512, 1024, ...\n",
            size_bytes);
    return 1;
  }

  libusb_context *ctx = NULL;
  libusb_device_handle *handle = NULL;
  int r;

  r = libusb_init(&ctx);
  if (r < 0) {
    fprintf(stderr, "Init Error %d\n", r);
    return 1;
  }

  handle = libusb_open_device_with_vid_pid(ctx, vid, pid);
  if (!handle) {
    fprintf(stderr, "Cannot open device %04x:%04x\n", vid, pid);
    libusb_exit(ctx);
    return 1;
  }

  if (libusb_kernel_driver_active(handle, interface) == 1)
    libusb_detach_kernel_driver(handle, interface);

  r = libusb_claim_interface(handle, interface);
  if (r < 0) {
    fprintf(stderr, "Cannot Claim Interface %d: %d\n", interface, r);
    libusb_close(handle);
    libusb_exit(ctx);
    return 1;
  }

  // Dynamische buffers op basis van opgegeven grootte
  unsigned char *ping = (unsigned char *)calloc(size_bytes, 1);
  unsigned char *pong = (unsigned char *)calloc(size_bytes, 1);
  if (!ping || !pong) {
    fprintf(stderr, "calloc failed\n");
    return 1;
  }
  memset(ping, 0xAB, size_bytes); // Herkenbaar patroon

  double *rtts = (double *)malloc(iterations * sizeof(double));
  if (!rtts) {
    fprintf(stderr, "malloc failed\n");
    return 1;
  }

  int actual_length;

  // --- Warmup ---
  printf("Starting Warmup (%d iterations, %d bytes)...\n", WARMUP_ITERATIONS,
         size_bytes);
  for (int i = 0; i < WARMUP_ITERATIONS; i++) {
    r = libusb_bulk_transfer(handle, ep_out, ping, size_bytes, &actual_length,
                             DEFAULT_TIMEOUT);
    if (r < 0) {
      fprintf(stderr, "Bulk Out Error %d at warmup %d\n", r, i);
      break;
    }
    r = libusb_bulk_transfer(handle, ep_in, pong, size_bytes, &actual_length,
                             DEFAULT_TIMEOUT);
    if (r < 0) {
      fprintf(stderr, "Bulk In Error %d at warmup %d\n", r, i);
      break;
    }
  }

  // --- Meting ---
  printf("Starting Measurement (%d iterations, %d bytes)...\n", iterations,
         size_bytes);

  double total_rtt = 0, min_rtt = 999999, max_rtt = 0;
  int measured = 0;

  for (int i = 0; i < iterations; i++) {
    double start = get_time_ms();

    r = libusb_bulk_transfer(handle, ep_out, ping, size_bytes, &actual_length,
                             DEFAULT_TIMEOUT);
    if (r < 0) {
      fprintf(stderr, "Bulk Out Error %d at iteration %d\n", r, i);
      break;
    }
    r = libusb_bulk_transfer(handle, ep_in, pong, size_bytes, &actual_length,
                             DEFAULT_TIMEOUT);
    if (r < 0) {
      fprintf(stderr, "Bulk In Error %d at iteration %d\n", r, i);
      break;
    }

    double end = get_time_ms();
    double rtt = end - start;
    rtts[measured++] = rtt;
    total_rtt += rtt;
    if (rtt < min_rtt)
      min_rtt = rtt;
    if (rtt > max_rtt)
      max_rtt = rtt;
  }

  // --- Statistieken ---
  printf("\n--- Statistics (%d samples, %d bytes) ---\n", measured, size_bytes);
  printf("Average RTT: %.3f ms\n", total_rtt / measured);
  printf("Min RTT:     %.3f ms\n", min_rtt);
  printf("Max RTT:     %.3f ms\n", max_rtt);

  // --- CSV: bestandsnaam bevat variant + grootte ---
  mkdir("results", 0755);
  char csv_path[256];
  snprintf(csv_path, sizeof(csv_path), "results/rtt_results_latency_%s_%d.csv",
           variant, size_bytes);
  FILE *f = fopen(csv_path, "w");
  if (f) {
    fprintf(f, "iteration,size_bytes,rtt_ms\n");
    for (int i = 0; i < measured; i++)
      fprintf(f, "%d,%d,%.6f\n", i + 1, size_bytes, rtts[i]);
    fclose(f);
    printf("Results written to %s\n", csv_path);
  } else {
    fprintf(stderr, "Could not open %s for writing\n", csv_path);
  }

  free(ping);
  free(pong);
  free(rtts);
  libusb_release_interface(handle, interface);
  libusb_close(handle);
  libusb_exit(ctx);
  return 0;
}
