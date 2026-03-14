use nokhwa::pixel_format::RgbFormat;
use nokhwa::utils::{ApiBackend, CameraIndex, RequestedFormat, RequestedFormatType, CameraFormat, Resolution, FrameFormat};
use nokhwa::Camera;

fn main() {
    println!("Nokhwa Test - Native macOS Backend");

    // Query for available cameras using AVFoundation backend
    let cameras = nokhwa::query(ApiBackend::AVFoundation).expect("Failed to query cameras");

    if cameras.is_empty() {
        println!("No cameras found!");
        return;
    }

    println!("Found {} cameras:", cameras.len());
    for (i, cam) in cameras.iter().enumerate() {
        println!("  {}: {}", i, cam.human_name());
    }

    println!("Enter the index of the camera you want to use:");
    let mut input = String::new();
    std::io::stdin().read_line(&mut input).expect("Failed to read line");
    let choice: usize = input.trim().parse().expect("Please enter a valid number");

    if choice >= cameras.len() {
        println!("Invalid camera index selected!");
        return;
    }

    // Use the selected camera
    let index = CameraIndex::Index(choice as u32);
    
    // Start with a safe format to get the ball rolling
    let initial_request = RequestedFormat::new::<RgbFormat>(RequestedFormatType::None);
    println!("Opening camera for discovery...");
    let mut camera = Camera::new(index.clone(), initial_request)
        .expect("Failed to open camera for discovery");

    println!("Detected camera: {}", camera.info().human_name());
    
    // CRITICAL: Query formats BEFORE opening the stream.
    // Some drivers (like Brio 100) might fail to report formats while streaming.
    let mut formats = match camera.compatible_camera_formats() {
        Ok(f) => {
            if f.is_empty() {
                println!("Library reported 0 compatible formats (even before stream open).");
            } else {
                println!("Library reported {} compatible formats.", f.len());
            }
            f
        }
        Err(e) => {
            println!("Failed to query compatible formats: {}", e);
            Vec::new()
        }
    };

    // If still empty, provide the guesses
    if formats.is_empty() {
        println!("Providing 'Guess' formats for macOS/AVFoundation (avoiding MJPEG due to driver crashes):");
        let guesses = [
            (1280, 720, 30, FrameFormat::YUYV),
            (640, 480, 30, FrameFormat::YUYV),
            (1920, 1080, 15, FrameFormat::YUYV), // Lower FPS for bandwidth
            (1920, 1080, 30, FrameFormat::YUYV),
            (1280, 720, 30, FrameFormat::NV12), // NV12 is native to macOS
            (1920, 1080, 30, FrameFormat::NV12),
        ];
        for (w, h, fps, f) in guesses {
            formats.push(CameraFormat::new(Resolution::new(w, h), f, fps));
        }
    }

    println!("Available/Guess formats:");
    for (i, format) in formats.iter().enumerate() {
        println!("  {}: {}", i, format);
    }

    println!("Enter the index of the format you want to use (or press enter for current/default):");
    let mut format_input = String::new();
    std::io::stdin().read_line(&mut format_input).expect("Failed to read line");
    let format_input = format_input.trim();

    if !format_input.is_empty() {
        if let Ok(choice_idx) = format_input.parse::<usize>() {
            if choice_idx < formats.len() {
                let selected_format = formats[choice_idx];
                println!("Switching to: {} (recreating camera...)", selected_format);
                
                // Drop the discovery instance and wait a bit
                drop(camera);
                std::thread::sleep(std::time::Duration::from_millis(500));

                // Create a FRESH camera with the EXACT format
                let new_request = RequestedFormat::new::<RgbFormat>(RequestedFormatType::Exact(selected_format));
                match Camera::new(index.clone(), new_request) {
                    Ok(mut new_cam) => {
                        println!("  New camera instance created.");
                        match new_cam.open_stream() {
                            Ok(_) => {
                                println!("  Stream opened successfully!");
                                camera = new_cam;
                            }
                            Err(e) => {
                                println!("  Failed to open stream: {}. Reverting...", e);
                                std::thread::sleep(std::time::Duration::from_millis(500));
                                camera = Camera::new(index.clone(), RequestedFormat::new::<RgbFormat>(RequestedFormatType::None))
                                    .expect("Failed to revert camera");
                                camera.open_stream().expect("Failed to open default stream");
                            }
                        }
                    }
                    Err(e) => {
                        println!("  Failed to recreate camera: {}. Reverting...", e);
                        std::thread::sleep(std::time::Duration::from_millis(500));
                        camera = Camera::new(index.clone(), RequestedFormat::new::<RgbFormat>(RequestedFormatType::None))
                            .expect("Failed to revert camera");
                        camera.open_stream().expect("Failed to open default stream");
                    }
                }
            } else {
                println!("Invalid index. Opening default stream...");
                camera.open_stream().expect("Failed to open default stream");
            }
        } else {
            println!("Invalid input. Opening default stream...");
            camera.open_stream().expect("Failed to open default stream");
        }
    } else {
        println!("Keeping default. Opening stream...");
        camera.open_stream().expect("Failed to open default stream");
    }

    println!("Current active format: {}", camera.camera_format());

    // Warm-up delay
    println!("Waiting 2 seconds for camera warm-up...");
    std::thread::sleep(std::time::Duration::from_secs(2));

    // Capture 5 frames
    for i in 0..5 {
        match camera.frame() {
            Ok(frame) => {
                println!("Captured frame {}: {}x{}", i, frame.resolution().width(), frame.resolution().height());
                match frame.decode_image::<RgbFormat>() {
                    Ok(decoded) => {
                        let path = format!("frame_{}.png", i);
                        if let Err(e) = decoded.save_with_format(&path, image::ImageFormat::Png) {
                            println!("  Failed to save image: {}", e);
                        } else {
                            println!("  Saved to: {}", path);
                        }
                    }
                    Err(e) => println!("  Failed to decode frame: {}", e),
                }
            }
            Err(e) => println!("Failed to capture frame {}: {}", i, e),
        }
    }

    println!("Capture finished!");
    let _ = camera.stop_stream();
}
