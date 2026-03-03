#include "libusb.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#define DEFAULT_TIMEOUT 5000
#define BLOCK_SIZE 512
#define CHUNK_BLOCKS 128
#define CBW_SIGNATURE 0x43425355
#define CSW_SIGNATURE 0x53425355
#define MAX_RUNS 64
#define MIN_ELAPSED_MS 1.0

#pragma pack(push, 1)
typedef struct {
  uint32_t dCBWSignature;
  uint32_t dCBWTag;
  uint32_t dCBWDataTransferLength;
  uint8_t bmCBWFlags;
  uint8_t bCBWLUN;
  uint8_t bCBWCBLength;
  uint8_t CBWCB[16];
} CBW;

typedef struct {
  uint32_t dCSWSignature;
  uint32_t dCSWTag;
  uint32_t dCSWDataResidue;
  uint8_t bCSWStatus;
} CSW;
#pragma pack(pop)

/* ── Timing ──────────────────────────────────────────────────── */
static double get_time_ms(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000.0 + ts.tv_nsec / 1000000.0;
}

/* ── CBW builders ────────────────────────────────────────────── */
static void build_read10(CBW *cbw, uint32_t tag, uint32_t lba, uint16_t n) {
  memset(cbw, 0, sizeof(*cbw));
  cbw->dCBWSignature = CBW_SIGNATURE;
  cbw->dCBWTag = tag;
  cbw->dCBWDataTransferLength = n * BLOCK_SIZE;
  cbw->bmCBWFlags = 0x80;
  cbw->bCBWLUN = 0;
  cbw->bCBWCBLength = 10;
  cbw->CBWCB[0] = 0x28;
  cbw->CBWCB[2] = (lba >> 24) & 0xFF;
  cbw->CBWCB[3] = (lba >> 16) & 0xFF;
  cbw->CBWCB[4] = (lba >> 8) & 0xFF;
  cbw->CBWCB[5] = (lba) & 0xFF;
  cbw->CBWCB[7] = (n >> 8) & 0xFF;
  cbw->CBWCB[8] = (n) & 0xFF;
}

static void build_write10(CBW *cbw, uint32_t tag, uint32_t lba, uint16_t n) {
  memset(cbw, 0, sizeof(*cbw));
  cbw->dCBWSignature = CBW_SIGNATURE;
  cbw->dCBWTag = tag;
  cbw->dCBWDataTransferLength = n * BLOCK_SIZE;
  cbw->bmCBWFlags = 0x00;
  cbw->bCBWLUN = 0;
  cbw->bCBWCBLength = 10;
  cbw->CBWCB[0] = 0x2A;
  cbw->CBWCB[2] = (lba >> 24) & 0xFF;
  cbw->CBWCB[3] = (lba >> 16) & 0xFF;
  cbw->CBWCB[4] = (lba >> 8) & 0xFF;
  cbw->CBWCB[5] = (lba) & 0xFF;
  cbw->CBWCB[7] = (n >> 8) & 0xFF;
  cbw->CBWCB[8] = (n) & 0xFF;
}

/* ── MSC transfer: CBW → data → CSW ─────────────────────────── */
static int msc_transfer(libusb_device_handle *h, uint8_t ep_out, uint8_t ep_in,
                        CBW *cbw, unsigned char *data, int data_len,
                        int is_read) {
  int actual, r;

  r = libusb_bulk_transfer(h, ep_out, (unsigned char *)cbw, sizeof(CBW),
                           &actual, DEFAULT_TIMEOUT);
  if (r < 0) {
    fprintf(stderr, "  CBW send error: %s (%d)\n", libusb_strerror(r), r);
    return r;
  }
  if (actual != (int)sizeof(CBW)) {
    fprintf(stderr, "  CBW short write: %d/%zu bytes\n", actual, sizeof(CBW));
    return -1;
  }

  uint8_t ep = is_read ? ep_in : ep_out;
  r = libusb_bulk_transfer(h, ep, data, data_len, &actual, DEFAULT_TIMEOUT);
  if (r < 0) {
    fprintf(stderr, "  Data phase error: %s (%d)\n", libusb_strerror(r), r);
    return r;
  }

  CSW csw;
  r = libusb_bulk_transfer(h, ep_in, (unsigned char *)&csw, sizeof(CSW),
                           &actual, DEFAULT_TIMEOUT);
  if (r < 0) {
    fprintf(stderr, "  CSW recv error: %s (%d)\n", libusb_strerror(r), r);
    return r;
  }
  if (csw.dCSWSignature != CSW_SIGNATURE) {
    fprintf(stderr, "  CSW bad signature: 0x%08X\n", csw.dCSWSignature);
    return -1;
  }
  if (csw.bCSWStatus != 0) {
    fprintf(stderr, "  CSW status error: %d\n", csw.bCSWStatus);
    return -1;
  }
  return 0;
}

/* ── INQUIRY voor diagnose ───────────────────────────────────── */
static int run_inquiry(libusb_device_handle *h, uint8_t ep_out, uint8_t ep_in) {
  unsigned char cbw[31];
  memset(cbw, 0, sizeof(cbw));
  cbw[0] = 0x55;
  cbw[1] = 0x53;
  cbw[2] = 0x42;
  cbw[3] = 0x43;  /* signature */
  cbw[4] = 0xFF;  /* tag */
  cbw[8] = 0x24;  /* transfer length = 36 */
  cbw[12] = 0x80; /* flags = IN */
  cbw[14] = 0x06; /* CDB length */
  cbw[15] = 0x12; /* INQUIRY opcode */
  cbw[19] = 0x24; /* allocation length = 36 */

  unsigned char resp[36];
  int actual, r;

  r = libusb_bulk_transfer(h, ep_out, cbw, 31, &actual, 2000);
  if (r < 0 || actual != 31) {
    fprintf(stderr, "INQUIRY CBW mislukt: %s, actual=%d\n", libusb_strerror(r),
            actual);
    return -1;
  }
  r = libusb_bulk_transfer(h, ep_in, resp, 36, &actual, 2000);
  if (r < 0) {
    fprintf(stderr, "INQUIRY data mislukt: %s\n", libusb_strerror(r));
    return -1;
  }

  char vendor[9] = {0};
  char product[17] = {0};
  memcpy(vendor, resp + 8, 8);
  memcpy(product, resp + 16, 16);
  printf("INQUIRY OK — Vendor: [%.8s]  Product: [%.16s]\n", vendor, product);

  /* CSW lezen na INQUIRY */
  unsigned char csw_buf[13];
  libusb_bulk_transfer(h, ep_in, csw_buf, 13, &actual, 2000);
  return 0;
}

/* ── Main ────────────────────────────────────────────────────── */
int main(int argc, char *argv[]) {
  if (argc < 9) {
    printf("Usage: %s <vid> <pid> <iface> <ep_out> <ep_in>"
           " <start_lba> <size_mb> <runs> [variant]\n",
           argv[0]);
    printf("Voorbeeld: %s 0x1234 0x5678 0 0x02 0x81 2048 64 10"
           " libusb_native\n",
           argv[0]);
    return 1;
  }

  uint16_t vid = (uint16_t)strtol(argv[1], NULL, 16);
  uint16_t pid = (uint16_t)strtol(argv[2], NULL, 16);
  int iface = atoi(argv[3]);
  uint8_t ep_out = (uint8_t)strtol(argv[4], NULL, 16);
  uint8_t ep_in = (uint8_t)strtol(argv[5], NULL, 16);
  uint32_t start_lba = (uint32_t)strtol(argv[6], NULL, 0);
  size_t size_mb = (size_t)atoi(argv[7]);
  int runs = atoi(argv[8]);
  const char *variant = (argc >= 10) ? argv[9] : "libusb_native";

  if (runs > MAX_RUNS)
    runs = MAX_RUNS;

  size_t total_blocks = (size_mb * 1024 * 1024) / BLOCK_SIZE;
  size_t chunk_bytes = CHUNK_BLOCKS * BLOCK_SIZE;
  unsigned char *buf = malloc(chunk_bytes);
  if (!buf) {
    fprintf(stderr, "malloc mislukt\n");
    return 1;
  }
  memset(buf, 0xAA, chunk_bytes);

  double write_mbps[MAX_RUNS];
  double read_mbps[MAX_RUNS];
  int write_valid[MAX_RUNS];
  int read_valid[MAX_RUNS];
  memset(write_valid, 0, sizeof(write_valid));
  memset(read_valid, 0, sizeof(read_valid));

  /* ── libusb init ─────────────────────────────────────────── */
  libusb_context *ctx = NULL;
  libusb_device_handle *handle = NULL;
  libusb_init(&ctx);

  handle = libusb_open_device_with_vid_pid(ctx, vid, pid);
  if (!handle) {
    fprintf(stderr, "Device niet gevonden (VID=0x%04X PID=0x%04X)\n", vid, pid);
    libusb_exit(ctx);
    return 1;
  }

  /* ── Kernel driver detachen (macOS / Linux) ──────────────── */
  if (libusb_kernel_driver_active(handle, iface) == 1) {
    int r = libusb_detach_kernel_driver(handle, iface);
    if (r < 0) {
      fprintf(stderr, "Kon kernel driver niet detachen: %s\n",
              libusb_strerror(r));
      libusb_close(handle);
      libusb_exit(ctx);
      return 1;
    }
    printf("Kernel driver gedetacht van interface %d\n", iface);
  }

  int cr = libusb_claim_interface(handle, iface);
  if (cr < 0) {
    fprintf(stderr, "Claim interface mislukt: %s\n", libusb_strerror(cr));
    libusb_close(handle);
    libusb_exit(ctx);
    return 1;
  }
  printf("Interface %d geclaimd\n", iface);

  /* ── INQUIRY diagnose ────────────────────────────────────── */
  if (run_inquiry(handle, ep_out, ep_in) < 0) {
    fprintf(stderr, "INQUIRY mislukt — controleer ep_out/ep_in en of "
                    "de stick correct is vrijgegeven door het OS\n");
    libusb_release_interface(handle, iface);
    libusb_close(handle);
    libusb_exit(ctx);
    return 1;
  }

  printf("MSC Throughput — %zu MB, %d runs [%s]  start_lba=%u\n\n", size_mb,
         runs, variant, start_lba);

  /* ── Meetlus ─────────────────────────────────────────────── */
  for (int run = 0; run < runs; run++) {
    uint32_t tag = (uint32_t)(run * 2000 + 1);
    uint32_t lba = start_lba;
    size_t done = 0;
    int ok = 1;

    /* WRITE */
    double t0 = get_time_ms();
    while (done < total_blocks) {
      uint16_t n = (uint16_t)((total_blocks - done < CHUNK_BLOCKS)
                                  ? (total_blocks - done)
                                  : CHUNK_BLOCKS);
      CBW cbw;
      build_write10(&cbw, tag++, lba, n);
      if (msc_transfer(handle, ep_out, ep_in, &cbw, buf, (int)(n * BLOCK_SIZE),
                       0) < 0) {
        ok = 0;
        break;
      }
      lba += n;
      done += n;
    }
    double elapsed_w = get_time_ms() - t0;

    if (!ok) {
      fprintf(stderr, "Run %2d WRITE: transfer error — run overgeslagen\n",
              run + 1);
    } else if (elapsed_w < MIN_ELAPSED_MS) {
      fprintf(stderr,
              "Run %2d WRITE: elapsed %.4f ms te klein — "
              "transfer niet echt uitgevoerd\n",
              run + 1, elapsed_w);
    } else {
      write_mbps[run] = (size_mb * 1000.0) / elapsed_w;
      write_valid[run] = 1;
    }

    /* READ */
    lba = start_lba;
    done = 0;
    ok = 1;
    double t1 = get_time_ms();
    while (done < total_blocks) {
      uint16_t n = (uint16_t)((total_blocks - done < CHUNK_BLOCKS)
                                  ? (total_blocks - done)
                                  : CHUNK_BLOCKS);
      CBW cbw;
      build_read10(&cbw, tag++, lba, n);
      if (msc_transfer(handle, ep_out, ep_in, &cbw, buf, (int)(n * BLOCK_SIZE),
                       1) < 0) {
        ok = 0;
        break;
      }
      lba += n;
      done += n;
    }
    double elapsed_r = get_time_ms() - t1;

    if (!ok) {
      fprintf(stderr, "Run %2d READ:  transfer error — run overgeslagen\n",
              run + 1);
    } else if (elapsed_r < MIN_ELAPSED_MS) {
      fprintf(stderr,
              "Run %2d READ:  elapsed %.4f ms te klein — "
              "transfer niet echt uitgevoerd\n",
              run + 1, elapsed_r);
    } else {
      read_mbps[run] = (size_mb * 1000.0) / elapsed_r;
      read_valid[run] = 1;
    }

    /* Rapporteer */
    if (write_valid[run] && read_valid[run]) {
      printf("Run %2d — Write: %8.3f MB/s  Read: %8.3f MB/s\n", run + 1,
             write_mbps[run], read_mbps[run]);
    } else {
      printf("Run %2d — (een of beide richtingen ongeldig)\n", run + 1);
    }
  }

  /* ── CSV-export ──────────────────────────────────────────── */
  mkdir("results", 0755);
  char fname[128];
  snprintf(fname, sizeof(fname), "results/throughput_results_%s_%dMB.csv", variant, size_mb);
  FILE *f = fopen(fname, "w");
  if (!f) {
    fprintf(stderr, "Kon %s niet openen voor schrijven\n", fname);
  } else {
    fprintf(f, "run,direction,mb_per_sec\n");
    for (int i = 0; i < runs; i++) {
      if (write_valid[i])
        fprintf(f, "%d,write,%.6f\n", i + 1, write_mbps[i]);
      if (read_valid[i])
        fprintf(f, "%d,read,%.6f\n", i + 1, read_mbps[i]);
    }
    fclose(f);
    printf("\nCSV opgeslagen: %s\n", fname);
  }

  free(buf);
  libusb_release_interface(handle, iface);
  libusb_close(handle);
  libusb_exit(ctx);
  return 0;
}