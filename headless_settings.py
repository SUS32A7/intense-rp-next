from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from config.manager import ConfigManager
from config.schema import SCHEMA, SettingType


_EDITABLE_TYPES = {
    SettingType.BOOLEAN,
    SettingType.STRING,
    SettingType.DIRECTORY,
    SettingType.INTEGER,
    SettingType.PASSWORD,
    SettingType.TEXTAREA,
    SettingType.DROPDOWN,
    SettingType.INPUT_LIST,
}

_SKIP_TYPES = {
    SettingType.BUTTON,
    SettingType.DESCRIPTION,
    SettingType.DIVIDER,
    SettingType.HINT,
    SettingType.REDIRECT,
}


class SettingsUpdateRequest(BaseModel):
    category: str
    key: str
    value: Any


class SettingsBulkUpdateRequest(BaseModel):
    updates: list[SettingsUpdateRequest]



def _iter_setting_fields(fields):
    for field in fields:
        if getattr(field, "transient", False):
            continue

        if field.type == SettingType.ROW and field.sub_fields:
            yield from _iter_setting_fields(field.sub_fields)
            continue

        if field.type in _SKIP_TYPES:
            continue

        yield field


def _coerce_value_for_field(field, raw_value: Any) -> Any:
    if field.type == SettingType.BOOLEAN:
        return bool(raw_value)

    if field.type == SettingType.INTEGER:
        try:
            return int(raw_value)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid integer for {field.key}: {raw_value}") from exc

    if field.type == SettingType.INPUT_LIST:
        if isinstance(raw_value, list):
            return [str(item) for item in raw_value]
        if isinstance(raw_value, str):
            # Accept newline/comma-separated strings for convenience.
            parts = [piece.strip() for piece in raw_value.replace("\n", ",").split(",")]
            return [piece for piece in parts if piece]
        raise HTTPException(status_code=400, detail=f"Invalid list for {field.key}: {raw_value}")

    if field.type == SettingType.DROPDOWN and field.options:
        candidate = str(raw_value)
        if candidate not in field.options:
            raise HTTPException(status_code=400, detail=f"Invalid option for {field.key}: {candidate}")
        return candidate

    return raw_value


def _build_schema_payload(config_manager: ConfigManager) -> list[dict[str, Any]]:
    categories_payload: list[dict[str, Any]] = []

    for category in SCHEMA:
        fields_payload: list[dict[str, Any]] = []
        for field in _iter_setting_fields(category.fields):
            if field.type not in _EDITABLE_TYPES:
                continue

            fields_payload.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "type": field.type.value,
                    "tooltip": field.tooltip,
                    "options": list(field.options or []),
                    "value": config_manager.get_setting(category.key, field.key),
                }
            )

        if fields_payload:
            categories_payload.append(
                {
                    "key": category.key,
                    "name": category.name,
                    "fields": fields_payload,
                }
            )

    return categories_payload


def _get_schema_field(category_key: str, field_key: str):
    for category in SCHEMA:
        if category.key != category_key:
            continue
        for field in _iter_setting_fields(category.fields):
            if field.key == field_key:
                return field
    return None


def register_headless_settings_routes(app, config_manager: ConfigManager) -> None:
    @app.get("/settings", response_class=HTMLResponse)
    async def settings_dashboard() -> HTMLResponse:
        return HTMLResponse(_SETTINGS_HTML)

    @app.get("/settings/api/schema")
    async def settings_schema():
        return {"categories": _build_schema_payload(config_manager)}

    @app.post("/settings/api/update")
    async def settings_update(payload: SettingsUpdateRequest):
        field = _get_schema_field(payload.category, payload.key)
        if field is None:
            raise HTTPException(status_code=404, detail="Unknown setting")
        if field.type not in _EDITABLE_TYPES:
            raise HTTPException(status_code=400, detail="Setting is not editable from dashboard")

        coerced = _coerce_value_for_field(field, payload.value)
        config_manager.set_setting(payload.category, payload.key, coerced)
        config_manager.save_settings()
        return {"ok": True, "category": payload.category, "key": payload.key, "value": coerced}

    @app.post("/settings/api/update-bulk")
    async def settings_update_bulk(payload: SettingsBulkUpdateRequest):
        applied: list[dict[str, Any]] = []
        for update in payload.updates:
            field = _get_schema_field(update.category, update.key)
            if field is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown setting: {update.category}.{update.key}",
                )
            if field.type not in _EDITABLE_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Setting is not editable: {update.category}.{update.key}",
                )

            coerced = _coerce_value_for_field(field, update.value)
            config_manager.set_setting(update.category, update.key, coerced)
            applied.append(
                {
                    "category": update.category,
                    "key": update.key,
                    "value": coerced,
                }
            )

        config_manager.save_settings()
        return {"ok": True, "applied": applied}


_SETTINGS_HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>IntenseRP Headless Settings</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: #121212; color: #e7e7e7; }
    header { padding: 16px 20px; border-bottom: 1px solid #2a2a2a; position: sticky; top: 0; background: #121212; }
    main { max-width: 1120px; margin: 0 auto; padding: 16px 20px 64px; }
    h1 { margin: 0; font-size: 22px; }
    .hint { color: #9aa4b2; margin-top: 8px; font-size: 13px; }
    .category { border: 1px solid #2a2a2a; border-radius: 12px; padding: 16px; margin-top: 14px; background: #171717; }
    .category h2 { margin: 0 0 12px; font-size: 18px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
    .field { border: 1px solid #303030; border-radius: 10px; padding: 10px; background: #1d1d1d; }
    label { display: block; font-size: 13px; margin-bottom: 6px; color: #d7d7d7; }
    input, select, textarea { width: 100%; box-sizing: border-box; border-radius: 8px; border: 1px solid #444; background: #0f0f0f; color: #f0f0f0; padding: 8px; }
    textarea { min-height: 92px; resize: vertical; }
    .tip { margin-top: 6px; font-size: 12px; color: #9aa4b2; }
    .toolbar { margin-top: 18px; display: flex; gap: 8px; align-items: center; }
    button { border: 1px solid #3f3f3f; border-radius: 8px; padding: 8px 14px; color: #fff; background: #1f6feb; cursor: pointer; }
    button.secondary { background: #232323; }
    #status { font-size: 13px; color: #9aa4b2; }
  </style>
</head>
<body>
  <header>
    <h1>IntenseRP Headless Settings</h1>
    <div class=\"hint\">Web dashboard for editing settings while running headless mode.</div>
  </header>
  <main>
    <div class=\"toolbar\">
      <button id=\"save-all\">Save all changes</button>
      <button id=\"reload\" class=\"secondary\">Reload from disk</button>
      <span id=\"status\">Loading...</span>
    </div>
    <div id=\"app\"></div>
  </main>
  <script>
    const app = document.getElementById('app');
    const status = document.getElementById('status');
    const saveBtn = document.getElementById('save-all');
    const reloadBtn = document.getElementById('reload');

    let state = { categories: [] };

    function mk(tag, attrs = {}, children = []) {
      const el = document.createElement(tag);
      for (const [k, v] of Object.entries(attrs)) {
        if (k === 'className') el.className = v;
        else if (k === 'text') el.textContent = v;
        else el.setAttribute(k, v);
      }
      for (const child of children) el.appendChild(child);
      return el;
    }

    function normalizeValue(type, input) {
      if (type === 'boolean') return !!input.checked;
      if (type === 'integer') return Number.parseInt(input.value || '0', 10);
      if (type === 'input_list') return (input.value || '').split(/[,\n]/).map(v => v.trim()).filter(Boolean);
      return input.value;
    }

    function render() {
      app.innerHTML = '';
      for (const category of state.categories) {
        const card = mk('section', { className: 'category' });
        card.appendChild(mk('h2', { text: category.name }));
        const grid = mk('div', { className: 'grid' });

        for (const field of category.fields) {
          const box = mk('div', { className: 'field' });
          box.appendChild(mk('label', { text: field.label }));

          let input;
          if (field.type === 'boolean') {
            input = mk('input', { type: 'checkbox' });
            input.checked = !!field.value;
          } else if (field.type === 'dropdown') {
            input = mk('select');
            for (const option of (field.options || [])) {
              const opt = mk('option', { value: option, text: option });
              if (option === field.value) opt.selected = true;
              input.appendChild(opt);
            }
          } else if (field.type === 'textarea' || field.type === 'input_list') {
            input = mk('textarea');
            if (field.type === 'input_list' && Array.isArray(field.value)) {
              input.value = field.value.join('\n');
            } else {
              input.value = field.value ?? '';
            }
          } else if (field.type === 'password') {
            input = mk('input', { type: 'password', value: field.value ?? '' });
          } else if (field.type === 'integer') {
            input = mk('input', { type: 'number', value: String(field.value ?? 0) });
          } else {
            input = mk('input', { type: 'text', value: field.value ?? '' });
          }

          input.dataset.category = category.key;
          input.dataset.key = field.key;
          input.dataset.type = field.type;

          box.appendChild(input);
          if (field.tooltip) {
            box.appendChild(mk('div', { className: 'tip', text: field.tooltip }));
          }
          grid.appendChild(box);
        }

        card.appendChild(grid);
        app.appendChild(card);
      }
    }

    async function loadSchema() {
      status.textContent = 'Loading settings...';
      const res = await fetch('/settings/api/schema');
      if (!res.ok) {
        status.textContent = `Failed to load (${res.status})`;
        return;
      }
      const payload = await res.json();
      state.categories = payload.categories || [];
      render();
      status.textContent = 'Loaded.';
    }

    async function saveAll() {
      const inputs = app.querySelectorAll('input, select, textarea');
      const updates = [];
      for (const input of inputs) {
        updates.push({
          category: input.dataset.category,
          key: input.dataset.key,
          value: normalizeValue(input.dataset.type, input),
        });
      }

      status.textContent = 'Saving...';
      const res = await fetch('/settings/api/update-bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates }),
      });
      if (!res.ok) {
        const err = await res.text();
        status.textContent = `Save failed (${res.status}): ${err}`;
        return;
      }
      status.textContent = 'Saved.';
      await loadSchema();
    }

    saveBtn.addEventListener('click', saveAll);
    reloadBtn.addEventListener('click', loadSchema);
    loadSchema();
  </script>
</body>
</html>
"""
