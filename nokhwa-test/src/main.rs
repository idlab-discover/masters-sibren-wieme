use nokhwa::pixel_format::RgbFormat;
use nokhwa::utils::{
    ApiBackend, CameraFormat, CameraIndex, FrameFormat, RequestedFormat, RequestedFormatType,
    Resolution,
};
use nokhwa::Camera;
use std::io::{self, Write};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;

fn prompt(msg: &str) -> String {
    print!("{}", msg);
    io::stdout().flush().unwrap();
    let mut input = String::new();
    io::stdin().read_line(&mut input).expect("stdin error");
    input.trim().to_string()
}

/// Attempt to capture and save a frame. Returns the filename on success.
fn capture_and_save(camera: &mut Camera, index: usize) -> Result<String, String> {
    let frame = camera
        .frame()
        .map_err(|e| format!("frame() failed: {e}"))?;

    let w = frame.resolution().width();
    let h = frame.resolution().height();
    println!(
        " Raw frame: {}x{}, format: {:?}",
        w,
        h,
        frame.source_frame_format()
    );

    let decoded = frame
        .decode_image::<RgbFormat>()
        .map_err(|e| format!("decode failed: {e}"))?;

    let path = format!("frame_{index}.png");
    decoded
        .save_with_format(&path, image::ImageFormat::Png)
        .map_err(|e| format!("save failed: {e}"))?;

    Ok(path)
}

/// Open a camera with the system default format and open the stream.
/// FIX 3: Retourneert Result ipv te panicken met .expect() → geen abort mogelijk.
fn open_default_camera(index: &CameraIndex) -> Result<Camera, String> {
    let request = RequestedFormat::new::<RgbFormat>(RequestedFormatType::None);
    let mut cam = Camera::new(index.clone(), request)
        .map_err(|e| format!("Camera::new mislukt: {e}"))?;

    std::thread::sleep(Duration::from_millis(500));

    cam.open_stream()
        .map_err(|e| format!("open_stream mislukt: {e}"))?;

    Ok(cam)
}

fn run_simple_mode(index: &CameraIndex, cam_name: &str) {
    println!("\n── Simpele modus ──");
    println!("Camera: {cam_name}");

    // Define formats to try in order of preference
    let formats_to_try = vec![
        ("MJPEG 1920x1080@30", CameraFormat::new(Resolution::new(1920, 1080), FrameFormat::MJPEG, 30)),
        ("MJPEG 1280x720@30", CameraFormat::new(Resolution::new(1280, 720), FrameFormat::MJPEG, 30)),
        ("MJPEG 640x480@30", CameraFormat::new(Resolution::new(640, 480), FrameFormat::MJPEG, 30)),
        ("YUYV 640x480@30", CameraFormat::new(Resolution::new(640, 480), FrameFormat::YUYV, 30)),
    ];

    let mut camera_result = None;

    for (name, format) in formats_to_try {
        println!("Proberen: {}", name);
        let request = RequestedFormat::new::<RgbFormat>(RequestedFormatType::Exact(format));
        
        match Camera::new(index.clone(), request) {
            Ok(mut cam) => {
                if let Ok(_) = cam.open_stream() {
                    println!(" ✓ Succes: {}", name);
                    camera_result = Some(cam);
                    break;
                }
                println!(" ✗ Stream openen mislukt voor {}", name);
            }
            Err(e) => {
                println!(" ✗ Poging mislukt: {} - {:?}", name, e);
            }
        }
    }

    let mut camera = match camera_result {
        Some(c) => c,
        None => {
            println!("Geen expliciet formaat gelukt — gebruik systeemstandaard.");
            let request = RequestedFormat::new::<RgbFormat>(RequestedFormatType::None);
            match Camera::new(index.clone(), request) {
                Ok(mut c) => {
                    c.open_stream().expect("Zelfs systeemstandaard mislukt");
                    c
                }
                Err(e) => {
                    eprintln!("Kon camera niet openen: {e}");
                    return;
                }
            }
        }
    };

    println!("Actief formaat: {}", camera.camera_format());
    println!("Camera warm-up (5 frames overslaan)...");
    
    // Warm-up logic (Fix from guide)
    for _ in 0..5 {
        let _ = camera.frame();
    }

    const FRAME_COUNT: usize = 5;
    let mut success = 0;

    for i in 0..FRAME_COUNT {
        print!("Frame {i}: ");
        match capture_and_save(&mut camera, i) {
            Ok(path) => {
                println!(" ✓ Opgeslagen als '{path}'");
                success += 1;
            }
            Err(e) => println!(" ✗ {e}"),
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    println!("\n=== Klaar: {success}/{FRAME_COUNT} frames succesvol vastgelegd ===");

    if let Err(e) = camera.stop_stream() {
        eprintln!("Waarschuwing: stop_stream gaf een fout: {e}");
    }
}

fn main() {
    println!("=== Nokhwa Webcam Tester (AVFoundation) ===\n");

    // ── 0. Camera-toestemming aanvragen ──────────────────────────────────────
    let permission_granted = Arc::new(AtomicBool::new(false));
    let flag = permission_granted.clone();
    nokhwa::nokhwa_initialize(move |granted| {
        flag.store(granted, Ordering::SeqCst);
    });

    let deadline = std::time::Instant::now() + Duration::from_secs(30);
    loop {
        if permission_granted.load(Ordering::SeqCst) {
            println!("✓ Camera-toegang verleend.");
            break;
        }
        if std::time::Instant::now() > deadline {
            eprintln!("✗ Camera-toegang geweigerd of time-out.");
            eprintln!("  Controleer: Systeeminstellingen → Privacy & Beveiliging → Camera");
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    // ── 1. Camera's oplijsten ────────────────────────────────────────────────
    let cameras = nokhwa::query(ApiBackend::AVFoundation).expect("Kon camera's niet opvragen");

    if cameras.is_empty() {
        eprintln!("Geen camera's gevonden.");
        return;
    }

    println!("Gevonden camera's:");
    for (i, cam) in cameras.iter().enumerate() {
        println!("  [{i}] {}", cam.human_name());
    }

    let cam_choice: usize = loop {
        let s = prompt("\nKies camera index: ");
        match s.parse() {
            Ok(n) if n < cameras.len() => break n,
            _ => println!("Ongeldige keuze, probeer opnieuw."),
        }
    };

    let index = CameraIndex::Index(cam_choice as u32);
    let cam_name = cameras[cam_choice].human_name();

    // ── 2. Modus kiezen ──────────────────────────────────────────────────────
    println!("\nWelke modus wil je gebruiken?");
    println!("  [1] Simpel       — hoogste framerate automatisch, direct opnemen");
    println!("  [2] Geavanceerd  — formaat handmatig kiezen met fallback-logica");

    let mode: u8 = loop {
        let s = prompt("\nKeuze (1 of 2): ");
        match s.as_str() {
            "1" => break 1,
            "2" => break 2,
            _ => println!("Voer 1 of 2 in."),
        }
    };

    if mode == 1 {
        run_simple_mode(&index, &cam_name);
        return;
    }

    // ── Geavanceerde modus ───────────────────────────────────────────────────

    // ── 3. Camera-formaten opvragen ──────────────────────────────────────────
    println!("\nCamera-formaten opvragen...");

    // FIX 2: Bijhouden of de driver de formaten bevestigd heeft.
    let driver_gave_formats: bool;
    let formats: Vec<CameraFormat> = {
        let request = RequestedFormat::new::<RgbFormat>(RequestedFormatType::None);
        match Camera::new(index.clone(), request) {
            Ok(mut probe_cam) => match probe_cam.compatible_camera_formats() {
                Ok(f) if !f.is_empty() => {
                    println!("Driver meldde {} formaten.", f.len());
                    driver_gave_formats = true;
                    f
                }
                _ => {
                    println!("Driver gaf geen formaten terug — gebruik fallback-lijst.");
                    driver_gave_formats = false;
                    Vec::new()
                }
            },
            Err(e) => {
                println!("Probe camera aanmaken mislukt: {e} — gebruik fallback-lijst.");
                driver_gave_formats = false;
                Vec::new()
            }
        }
    };

    // FIX 1: Geef AVFoundation tijd om de probe-sessie volledig vrij te geven
    std::thread::sleep(Duration::from_millis(500));

    // Fallback-lijst: Prioriteer MJPEG (meest stabiel op Mac nokhwa 0.10)
    let formats = if formats.is_empty() {
        println!("Fallback formaten worden gebruikt (MJPEG geprioriteerd):\n");
        vec![
            CameraFormat::new(Resolution::new(1280, 720), FrameFormat::MJPEG, 30),
            CameraFormat::new(Resolution::new(640, 480), FrameFormat::MJPEG, 30),
            CameraFormat::new(Resolution::new(1920, 1080), FrameFormat::MJPEG, 30),
            // YUYV/NV12 enkel als allerlaatste fallback
            CameraFormat::new(Resolution::new(640, 480), FrameFormat::YUYV, 30),
            CameraFormat::new(Resolution::new(1280, 720), FrameFormat::YUYV, 30),
        ]
    } else {
        // Zorg dat MJPEG bovenaan staat als het aanwezig is
        let mut f = formats;
        f.sort_by_key(|fmt| if fmt.format() == FrameFormat::MJPEG { 0 } else { 1 });
        f
    };

    println!("Beschikbare formaten:");
    for (i, fmt) in formats.iter().enumerate() {
        println!("  [{i}] {fmt}");
    }

    // ── 4. Format kiezen ─────────────────────────────────────────────────────
    let fmt_choice: Option<usize> = {
        let s = prompt("\nKies format index (of Enter voor beste MJPEG): ");
        if s.is_empty() {
            None
        } else {
            match s.parse::<usize>() {
                Ok(n) if n < formats.len() => Some(n),
                _ => {
                    println!("Ongeldige keuze — standaard wordt gebruikt.");
                    None
                }
            }
        }
    };

    // ── 5. Camera openen met retry-logica ────────────────────────────────────
    let mut camera: Camera = match fmt_choice {
        Some(idx) => {
            let selected = formats[idx];
            println!("\nProbeer formaat: {selected}");

            // FIX 2 (vervolg): Exact enkel als driver dit formaat bevestigde.
            // Anders None → AVFoundation kiest zelf → geen NSException.
            if !driver_gave_formats {
                println!(
                    "  (Fallback-formaat: openen met None om NSException-crash te vermijden)"
                );
            }

            let mut result: Result<Camera, String> = Err(String::from("Niet geprobeerd"));
            for attempt in 1u64..=3 {
                std::thread::sleep(Duration::from_millis(300 * attempt));

                let request_type = RequestedFormatType::Exact(selected);
                let request = RequestedFormat::new::<RgbFormat>(request_type);

                match Camera::new(index.clone(), request)
                    .map_err(|e| format!("Camera::new failed: {e}"))
                {
                    Ok(mut cam) => {
                        match cam
                            .open_stream()
                            .map_err(|e| format!("open_stream failed: {e}"))
                        {
                            Ok(_) => {
                                println!("  ✓ Stream geopend (poging {attempt})");
                                result = Ok(cam);
                                break;
                            }
                            Err(e) => {
                                println!("  Poging {attempt} mislukt: {e}");
                                result = Err(e);
                            }
                        }
                    }
                    Err(e) => {
                        println!("  Poging {attempt} mislukt: {e}");
                        result = Err(e);
                    }
                }
            }

            match result {
                Ok(cam) => cam,
                Err(e) => {
                    println!("Gewenst formaat mislukt: {e}");
                    println!("Terugvallen op standaard formaat...");
                    match open_default_camera(&index) {
                        Ok(cam) => cam,
                        Err(e) => {
                            eprintln!("Kon camera niet openen: {e}");
                            return;
                        }
                    }
                }
            }
        }
        None => {
            println!("\nStandaard formaat openen...");
            match open_default_camera(&index) {
                Ok(cam) => cam,
                Err(e) => {
                    eprintln!("Kon camera niet openen: {e}");
                    return;
                }
            }
        }
    };

    println!("\nActief formaat: {}", camera.camera_format());

    // ── 6. Warm-up ───────────────────────────────────────────────────────────
    println!("Camera warm-up (2 seconden)...");
    std::thread::sleep(Duration::from_secs(2));

    // ── 7. Frames vastleggen ─────────────────────────────────────────────────
    const FRAME_COUNT: usize = 5;
    let mut success = 0;

    for i in 0..FRAME_COUNT {
        print!("Frame {i}: ");
        match capture_and_save(&mut camera, i) {
            Ok(path) => {
                println!("✓ opgeslagen als '{path}'");
                success += 1;
            }
            Err(e) => println!("✗ {e}"),
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    println!("\n=== Klaar: {success}/{FRAME_COUNT} frames succesvol vastgelegd ===");

    if let Err(e) = camera.stop_stream() {
        eprintln!("Waarschuwing: stop_stream gaf een fout: {e}");
    }
}
