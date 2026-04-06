# Hermes ComfyUI Workflow Plugin

讓 Hermes Agent 能夠執行 ComfyUI workflow 進行圖片生成或編輯。

## 功能

- **文生圖（text_to_image）**：純文字指令生成圖片
- **圖片編輯（image_edit）**：上傳圖片 + 指令進行 AI 編輯（如更換背景、調整顏色）

## 安裝

```bash
hermes plugins install dennygod1220/hermes-agent-comfyui-workflow
```

## 設定

安裝後，在 `.env` 檔案中添加以下環境變數：

```bash
# =============================================================================
# COMFYUI WORKFLOW
# =============================================================================
# ComfyUI API URL (需要啟用 ComfyUI 的 API 功能)
COMFY_API_URL=https://your-comfyui-server.trycloudflare.com/

# Template 目錄（安裝後自動指向 plugin 目錄）
COMFY_TEMPLATE_DIR=~/.hermes/plugins/hermes-agent-comfyui-workflow/templates

# 輸出目錄
COMFY_OUTPUT_DIR=~/.hermes/data/comfyui_output

# Debug 模式（可選，預設為 false）
COMFY_WORKFLOW_DEBUG=false
```

## 使用方式

### 文生圖

在 Discord（或任何 Hermes 支援的訊息平台）輸入：

```
生成一張圖：一隻可愛的貓咪坐在草地上
```

Agent 會自動使用 `text_to_image` workflow 生成圖片。

### 圖片編輯

上傳圖片並輸入編輯指令：

```
幫我把背景換成藍色的沙灘
```

Agent 會使用 `image_edit` workflow 進行圖片編輯。

## 環境需求

- Hermes Agent 已安裝並正常運作
- ComfyUI 已啟用 API 功能（啟動時加上 `--listen` 參數）

## 疑難排解

1. **圖片未傳送到 Discord**：請確保在回覆中包含 `MEDIA:<圖片路徑>` 標籤
2. **Template 找不到**：請確認 `COMFY_TEMPLATE_DIR` 路徑正確
3. **ComfyUI 連線失敗**：請確認 `COMFY_API_URL` 可存取

## 授權

MIT License