#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    Manager,
};

const DEFAULT_ZOOM: f64 = 1.0;
const MIN_ZOOM: f64 = 0.5;
const MAX_ZOOM: f64 = 2.0;
const ZOOM_STEP: f64 = 0.2;

struct ZoomState(Mutex<f64>);

fn main() {
    tauri::Builder::default()
        .manage(ZoomState(Mutex::new(DEFAULT_ZOOM)))
        .menu(|app| {
            let zoom_in = MenuItem::with_id(app, "zoom_in", "Zoom In", true, Some("CmdOrCtrl+="))?;
            let zoom_out =
                MenuItem::with_id(app, "zoom_out", "Zoom Out", true, Some("CmdOrCtrl+-"))?;
            let actual_size =
                MenuItem::with_id(app, "actual_size", "Actual Size", true, Some("CmdOrCtrl+0"))?;
            let separator = PredefinedMenuItem::separator(app)?;
            let menu = Menu::default(app)?;
            let view = menu
                .items()?
                .into_iter()
                .filter_map(|item| item.as_submenu().cloned())
                .find(|submenu| submenu.text().is_ok_and(|text| text == "View"))
                .expect("Tauri's default macOS menu must contain View");
            view.prepend_items(&[&zoom_in, &zoom_out, &actual_size, &separator])?;
            Ok(menu)
        })
        .on_menu_event(|app, event| {
            let action = if event.id() == "actual_size" {
                Some(ZoomAction::Reset)
            } else if event.id() == "zoom_in" {
                Some(ZoomAction::In)
            } else if event.id() == "zoom_out" {
                Some(ZoomAction::Out)
            } else {
                None
            };

            if let Some(action) = action {
                let state = app.state::<ZoomState>();
                let mut zoom = state.0.lock().expect("zoom state lock poisoned");
                *zoom = adjusted_zoom(*zoom, action);
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.set_zoom(*zoom);
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[derive(Clone, Copy)]
enum ZoomAction {
    In,
    Out,
    Reset,
}

fn adjusted_zoom(current: f64, action: ZoomAction) -> f64 {
    match action {
        ZoomAction::In => (current + ZOOM_STEP).min(MAX_ZOOM),
        ZoomAction::Out => (current - ZOOM_STEP).max(MIN_ZOOM),
        ZoomAction::Reset => DEFAULT_ZOOM,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zoom_steps_reset_and_clamp() {
        assert!((adjusted_zoom(1.0, ZoomAction::In) - 1.2).abs() < f64::EPSILON);
        assert!((adjusted_zoom(1.0, ZoomAction::Out) - 0.8).abs() < f64::EPSILON);
        assert_eq!(adjusted_zoom(1.8, ZoomAction::Reset), DEFAULT_ZOOM);
        assert_eq!(adjusted_zoom(MAX_ZOOM, ZoomAction::In), MAX_ZOOM);
        assert_eq!(adjusted_zoom(MIN_ZOOM, ZoomAction::Out), MIN_ZOOM);
    }
}
