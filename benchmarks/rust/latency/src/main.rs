use latency::exports_wasi_cli_run_run;

fn main() {
    let success = latency::exports_wasi_cli_run_run();
    if !success {
        std::process::exit(1);
    }
}
