//! UVC webcam capture via WASI-USB — guest-side implementation.
//!
//! All webcam-specific logic lives here:
//! 1. UVC Control interface discovery
//! 2. Probe/Commit negotiation (control transfers)
//! 3. Isochronous endpoint activation (alt-setting)
//! 4. Raw packet capture via the generic `await-transfer`
//! 5. UVC payload header stripping + FID-based frame reassembly
//!
//! The host only sees generic USB operations; no UVC, MJPEG, or ML here.

#[cfg(target_family = "wasm")]
use crate::bindings::component::usb::{
    device::DeviceHandle,
    transfers::{await_transfer, TransferOptions, TransferSetup, TransferType},
};

use anyhow::{bail, Result};

/// Raw captured video frame.
pub struct RawFrame {
    pub data: Vec<u8>,
    pub width: u32,
    pub height: u32,
}

// ─── UVC constants ────────────────────────────────────────────────────────────
const UVC_VS_PROBE_CONTROL: u16 = 0x0100;
const UVC_VS_COMMIT_CONTROL: u16 = 0x0200;
const UVC_GET_CUR: u8 = 0x81;
const UVC_SET_CUR: u8 = 0x01;

// ─── Preferred camera ─────────────────────────────────────────────────────────
/// Logitech Brio 100 — preferred over any other UVC device when present.
const BRIO_VID: u16 = 0x046d;
const BRIO_PID: u16 = 0x094c;
/// Returns true if `data` is a complete JPEG (starts with SOI, ends with EOI).
fn is_complete_jpeg(data: &[u8]) -> bool {
    data.len() >= 4
        && data[0] == 0xFF && data[1] == 0xD8        // SOI
        && data[data.len() - 2] == 0xFF && data[data.len() - 1] == 0xD9 // EOI
}

// ─── WebcamFrameStream ────────────────────────────────────────────────────────

/// Guest-side UVC frame stream. Handles negotiation and reassembly internally.
/// Mutable capture state is wrapped in RefCell so GuestFrameStream::read_frame
/// can be called via &self (as the WIT resource model requires).
#[cfg(target_family = "wasm")]
pub struct WebcamFrameStream {
    handle: DeviceHandle,
    ep_addr: u8,
    packet_stride: u32,
    num_packets: u32,
    actual_frame_size: u32,
    // Reassembly state — interior-mutable
    inner: std::cell::RefCell<ReassemblyState>,
}

#[cfg(target_family = "wasm")]
struct ReassemblyState {
    frame_buffer: Vec<u8>,
    last_fid: u8,
    frame_started: bool,
    _frame_count: u32,
}

#[cfg(target_family = "wasm")]
impl WebcamFrameStream {
    pub fn new(index: u32) -> Self {
        open_uvc_stream(index).expect("Failed to open UVC stream")
    }

}

// ─── UVC device open & negotiate ─────────────────────────────────────────────

#[cfg(target_family = "wasm")]
fn open_uvc_stream(index: u32) -> Result<WebcamFrameStream> {
    use crate::bindings::component::usb::device;

    // 0. Initialize backend.
    device::init().map_err(|e| anyhow::anyhow!("{:?}", e))?;

    // 1. Find the Nth UVC device.
    let all_devices = device::list_devices().map_err(|e| anyhow::anyhow!("{:?}", e))?;
    println!("Found {} USB devices total.", all_devices.len());
    for (i, (_dev, desc, _)) in all_devices.iter().enumerate() {
        println!(
            "  Device #{}: ID {:04x}:{:04x}, Class 0x{:02x}",
            i, desc.vendor_id, desc.product_id, desc.device_class
        );
    }

    let mut uvc: Vec<_> = all_devices
        .into_iter()
        .filter(|(_, desc, _)| {
            let is_uvc =
                desc.device_class == 0x0E || desc.device_class == 0xEF || desc.device_class == 0x00;
            is_uvc
        })
        .collect();
    println!(
        "Found {} potential UVC devices (Class 0E, EF, or 00).",
        uvc.len()
    );

    // Prefer the Logitech Brio (046d:094c) when it is present. Fall back to
    // index-based selection so other cameras still work when the Brio is absent.
    let brio_pos = uvc
        .iter()
        .position(|(_, desc, _)| desc.vendor_id == BRIO_VID && desc.product_id == BRIO_PID);

    let (dev, _, _) = if let Some(pos) = brio_pos {
        println!("  -> Selecting Logitech Brio {:04x}:{:04x} at UVC position {}.", BRIO_VID, BRIO_PID, pos);
        uvc.remove(pos)
    } else {
        println!("  -> Logitech Brio not found, falling back to UVC index {}.", index);
        uvc.drain(..)
            .nth(index as usize)
            .ok_or_else(|| anyhow::anyhow!("No UVC device at index {}", index))?
    };

    // 2. Open handle.
    let handle = dev.open().map_err(|e| anyhow::anyhow!("{:?}", e))?;

    // 3. Find best isochronous-IN endpoint on a UVC streaming interface.
    let config = dev
        .get_active_configuration_descriptor()
        .map_err(|e| anyhow::anyhow!("{:?}", e))?;

    let mut best: Option<(u8, u8, u8, u16)> = None; // (iface, altsetting, ep, mps)
    for iface in &config.interfaces {
        if iface.interface_class != 0x0E || iface.interface_subclass != 0x02 {
            continue;
        }
        for ep in &iface.endpoints {
            let is_iso_in = (ep.endpoint_address & 0x80 != 0) && (ep.attributes & 0x03 == 1);
            if !is_iso_in {
                continue;
            }
            let base_mps = ep.max_packet_size & 0x7FF;
            let mult = 1 + ((ep.max_packet_size >> 11) & 0x03);
            let effective = base_mps * mult;
            if best.map_or(true, |(_, _, _, s)| effective > s) {
                best = Some((
                    iface.interface_number,
                    iface.alternate_setting,
                    ep.endpoint_address,
                    effective,
                ));
            }
        }
    }
    let (iface_num, alt_setting, ep_addr, max_packet_size) =
        best.ok_or_else(|| anyhow::anyhow!("No UVC streaming interface found"))?;

    // 4. Claim interface and start at alt 0 (zero-bandwidth).
    handle
        .claim_interface(iface_num)
        .map_err(|e| anyhow::anyhow!("{:?}", e))?;
    handle.set_interface_altsetting(iface_num, 0).ok();
    std::thread::sleep(std::time::Duration::from_millis(50));

    let ctrl_idx = iface_num as u16;
    let no_timeout = TransferOptions {
        endpoint: 0,
        timeout_ms: 2000,
        stream_id: 0,
        iso_packets: 0,
    };

    // Helper: do a control transfer and return the data portion only.
    let ctrl = |h: &DeviceHandle,
                setup: TransferSetup,
                payload: &[u8],
                payload_len: u32|
     -> Result<Vec<u8>> {
        let xfer = h
            .new_transfer(TransferType::Control, setup.clone(), payload_len, no_timeout.clone())
            .map_err(|e| anyhow::anyhow!("{:?}", e))?;

        // The wasi-usb host manages the 8-byte USB setup packet internally in
        // new_transfer and strips it from IN responses. Guests pass and receive
        // raw payload bytes on both directions.
        let submit_buf: Vec<u8> = payload.to_vec();

        xfer.submit_transfer(&submit_buf)
            .map_err(|e| anyhow::anyhow!("{:?}", e))?;
        let result = await_transfer(&xfer).map_err(|e| anyhow::anyhow!("{:?}", e))?;

        Ok(result.data)
    };

    // 5. GET_CUR probe → modify → SET_CUR probe → GET_CUR probe (negotiated).
    let probe_get_setup = TransferSetup {
        bm_request_type: 0xA1,
        b_request: UVC_GET_CUR,
        w_value: UVC_VS_PROBE_CONTROL,
        w_index: ctrl_idx,
    };
    let probe_set_setup = TransferSetup {
        bm_request_type: 0x21,
        b_request: UVC_SET_CUR,
        w_value: UVC_VS_PROBE_CONTROL,
        w_index: ctrl_idx,
    };

    let mut probe_data = ctrl(&handle, probe_get_setup.clone(), &[], 34)?;
    if probe_data.len() >= 4 {
        probe_data[2] = 2; // bFormatIndex (MJPEG)
        probe_data[3] = 1; // bFrameIndex
    }
    let probe_len = probe_data.len() as u32;
    ctrl(&handle, probe_set_setup, &probe_data, probe_len)?;
    let negotiated = ctrl(&handle, probe_get_setup, &[], probe_len)?;

    let actual_frame_size = if negotiated.len() >= 22 {
        u32::from_le_bytes(negotiated[18..22].try_into().unwrap_or([0; 4]))
    } else {
        0
    };

    // 6. SET_CUR commit — with the EXACT bytes the camera returned in step 5.
    let commit_setup = TransferSetup {
        bm_request_type: 0x21,
        b_request: UVC_SET_CUR,
        w_value: UVC_VS_COMMIT_CONTROL,
        w_index: ctrl_idx,
    };
    ctrl(&handle, commit_setup, &negotiated, negotiated.len() as u32)?;
    println!("Handshake complete. Negotiated frame size: {} bytes.", actual_frame_size);

    // 7. Enable Auto White Balance on the Processing Unit AFTER the handshake,
    //    BEFORE activating the high-bandwidth alt-setting.
    //    PU_WHITE_BALANCE_TEMPERATURE_AUTO_CONTROL = 0x0B
    //    w_index = (unit_id << 8) | vc_interface_number
    println!("Enabling Auto White Balance (Processing Unit 2)...");
    let vc_iface: u16 = 0; // VideoControl interface is always 0
    let pu_unit:  u16 = 2; // Processing Unit ID
    let awb_setup = TransferSetup {
        bm_request_type: 0x21,
        b_request: UVC_SET_CUR,
        w_value: 0x0B00, // PU_WHITE_BALANCE_TEMPERATURE_AUTO_CONTROL
        w_index: (pu_unit << 8) | vc_iface,
    };
    // Ignore errors: not all cameras expose this control.
    if let Ok(data) = ctrl(&handle, awb_setup, &[1], 1) {
        let _ = data;
        println!("  Auto White Balance enabled.");
    }

    // 8. Switch to high-bandwidth alt setting — only after ISP is configured.
    handle
        .set_interface_altsetting(iface_num, alt_setting)
        .map_err(|e| anyhow::anyhow!("{:?}", e))?;

    // 9. Camera ISP warm-up — critical for Auto White Balance to converge.
    //    Without this sleep, the first frames are captured before AWB
    //    stabilises → pink/magenta cast locked into the whole session.
    println!("Camera ISP warm-up (2 seconds)...");
    std::thread::sleep(std::time::Duration::from_secs(2));

    Ok(WebcamFrameStream {
        handle,
        ep_addr,
        packet_stride: max_packet_size as u32,
        num_packets: 32,
        actual_frame_size,
        inner: std::cell::RefCell::new(ReassemblyState {
            frame_buffer: Vec::new(),
            last_fid: 0,
            frame_started: false,
            _frame_count: 0,
        }),
    })
}

// ─── Capture & Reassembly ─────────────────────────────────────────────────────

#[cfg(target_family = "wasm")]
impl WebcamFrameStream {
    fn capture_uvc_frame(&self) -> Result<RawFrame> {
        let buffer_size = self.num_packets * self.packet_stride;
        let opts = TransferOptions {
            endpoint: self.ep_addr,
            timeout_ms: 2000,
            stream_id: 0,
            iso_packets: self.num_packets,
        };
        let setup = TransferSetup {
            bm_request_type: 0,
            b_request: 0,
            w_value: 0,
            w_index: 0,
        };

        for _attempt in 0..2000 {
            let xfer = self
                .handle
                .new_transfer(
                    TransferType::Isochronous,
                    setup.clone(),
                    buffer_size,
                    opts.clone(),
                )
                .map_err(|e| anyhow::anyhow!("{:?}", e))?;
            xfer.submit_transfer(&[])
                .map_err(|e| anyhow::anyhow!("{:?}", e))?;
            let result = await_transfer(&xfer).map_err(|e| anyhow::anyhow!("{:?}", e))?;

            let stride = self.packet_stride as usize;
            let mut offset = 0usize;

            for packet in result.packets {
                let actual_len = packet.actual_length as usize;
                if actual_len == 0 {
                    offset += stride;
                    continue;
                }
                let end = (offset + actual_len.min(stride)).min(result.data.len());
                let pkt_data = &result.data[offset..end];
                offset += stride;

                if pkt_data.len() < 2 {
                    continue;
                }
                let hdr_len = pkt_data[0] as usize;
                if hdr_len < 2 || hdr_len > pkt_data.len() {
                    continue;
                }
                let hdr_flags = pkt_data[1];
                let is_eof = (hdr_flags & 0x02) != 0;
                let fid = hdr_flags & 0x01;
                let payload = &pkt_data[hdr_len..];

                let mut st = self.inner.borrow_mut();

                // FID toggle → previous frame is complete.
                if !st.frame_buffer.is_empty() && fid != st.last_fid {
                    let complete = std::mem::take(&mut st.frame_buffer);
                    st.frame_started = false;
                    st.last_fid = fid;
                    st.frame_buffer.extend_from_slice(payload);
                    st.frame_started = true;
                    drop(st); // release borrow before returning

                    if is_complete_jpeg(&complete) {
                        let (w, h) = guess_resolution(complete.len(), self.actual_frame_size);
                        return Ok(RawFrame {
                            data: complete,
                            width: w,
                            height: h,
                        });
                    } else {
                        eprintln!("[webcam] dropped incomplete frame ({} bytes) on FID toggle", complete.len());
                    }
                } else {
                    if !st.frame_started && !payload.is_empty() {
                        st.frame_started = true;
                    }
                    if st.frame_started {
                        st.frame_buffer.extend_from_slice(payload);
                    }
                    if st.frame_started && is_eof && !st.frame_buffer.is_empty() {
                        let complete = std::mem::take(&mut st.frame_buffer);
                        st.frame_started = false;
                        st.last_fid = fid;
                        drop(st);

                        if is_complete_jpeg(&complete) {
                            let (w, h) = guess_resolution(complete.len(), self.actual_frame_size);
                            return Ok(RawFrame {
                                data: complete,
                                width: w,
                                height: h,
                            });
                        } else {
                            eprintln!("[webcam] dropped incomplete frame ({} bytes) on EOF", complete.len());
                        }
                    } else {
                        st.last_fid = fid;
                    }
                }
            }
        }
        bail!("Timed out waiting for a complete frame")
    }
}

fn guess_resolution(frame_size: usize, _negotiated: u32) -> (u32, u32) {
    const KNOWN: &[(u32, u32)] = &[
        (1920, 1080),
        (1280, 720),
        (640, 480),
        (352, 288),
        (320, 240),
        (320, 180),
        (320, 120),
        (176, 144),
        (160, 144),
        (160, 120),
        (160, 90),
    ];
    for &(w, h) in KNOWN {
        let expected = (w * h * 2) as usize;
        if frame_size.abs_diff(expected) * 20 <= expected {
            return (w, h);
        }
    }
    (640, 480)
}

// ─── JPEG DHT injection ───────────────────────────────────────────────────────

/// UVC cameras commonly omit Huffman tables (DHT segments) from their MJPEG
/// output, relying on the decoder to supply the standard baseline tables.
/// Lenient decoders (libjpeg, most viewers) handle this transparently, but
/// strict ones such as macOS ImageIO / Preview require explicit DHT segments.
///
/// This function injects the four standard baseline Huffman tables defined in
/// ITU-T T.81 Annex K just before the SOS marker, but only when no DHT is
/// already present, so frames that already carry their own tables are untouched.
fn inject_standard_dht(data: &[u8]) -> Vec<u8> {
    // Standard baseline JPEG Huffman tables (ITU-T T.81, Annex K).
    #[rustfmt::skip]
    const DHT_DC_LUMA: &[u8] = &[
        0xFF,0xC4, 0x00,0x1F, 0x00,
        0x00,0x01,0x05,0x01,0x01,0x01,0x01,0x01,0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
        0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0A,0x0B,
    ];
    #[rustfmt::skip]
    const DHT_DC_CHROMA: &[u8] = &[
        0xFF,0xC4, 0x00,0x1F, 0x01,
        0x00,0x03,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x01,0x00,0x00,0x00,0x00,0x00,
        0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0A,0x0B,
    ];
    #[rustfmt::skip]
    const DHT_AC_LUMA: &[u8] = &[
        0xFF,0xC4, 0x00,0xB5, 0x10,
        0x00,0x02,0x01,0x03,0x03,0x02,0x04,0x03,0x05,0x05,0x04,0x04,0x00,0x00,0x01,0x7D,
        0x01,0x02,0x03,0x00,0x04,0x11,0x05,0x12,0x21,0x31,0x41,0x06,0x13,0x51,0x61,0x07,
        0x22,0x71,0x14,0x32,0x81,0x91,0xA1,0x08,0x23,0x42,0xB1,0xC1,0x15,0x52,0xD1,0xF0,
        0x24,0x33,0x62,0x72,0x82,0x09,0x0A,0x16,0x17,0x18,0x19,0x1A,0x25,0x26,0x27,0x28,
        0x29,0x2A,0x34,0x35,0x36,0x37,0x38,0x39,0x3A,0x43,0x44,0x45,0x46,0x47,0x48,0x49,
        0x4A,0x53,0x54,0x55,0x56,0x57,0x58,0x59,0x5A,0x63,0x64,0x65,0x66,0x67,0x68,0x69,
        0x6A,0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7A,0x83,0x84,0x85,0x86,0x87,0x88,0x89,
        0x8A,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,0x9A,0xA2,0xA3,0xA4,0xA5,0xA6,0xA7,
        0xA8,0xA9,0xAA,0xB2,0xB3,0xB4,0xB5,0xB6,0xB7,0xB8,0xB9,0xBA,0xC2,0xC3,0xC4,0xC5,
        0xC6,0xC7,0xC8,0xC9,0xCA,0xD2,0xD3,0xD4,0xD5,0xD6,0xD7,0xD8,0xD9,0xDA,0xE1,0xE2,
        0xE3,0xE4,0xE5,0xE6,0xE7,0xE8,0xE9,0xEA,0xF1,0xF2,0xF3,0xF4,0xF5,0xF6,0xF7,0xF8,
        0xF9,0xFA,
    ];
    #[rustfmt::skip]
    const DHT_AC_CHROMA: &[u8] = &[
        0xFF,0xC4, 0x00,0xB5, 0x11,
        0x00,0x02,0x01,0x02,0x04,0x04,0x03,0x04,0x07,0x05,0x04,0x04,0x00,0x01,0x02,0x77,
        0x00,0x01,0x02,0x03,0x11,0x04,0x05,0x21,0x31,0x06,0x12,0x41,0x51,0x07,0x61,0x71,
        0x13,0x22,0x32,0x81,0x08,0x14,0x42,0x91,0xA1,0xB1,0xC1,0x09,0x23,0x33,0x52,0xF0,
        0x15,0x62,0x72,0xD1,0x0A,0x16,0x24,0x34,0xE1,0x25,0xF1,0x17,0x18,0x19,0x1A,0x26,
        0x27,0x28,0x29,0x2A,0x35,0x36,0x37,0x38,0x39,0x3A,0x43,0x44,0x45,0x46,0x47,0x48,
        0x49,0x4A,0x53,0x54,0x55,0x56,0x57,0x58,0x59,0x5A,0x63,0x64,0x65,0x66,0x67,0x68,
        0x69,0x6A,0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7A,0x82,0x83,0x84,0x85,0x86,0x87,
        0x88,0x89,0x8A,0x92,0x93,0x94,0x95,0x96,0x97,0x98,0x99,0x9A,0xA2,0xA3,0xA4,0xA5,
        0xA6,0xA7,0xA8,0xA9,0xAA,0xB2,0xB3,0xB4,0xB5,0xB6,0xB7,0xB8,0xB9,0xBA,0xC2,0xC3,
        0xC4,0xC5,0xC6,0xC7,0xC8,0xC9,0xCA,0xD2,0xD3,0xD4,0xD5,0xD6,0xD7,0xD8,0xD9,0xDA,
        0xE2,0xE3,0xE4,0xE5,0xE6,0xE7,0xE8,0xE9,0xEA,0xF2,0xF3,0xF4,0xF5,0xF6,0xF7,0xF8,
        0xF9,0xFA,
    ];

    // If DHT already present, return as-is.
    let has_dht = data.windows(2).any(|w| w == [0xFF, 0xC4]);
    if has_dht {
        return data.to_vec();
    }

    // Find the SOS marker and inject the four tables just before it.
    if let Some(sos) = data.windows(2).position(|w| w == [0xFF, 0xDA]) {
        let mut out = Vec::with_capacity(data.len() + 432);
        out.extend_from_slice(&data[..sos]);
        out.extend_from_slice(DHT_DC_LUMA);
        out.extend_from_slice(DHT_DC_CHROMA);
        out.extend_from_slice(DHT_AC_LUMA);
        out.extend_from_slice(DHT_AC_CHROMA);
        out.extend_from_slice(&data[sos..]);
        out
    } else {
        data.to_vec() // no SOS found — pass through unchanged
    }
}

// ─── Entry point ─────────────────────────────────────────────────────────────

pub fn run_webcam() -> Result<()> {
    #[cfg(not(target_family = "wasm"))]
    bail!("webcam-cv must be compiled for wasm32");

    #[cfg(target_family = "wasm")]
    {
        use std::io::{self, BufRead, Write};

        println!("Starting UVC webcam capture...");
        let stream = WebcamFrameStream::new(0);
        println!("Stream initialized.");

        let stdin = io::stdin();
        let mut frame_idx = 0u32;
        loop {
            print!("Press ENTER for frame #{} (or type EXIT): ", frame_idx + 1);
            io::stdout().flush().ok();
            let mut line = String::new();
            if stdin.lock().read_line(&mut line).is_err()
                || line.trim().eq_ignore_ascii_case("exit")
            {
                break;
            }
            match stream.capture_uvc_frame() {
                Ok(f) => {
                    frame_idx += 1;
                    // UVC MJPEG frames omit Huffman tables (DHT segments); inject
                    // the standard baseline tables so strict decoders such as
                    // macOS Preview / ImageIO can open the file.
                    let jpeg_bytes = inject_standard_dht(&f.data);
                    if let Err(e) = std::fs::write("out/latest.jpg", &jpeg_bytes) {
                        eprintln!("warn: could not write out/latest.jpg: {e}");
                    }
                    println!(
                        "Frame #{}: {}x{} ({} bytes) → out/latest.jpg",
                        frame_idx,
                        f.width,
                        f.height,
                        f.data.len()
                    );
                }
                Err(e) => eprintln!("Capture error: {e}"),
            }
        }
        Ok(())
    }
}
