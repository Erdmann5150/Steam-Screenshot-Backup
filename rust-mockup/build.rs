fn main() {
    // "fluent" follows the light/dark scheme we set at runtime, so the stock
    // checkboxes, combo boxes and tabs re-theme along with our own colors.
    let config = slint_build::CompilerConfiguration::new().with_style("fluent".into());
    slint_build::compile_with_config("ui/app.slint", config).unwrap();
}
