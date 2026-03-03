#include "libusb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
  if (argc < 6) {
    fprintf(stderr,
            "Usage: %s <VID> <PID> <INTERFACE> <EP_OUT> <EP_IN> [MESSAGE]\n",
            argv[0]);
    return 1;
  }

  uint16_t vid = (uint16_t)strtol(argv[1], NULL, 16);
  uint16_t pid = (uint16_t)strtol(argv[2], NULL, 16);
  int interface = atoi(argv[3]);
  uint8_t ep_out = (uint8_t)strtol(argv[4], NULL, 16);
  uint8_t ep_in = (uint8_t)strtol(argv[5], NULL, 16);
  char *msg = (argc > 6) ? argv[6] : "Hello WASI-USB Loopback!";

  libusb_context *ctx = NULL;
  libusb_device_handle *handle = NULL;
  int r;

  r = libusb_init(&ctx);
  if (r < 0)
    return 1;

  handle = libusb_open_device_with_vid_pid(ctx, vid, pid);
  if (!handle) {
    fprintf(stderr, "Could not open device %04x:%04x\n", vid, pid);
    libusb_exit(ctx);
    return 1;
  }

  libusb_set_auto_detach_kernel_driver(handle, 1);
  r = libusb_claim_interface(handle, interface);
  if (r < 0) {
    fprintf(stderr, "Claim interface %d failed: %s\n", interface,
            libusb_error_name(r));
    libusb_close(handle);
    libusb_exit(ctx);
    return 1;
  }

  int actual;
  printf("Writing: \"%s\" to EP 0x%02x...\n", msg, ep_out);
  r = libusb_bulk_transfer(handle, ep_out, (unsigned char *)msg, strlen(msg),
                           &actual, 1000);
  if (r < 0) {
    fprintf(stderr, "Write failed: %s\n", libusb_error_name(r));
  } else {
    printf("Write success (%d bytes sent)\n", actual);
  }

  unsigned char buffer[256];
  memset(buffer, 0, sizeof(buffer));
  printf("Reading from EP 0x%02x...\n", ep_in);
  r = libusb_bulk_transfer(handle, ep_in, buffer, sizeof(buffer) - 1, &actual,
                           1000);
  if (r < 0) {
    fprintf(stderr, "Read failed: %s\n", libusb_error_name(r));
  } else {
    printf("Read success (%d bytes): \"%s\"\n", actual, buffer);
  }

  libusb_release_interface(handle, interface);
  libusb_close(handle);
  libusb_exit(ctx);
  return 0;
}
