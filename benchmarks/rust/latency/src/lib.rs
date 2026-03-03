use rusb::{Context, UsbContext};
use std::time::{Duration, Instant};
use std::env;
use std::fs::{self, File};
use std::io::{BufWriter, Write};

const DEFAULT_TIMEOUT: Duration = Duration::from_millis(1000);
const ITERATIONS: u32 = 10000;
const WARMUP_ITERATIONS: u32 = 1000;

fn run_latency_test() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 7 {
        eprintln!("Usage: {} <vid> <pid> <interface> <ep_out> <ep_in> <size_bytes> [iterations] [variant]", args[0]);
        return Err("Niet genoeg argumenten.".into());
    }

    let vid        = u16::from_str_radix(args[1].trim_start_matches("0x"), 16)?;
    let pid        = u16::from_str_radix(args[2].trim_start_matches("0x"), 16)?;
    let interface  = args[3].parse::<u8>()?;
    let ep_out     = u8::from_str_radix(args[4].trim_start_matches("0x"), 16)?;
    let ep_in      = u8::from_str_radix(args[5].trim_start_matches("0x"), 16)?;
    let size_bytes = args[6].parse::<usize>()?;
    let iterations = if args.len() > 7 { args[7].parse().unwrap_or(ITERATIONS) } else { ITERATIONS };
    let variant    = if args.len() > 8 { args[8].clone() } else { "rusb_native".to_string() };

    if size_bytes == 0 || size_bytes % 64 != 0 {
        return Err(format!(
            "Fout: size_bytes ({}) moet een veelvoud van 64 zijn \
             (USB 2.0 bulk max-packet-size).\nGeldige waarden: 64, 128, 192, 256, 512, 1024, ...",
            size_bytes
        ).into());
    }

    let context = Context::new()?;
    let mut handle = context
        .open_device_with_vid_pid(vid, pid)
        .ok_or("Kon het USB-apparaat niet openen.")?;

    let _ = handle.set_active_configuration(1);
    handle.claim_interface(interface)?;

    // Dynamische buffers
    let ping = vec![0xABu8; size_bytes];
    let mut pong = vec![0u8; size_bytes];

    let mut rtts: Vec<Duration> = Vec::with_capacity(iterations as usize);
    let mut total_rtt = Duration::ZERO;
    let mut min_rtt   = Duration::MAX;
    let mut max_rtt   = Duration::ZERO;

    // --- Warmup ---
    println!("Starting Warmup ({} iterations, {} bytes)...", WARMUP_ITERATIONS, size_bytes);
    for i in 0..WARMUP_ITERATIONS {
        handle.write_bulk(ep_out, &ping, DEFAULT_TIMEOUT)
            .map_err(|e| format!("Bulk Out Error {:?} at warmup {}", e, i))?;
        handle.read_bulk(ep_in, &mut pong, DEFAULT_TIMEOUT)
            .map_err(|e| format!("Bulk In Error {:?} at warmup {}", e, i))?;
    }

    // --- Meting ---
    println!("Starting Measurement ({} iterations, {} bytes)...", iterations, size_bytes);
    for i in 0..iterations {
        let start = Instant::now();

        handle.write_bulk(ep_out, &ping, DEFAULT_TIMEOUT)
            .map_err(|e| format!("Bulk Out Error {:?} at iteration {}", e, i))?;
        handle.read_bulk(ep_in, &mut pong, DEFAULT_TIMEOUT)
            .map_err(|e| format!("Bulk In Error {:?} at iteration {}", e, i))?;

        let rtt = start.elapsed();
        rtts.push(rtt);
        total_rtt += rtt;
        min_rtt = min_rtt.min(rtt);
        max_rtt = max_rtt.max(rtt);
    }

    // --- Statistieken ---
    let n = rtts.len() as f64;
    println!("\n--- Statistics ({} samples, {} bytes) ---", rtts.len(), size_bytes);
    println!("Average RTT: {:.3} ms", (total_rtt.as_secs_f64() * 1000.0) / n);
    println!("Min RTT:     {:.3} ms", min_rtt.as_secs_f64() * 1000.0);
    println!("Max RTT:     {:.3} ms", max_rtt.as_secs_f64() * 1000.0);

    // --- CSV ---
    fs::create_dir_all("results")?;
    let csv_path = format!("results/rtt_results_latency_{}_{}.csv", variant, size_bytes);
    let file = File::create(&csv_path)?;
    let mut writer = BufWriter::new(file);
    writeln!(writer, "iteration,size_bytes,rtt_ms")?;
    for (i, rtt) in rtts.iter().enumerate() {
        writeln!(writer, "{},{},{:.6}", i + 1, size_bytes, rtt.as_secs_f64() * 1000.0)?;
    }
    writer.flush()?;
    println!("Results written to {}", csv_path);

    Ok(())
}

#[unsafe(no_mangle)]
pub extern "C" fn exports_wasi_cli_run_run() -> bool {
    match run_latency_test() {
        Ok(_) => true,
        Err(e) => { eprintln!("Error: {}", e); false }
    }
}
