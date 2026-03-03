use std::path::PathBuf;

fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS") == Ok("wasi".into()) {
        // Find the sysroot relative to the project root
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../");
        let sysroot = project_root.join("rusb-wasi/examples/wasi-workload/wasi-sysroot/usr/lib");
        println!("cargo:rustc-link-arg={}", sysroot.join("cguest_component_type.o").display());
    }
}
