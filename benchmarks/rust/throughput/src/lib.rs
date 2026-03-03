use rusb::{Context, DeviceHandle, UsbContext};
use std::env;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::time::{Duration, Instant};

const BLOCK_SIZE: usize = 512;
const CHUNK_BLOCKS: usize = 128;
const TIMEOUT: Duration = Duration::from_secs(5);
const MIN_ELAPSED_SECS: f64 = 0.001; // 1 ms minimum

// ── CBW builder ──────────────────────────────────────────────────
fn build_cbw(tag: u32, lba: u32, num_blocks: u16, is_read: bool) -> [u8; 31] {
    let transfer_len = (num_blocks as u32) * (BLOCK_SIZE as u32);
    let opcode: u8 = if is_read { 0x28 } else { 0x2A };
    let flags: u8  = if is_read { 0x80 } else { 0x00 };

    let mut cdb = [0u8; 16];
    cdb[0] = opcode;
    cdb[2] = ((lba >> 24) & 0xFF) as u8;
    cdb[3] = ((lba >> 16) & 0xFF) as u8;
    cdb[4] = ((lba >>  8) & 0xFF) as u8;
    cdb[5] = ( lba        & 0xFF) as u8;
    cdb[7] = ((num_blocks >> 8) & 0xFF) as u8;
    cdb[8] = ( num_blocks       & 0xFF) as u8;

    let mut cbw = [0u8; 31];
    cbw[0..4].copy_from_slice(&0x43425355u32.to_le_bytes());
    cbw[4..8].copy_from_slice(&tag.to_le_bytes());
    cbw[8..12].copy_from_slice(&transfer_len.to_le_bytes());
    cbw[12] = flags;
    cbw[13] = 0;    // LUN
    cbw[14] = 10;   // CDB length
    cbw[15..31].copy_from_slice(&cdb[0..16]);
    cbw
}

// ── CSW validatie ────────────────────────────────────────────────
fn check_csw<T: UsbContext>(
    h: &DeviceHandle<T>,
    ep_in: u8,
    expected_tag: u32,
) -> Result<(), String> {
    let mut csw = [0u8; 13];
    h.read_bulk(ep_in, &mut csw, TIMEOUT)
        .map_err(|e| format!("CSW read error: {e}"))?;

    let sig    = u32::from_le_bytes(csw[0..4].try_into().unwrap());
    let tag    = u32::from_le_bytes(csw[4..8].try_into().unwrap());
    let status = csw[12];

    if sig != 0x53425355 {
        return Err(format!("Ongeldige CSW signature: 0x{sig:08X}"));
    }
    if tag != expected_tag {
        return Err(format!("CSW tag mismatch: ontvangen {tag}, verwacht {expected_tag}"));
    }
    if status != 0 {
        return Err(format!("CSW status fout: {status}"));
    }
    Ok(())
}

// ── MSC write via SCSI WRITE(10) ─────────────────────────────────
fn msc_write<T: UsbContext>(
    h: &DeviceHandle<T>,
    ep_out: u8,
    ep_in: u8,
    tag: u32,
    lba: u32,
    data: &[u8],
) -> Result<(), String> {
    let num_blocks = (data.len() / BLOCK_SIZE) as u16;
    let cbw = build_cbw(tag, lba, num_blocks, false);

    let sent = h.write_bulk(ep_out, &cbw, TIMEOUT)
        .map_err(|e| format!("CBW write error: {e}"))?;
    if sent != 31 {
        return Err(format!("CBW short write: {sent}/31 bytes"));
    }
    h.write_bulk(ep_out, data, TIMEOUT)
        .map_err(|e| format!("Data write error: {e}"))?;
    check_csw(h, ep_in, tag)
}

// ── MSC read via SCSI READ(10) ───────────────────────────────────
fn msc_read<T: UsbContext>(
    h: &DeviceHandle<T>,
    ep_out: u8,
    ep_in: u8,
    tag: u32,
    lba: u32,
    buf: &mut [u8],
) -> Result<(), String> {
    let num_blocks = (buf.len() / BLOCK_SIZE) as u16;
    let cbw = build_cbw(tag, lba, num_blocks, true);

    let sent = h.write_bulk(ep_out, &cbw, TIMEOUT)
        .map_err(|e| format!("CBW write error: {e}"))?;
    if sent != 31 {
        return Err(format!("CBW short write: {sent}/31 bytes"));
    }
    h.read_bulk(ep_in, buf, TIMEOUT)
        .map_err(|e| format!("Data read error: {e}"))?;
    check_csw(h, ep_in, tag)
}

// ── INQUIRY diagnose ─────────────────────────────────────────────
fn run_inquiry<T: UsbContext>(
    h: &DeviceHandle<T>,
    ep_out: u8,
    ep_in: u8,
) -> Result<(), String> {
    let mut cbw = [0u8; 31];
    cbw[0..4].copy_from_slice(&0x43425355u32.to_le_bytes());
    cbw[4..8].copy_from_slice(&0xFFu32.to_le_bytes());   // tag
    cbw[8..12].copy_from_slice(&36u32.to_le_bytes());    // transfer length
    cbw[12] = 0x80;  // IN
    cbw[14] = 6;     // CDB length
    cbw[15] = 0x12;  // INQUIRY opcode
    cbw[19] = 0x24;  // allocation length = 36

    let sent = h.write_bulk(ep_out, &cbw, TIMEOUT)
        .map_err(|e| format!("INQUIRY CBW error: {e}"))?;
    if sent != 31 {
        return Err(format!("INQUIRY CBW short write: {sent}/31"));
    }

    let mut resp = [0u8; 36];
    h.read_bulk(ep_in, &mut resp, TIMEOUT)
        .map_err(|e| format!("INQUIRY data error: {e}"))?;

    let vendor  = std::str::from_utf8(&resp[8..16]).unwrap_or("?").trim();
    let product = std::str::from_utf8(&resp[16..32]).unwrap_or("?").trim();
    println!("INQUIRY OK — Vendor: [{vendor}]  Product: [{product}]");

    // CSW uitlezen na INQUIRY
    let mut csw = [0u8; 13];
    let _ = h.read_bulk(ep_in, &mut csw, TIMEOUT);
    Ok(())
}

// ── Benchmark kern ───────────────────────────────────────────────
pub fn run_benchmark(args: &[String]) -> bool {
    if args.len() < 9 {
        eprintln!(
            "Usage: {} <vid> <pid> <iface> <ep_out> <ep_in> \
             <start_lba> <size_mb> <runs> [variant]",
            args[0]
        );
        eprintln!(
            "Voorbeeld: {} 0x1234 0x5678 0 0x02 0x81 2048 64 10 rusb_native",
            args[0]
        );
        return false;
    }

    let vid       = u16::from_str_radix(args[1].trim_start_matches("0x"), 16).unwrap();
    let pid       = u16::from_str_radix(args[2].trim_start_matches("0x"), 16).unwrap();
    let iface     = args[3].parse::<u8>().expect("Ongeldig interface nummer");
    let ep_out    = u8::from_str_radix(args[4].trim_start_matches("0x"), 16).unwrap();
    let ep_in     = u8::from_str_radix(args[5].trim_start_matches("0x"), 16).unwrap();
    let start_lba = args[6].parse::<u32>().unwrap_or(0);
    let size_mb   = args[7].parse::<usize>().unwrap_or(1);
    let runs      = args[8].parse::<usize>().unwrap_or(10);
    let variant   = args.get(9).map(|s| s.as_str()).unwrap_or("rusb_native");

    let total_blocks = (size_mb * 1024 * 1024) / BLOCK_SIZE;
    let chunk_bytes  = CHUNK_BLOCKS * BLOCK_SIZE;
    let write_data   = vec![0xAAu8; chunk_bytes];
    let mut read_buf = vec![0u8; chunk_bytes];

    // Resultaten buiten de meetlus
    let mut write_results: Vec<Option<f64>> = vec![None; runs];
    let mut read_results:  Vec<Option<f64>> = vec![None; runs];

    // ── rusb init ────────────────────────────────────────────────
    let context = Context::new().expect("Kon libusb context niet aanmaken");
    let mut handle = context
        .open_device_with_vid_pid(vid, pid)
        .expect("Device niet gevonden");

    // Kernel driver detachen indien actief
    match handle.kernel_driver_active(iface) {
        Ok(true) => {
            handle.detach_kernel_driver(iface)
                .expect("Kon kernel driver niet detachen");
            println!("Kernel driver gedetacht van interface {iface}");
        }
        Ok(false) => {}
        Err(e) => eprintln!("kernel_driver_active error: {e}"),
    }

    handle.claim_interface(iface)
        .expect("Claim interface mislukt");
    println!("Interface {iface} geclaimd");

    // ── INQUIRY diagnose ─────────────────────────────────────────
    if let Err(e) = run_inquiry(&handle, ep_out, ep_in) {
        eprintln!("INQUIRY mislukt: {e}");
        eprintln!("Controleer ep_out/ep_in en of de stick vrijgegeven is door het OS.");
        handle.release_interface(iface).ok();
        return false;
    }

    println!(
        "MSC Throughput — {size_mb} MB, {runs} runs [{variant}]  start_lba={start_lba}\n"
    );

    // ── Meetlus ──────────────────────────────────────────────────
    for run in 0..runs {
        let base_tag = (run as u32) * 2000 + 1;
        let mut tag = base_tag;

        // WRITE
        let mut lba = start_lba;
        let mut done = 0usize;
        let mut write_ok = true;

        let t0 = Instant::now();
        while done < total_blocks {
            let n = (total_blocks - done).min(CHUNK_BLOCKS);
            if let Err(e) = msc_write(
                &handle, ep_out, ep_in, tag, lba,
                &write_data[..n * BLOCK_SIZE],
            ) {
                eprintln!("Run {:2} WRITE error bij LBA {lba}: {e}", run + 1);
                write_ok = false;
                break;
            }
            lba += n as u32;
            done += n;
            tag += 1;
        }
        let elapsed_w = t0.elapsed().as_secs_f64();

        if write_ok {
            if elapsed_w < MIN_ELAPSED_SECS {
                eprintln!(
                    "Run {:2} WRITE: elapsed {:.4} s te klein — transfer niet echt uitgevoerd",
                    run + 1, elapsed_w
                );
            } else {
                write_results[run] = Some(size_mb as f64 / elapsed_w);
            }
        }

        // READ
        lba = start_lba;
        done = 0;
        let mut read_ok = true;

        let t1 = Instant::now();
        while done < total_blocks {
            let n = (total_blocks - done).min(CHUNK_BLOCKS);
            if let Err(e) = msc_read(
                &handle, ep_out, ep_in, tag, lba,
                &mut read_buf[..n * BLOCK_SIZE],
            ) {
                eprintln!("Run {:2} READ error bij LBA {lba}: {e}", run + 1);
                read_ok = false;
                break;
            }
            lba += n as u32;
            done += n;
            tag += 1;
        }
        let elapsed_r = t1.elapsed().as_secs_f64();

        if read_ok {
            if elapsed_r < MIN_ELAPSED_SECS {
                eprintln!(
                    "Run {:2} READ:  elapsed {:.4} s te klein — transfer niet echt uitgevoerd",
                    run + 1, elapsed_r
                );
            } else {
                read_results[run] = Some(size_mb as f64 / elapsed_r);
            }
        }

        // Rapporteer
        match (write_results[run], read_results[run]) {
            (Some(w), Some(r)) =>
                println!("Run {:2} — Write: {:8.3} MB/s  Read: {:8.3} MB/s",
                         run + 1, w, r),
            _ =>
                println!("Run {:2} — (een of beide richtingen ongeldig)", run + 1),
        }
    }

    // ── CSV-export ───────────────────────────────────────────────
    fs::create_dir_all("results").expect("Kon results/ map niet aanmaken");
    let fname = format!("results/throughput_results_{variant}_{size_mb}MB.csv");
    let file = File::create(&fname).expect("Kon CSV niet aanmaken");
    let mut writer = BufWriter::new(file);
    writeln!(writer, "run,direction,mb_per_sec").unwrap();

    for (i, (w, r)) in write_results.iter().zip(read_results.iter()).enumerate() {
        if let Some(mbps) = w {
            writeln!(writer, "{},write,{:.6}", i + 1, mbps).unwrap();
        }
        if let Some(mbps) = r {
            writeln!(writer, "{},read,{:.6}", i + 1, mbps).unwrap();
        }
    }
    println!("\nCSV opgeslagen: {fname}");

    handle.release_interface(iface).ok();
    true
}

// ── Native entry point ───────────────────────────────────────────
fn main() {
    let args: Vec<String> = env::args().collect();
    std::process::exit(if run_benchmark(&args) { 0 } else { 1 });
}

// ── WASI export ──────────────────────────────────────────────────
#[unsafe(no_mangle)]
pub extern "C" fn exports_wasi_cli_run_run() -> bool {
    let args: Vec<String> = env::args().collect();
    run_benchmark(&args)
}