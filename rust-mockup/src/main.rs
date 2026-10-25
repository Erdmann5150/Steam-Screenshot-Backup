//! Non-functional GUI mockup. Every button is inert and all data is static;
//! this exists only to show what a Slint front end for the app would look like.
//!
//! Usage: ssbackup-gui-mockup [main|settings|settings-backup|delete] [--light]

slint::include_modules!();

fn main() -> Result<(), slint::PlatformError> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let dark = !args.iter().any(|a| a == "--light");
    let which = args.iter().find(|a| !a.starts_with("--")).map(String::as_str);

    match which.unwrap_or("main") {
        "settings" | "settings-backup" => {
            let w = SettingsWindow::new()?;
            w.invoke_apply_theme(dark);
            w.set_tab(if which == Some("settings-backup") { 1 } else { 0 });
            w.run()
        }
        "delete" => {
            let w = DeleteWindow::new()?;
            w.invoke_apply_theme(dark);
            w.run()
        }
        _ => {
            let w = MainWindow::new()?;
            w.invoke_apply_theme(dark);
            w.run()
        }
    }
}
