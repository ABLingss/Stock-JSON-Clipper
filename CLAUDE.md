# CLAUDE.md — 灵析 (LingXi)

## Project Context

A-share stock data → AI-ready JSON desktop tool. Users search stock codes in a WebView panel, data flows through stock-api (browser bundle), Python computes technical indicators (MA/MACD/RSI/BOLL), results render with SVG charts. System tray + WebView panel via pystray + pywebview. Single-file PyInstaller exe.

**V3.0 architecture:**
```
main.py                  Entry point
core/
  clipper.py             Config + cache + registry (minimal, ~60 lines)
  config.py              INI config (writes next to exe)
  cache.py               TTL in-memory cache
  registry.py            BaseModule + ModuleRegistry (plugin system)
  logging_setup.py       RotatingFileHandler
data/
  indicators.py          Pure Python MA/MACD/RSI/BOLL
  builder.py             JSON assembly + build_summary
ui/
  tray.py                pystray tray icon + menu
  panel.py               PANEL_HTML (70KB, stock-api inline bundle + SVG chart + all CSS/JS)
modules/prompt/
  formula.py             TDX formula → AI prompt generator (PromptModule)
```

**Data flow:** JS `StockApi.stocks.auto.getKlines()` → `pywebview.api.compute_indicators()` → Python calculates → returns enriched dict → JS renders chart + table.

**Key dependencies:** pywebview, pystray, PIL (tray icon), pyperclip. No numpy/pandas. stock-api IIFE bundle is embedded inline (16KB).

## Critical Lessons Learned

### 1. pywebview JS bridge: NO dynamic setattr
PanelAPI methods MUST be defined directly on the class. Using `setattr(self, name, func)` in `__init__` to attach methods from ModuleRegistry causes pywebview to not expose them to JS. Module methods are now defined as regular PanelAPI methods.

### 2. pywebview + pystray: BOTH need main thread
Cannot auto-show panel from background thread. `webview.start()` blocks, must run on main thread. Tray `icon.run()` also blocks on main thread. Solution: user clicks tray menu → panel opens on main thread. No auto-show.

### 3. NO dynamic HTML assembly
All HTML/CSS/JS must be statically baked into PANEL_HTML. Runtime string replacement (injecting module tabs via `</style>` or `</script>` replacement) breaks JS parsing. Module HTML contributions (get_panel_tab/get_panel_css/get_panel_js) are NOT used — everything is hardcoded in PANEL_HTML.

### 4. PyInstaller: config.ini path
Use `sys.executable` dir when frozen (`getattr(sys, 'frozen', False)`), project root otherwise. Bundle config.ini as data file. Ensure `os.makedirs` before writing config.

### 5. WebView2 cold start
First launch takes 2-5 seconds. This is WebView2 runtime initialization, unavoidable with pywebview on Windows. Tray icon appears instantly, user gets immediate feedback.

### 6. PanelAPI methods: check for duplicates
When refactoring, old methods can shadow new ones (e.g., two `get_history` definitions). The last definition wins in Python, so the old `get_history` calling clipper's empty stub overrode the new one with real data.

### 7. JS syntax errors: silent killers
A single missing `}` in a JS function prevents ALL subsequent scripts from executing. No error visible in --noconsole mode. Always validate JS syntax after edits, especially when editing PANEL_HTML raw string.

### 8. External CDN scripts: don't work in pywebview
`<script src="https://cdn.jsdelivr.net/...">` fails in pywebview's local page context. Always embed dependencies inline as `<script>...bundle...</script>`.

## Build & Release

```bash
python -m PyInstaller LingXi.spec   # Build exe
iscc installer.iss                   # Build Windows installer
gh release create v3.2 --title "..." dist/LingXi.exe
```

**Release checklist:**
- [ ] `python main.py --code 000001` (CLI mode)
- [ ] Double-click exe → tray icon appears
- [ ] Right-click tray → "显示面板" → panel opens
- [ ] Search "000001" → data loads + chart renders + history updates
- [ ] Copy JSON / Save file / AI analysis / Deep analysis buttons work
- [ ] Check LingXi.log for errors
