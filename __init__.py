#!/usr/bin/env python3
"""
ComfyUI Workflow Runner Plugin

提供 comfyui_workflow tool，讓 Agent 可以執行 ComfyUI workflow：
- 圖片編輯（image_edit）：上傳圖片 + 指令進行編輯
- 文生圖（text_to_image）：純文字指令生成圖片
"""

import json
import os
import time
import base64
import logging
import requests
from typing import Dict, Any, Optional


def _setup_logger() -> logging.Logger:
    """Setup logger based on environment variables."""
    logger = logging.getLogger("comfyui_workflow")

    if logger.handlers:
        return logger

    debug_mode = os.getenv("COMFY_WORKFLOW_DEBUG", "false").lower() == "true"
    log_dir = os.getenv("COMFY_WORKFLOW_LOG_DIR")

    if debug_mode:
        logger.setLevel(logging.DEBUG)

        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            handler = logging.FileHandler(os.path.join(log_dir, "comfyui_workflow.log"))
        else:
            handler = logging.StreamHandler()

        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        )
        logger.addHandler(handler)
    else:
        logger.setLevel(logging.WARNING)

    return logger


logger = _setup_logger()


def _load_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Hardcoded node ID fallback map (legacy templates without _meta.name)
# Format: {workflow_type: {node_name: node_id}}
_FALLBACK_NODE_IDS: Dict[str, Dict[str, str]] = {
    "image_edit": {
        "input_image": "64",
        "positive_prompt": "7",
        "latent_height": "28",
    },
    "text_to_image": {
        "positive_prompt": "67",
        "latent_size": "77",
    },
}


def _find_node_by_meta(workflow: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Find a workflow node by its _meta.name field.

    Args:
        workflow: Loaded workflow template dict.
        name: The _meta.name value to search for.

    Returns:
        The node dict if found, otherwise None.
    """
    for node in workflow.values():
        if isinstance(node, dict) and node.get("_meta", {}).get("name") == name:
            return node
    return None


def _get_node(workflow: Dict[str, Any], workflow_type: str, node_name: str) -> Optional[Dict[str, Any]]:
    """Get a workflow node by name, with fallback to hardcoded IDs for legacy templates.

    Args:
        workflow: Loaded workflow template dict.
        workflow_type: Type of workflow (image_edit or text_to_image).
        node_name: Logical name of the node (e.g. "positive_prompt").

    Returns:
        The node dict if found, otherwise None.
    """
    # Try _meta.name first (preferred, portable)
    node = _find_node_by_meta(workflow, node_name)
    if node is not None:
        logger.debug(f"Node '{node_name}' found via _meta.name")
        return node

    # Fallback to hardcoded ID (legacy templates)
    fallback_ids = _FALLBACK_NODE_IDS.get(workflow_type, {})
    legacy_id = fallback_ids.get(node_name)
    if legacy_id is not None and legacy_id in workflow:
        logger.warning(
            f"Node '{node_name}' not found via _meta.name, "
            f"falling back to legacy ID '{legacy_id}'. "
            f"Consider adding '_meta.name: {node_name}' to this node in the template."
        )
        return workflow[legacy_id]

    logger.error(f"Node '{node_name}' not found (neither via _meta.name nor legacy ID)")
    return None


def _get_template_path(workflow_type: str) -> Optional[str]:
    template_dir = _load_env("COMFY_TEMPLATE_DIR")
    if not template_dir:
        logger.warning("COMFY_TEMPLATE_DIR not set")
        return None
    # Expand ~ to user's home directory
    template_dir = os.path.expanduser(template_dir)

    template_map = {
        "image_edit": "Comfyui_Hermes_單圖編輯工作流API_Template.json",
        "text_to_image": "Flux2_klein_t2i_API_Template.json",
    }

    filename = template_map.get(workflow_type)
    if not filename:
        logger.warning(f"Unknown workflow_type: {workflow_type}")
        return None

    path = os.path.join(template_dir, filename)
    if not os.path.exists(path):
        logger.warning(f"Template file not found: {path}")
        return None

    logger.debug(f"Template found: {path}")
    return path


def _load_template(template_path: str) -> Dict[str, Any]:
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _download_image_as_base64(url: str) -> str:
    logger.debug(f"Processing image: {url}")

    # Handle file:// URL
    if url.startswith("file://"):
        url = url[7:]

    # Check if it's a local file path
    if os.path.isfile(url):
        logger.debug(f"Reading local file: {url}")
        with open(url, "rb") as f:
            data = f.read()
        logger.debug(f"Read {len(data)} bytes from local file")
        return base64.b64encode(data).decode("utf-8")

    # Otherwise, treat as HTTP URL
    raw_url = (
        url if url.endswith((".png", ".jpg", ".jpeg", ".webp")) else url + "?raw=1"
    )
    logger.debug(f"Downloading from URL: {raw_url}")
    response = requests.get(raw_url, timeout=30)
    response.raise_for_status()

    logger.debug(f"Downloaded {len(response.content)} bytes")
    return base64.b64encode(response.content).decode("utf-8")


def _poll_for_result(
    api_url: str, prompt_id: str, output_dir: str, timeout: int = 600
) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        res = requests.get(f"{api_url}/history/{prompt_id}")
        if res.status_code == 200 and res.json():
            history = res.json()
            result_data = None
            for nid in history:
                outputs = history[nid].get("outputs", {})
                for node_output in outputs.values():
                    if "images" in node_output and node_output["images"]:
                        result_data = node_output
                        break
                if result_data:
                    break

            if result_data:
                img = result_data["images"][0]
                filename = img.get("filename")
                subfolder = img.get("subfolder", "")
                if subfolder:
                    subfolder = subfolder.split("/")[-1]
                img_type = img.get("type", "output")

                local_path = os.path.join(output_dir, filename)
                img_url = f"{api_url}/view?filename={filename}&type={img_type}&subfolder={subfolder}"

                img_res = requests.get(img_url)
                img_res.raise_for_status()

                with open(local_path, "wb") as f:
                    f.write(img_res.content)

                logger.info(f"Image saved to: {local_path}")
                return {
                    "status": "success",
                    "local_path": local_path,
                    "filename": filename,
                }

        time.sleep(2)

    raise TimeoutError("ComfyUI task timed out")


def _run_workflow(
    prompt: str,
    workflow_type: str,
    image_url: Optional[str] = None,
    width: int = 1024,
    height: int = 1024,
) -> str:
    logger.info(f"Running workflow: {workflow_type}")
    logger.debug(f"Prompt: {prompt[:100]}...")
    logger.debug(f"image_url: {image_url}")
    logger.debug(f"width: {width}, height: {height}")

    api_url = _load_env("COMFY_API_URL")
    output_dir = _load_env("COMFY_OUTPUT_DIR", "/tmp/comfyui_output")
    # Expand ~ to user's home directory
    output_dir = os.path.expanduser(output_dir)

    if not api_url:
        logger.error("COMFY_API_URL not configured")
        return json.dumps(
            {"status": "error", "message": "COMFY_API_URL not configured"}
        )

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    template_path = _get_template_path(workflow_type)
    if not template_path:
        logger.error(f"Template not found for workflow_type: {workflow_type}")
        return json.dumps(
            {
                "status": "error",
                "message": f"Template not found for workflow_type: {workflow_type}",
            }
        )

    workflow = _load_template(template_path)

    if workflow_type == "image_edit":
        if not image_url:
            logger.error("image_url is required for image_edit workflow")
            return json.dumps(
                {
                    "status": "error",
                    "message": "image_url is required for image_edit workflow",
                }
            )
        img_b64 = _download_image_as_base64(image_url)

        input_node = _get_node(workflow, workflow_type, "input_image")
        prompt_node = _get_node(workflow, workflow_type, "positive_prompt")
        latent_node = _get_node(workflow, workflow_type, "latent_height")

        if input_node is None or prompt_node is None or latent_node is None:
            return json.dumps(
                {"status": "error", "message": f"Required node not found in template for workflow_type: {workflow_type}"}
            )

        input_node["inputs"]["data"] = img_b64
        prompt_node["inputs"]["text"] = prompt
        latent_node["inputs"]["value"] = height

    elif workflow_type == "text_to_image":
        prompt_node = _get_node(workflow, workflow_type, "positive_prompt")
        latent_node = _get_node(workflow, workflow_type, "latent_size")

        if prompt_node is None or latent_node is None:
            return json.dumps(
                {"status": "error", "message": f"Required node not found in template for workflow_type: {workflow_type}"}
            )

        prompt_node["inputs"]["text"] = prompt
        latent_node["inputs"]["width"] = width
        latent_node["inputs"]["height"] = height

    else:
        return json.dumps(
            {"status": "error", "message": f"Unknown workflow_type: {workflow_type}"}
        )

    # Respect COMFY_TIMEOUT env var (default 600s)
    timeout = int(os.getenv("COMFY_TIMEOUT", "600"))

    payload = {"prompt": workflow}
    logger.debug(f"Sending prompt to ComfyUI: {api_url}/prompt")
    response = requests.post(f"{api_url}/prompt", json=payload)
    response.raise_for_status()

    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        logger.error("Failed to get prompt_id")
        return json.dumps({"status": "error", "message": "Failed to get prompt_id"})

    logger.info(f"Prompt submitted, prompt_id: {prompt_id}")
    result = _poll_for_result(api_url, prompt_id, output_dir, timeout=timeout)

    return json.dumps(
        {
            "status": "success",
            "message": "Image generated successfully",
            "image_path": result["local_path"],
            "filename": result["filename"],
        }
    )


# =============================================================================
# Hermes Plugin Schema & Handler
# =============================================================================

COMFYUI_WORKFLOW_SCHEMA = {
    "name": "comfyui_workflow",
    "description": "執行 ComfyUI workflow 進行圖片生成或編輯。適用於：1) 使用圖片+指令進行 AI 圖片編輯（如更換背景、調整顏色）；2) 純文字指令生成新圖片。生成圖片後，請在回覆中包含 MEDIA:<圖片路徑> 標籤（如 MEDIA:/tmp/comfyui_output/xxx.png）才能將圖片發送到 Discord。",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "生成或編輯圖片的指令。例如：'幫我把背景換成藍色的沙灘' 或 '一隻可愛的貓咪坐在草地上'",
            },
            "workflow_type": {
                "type": "string",
                "description": "要執行的 workflow 類型",
                "enum": ["image_edit", "text_to_image"],
                "default": "text_to_image",
            },
            "image_url": {
                "type": "string",
                "description": "圖片網址或本地路徑（image_edit 時需要）。例如：'https://example.com/image.png' 或 '/tmp/hermes/attachments/xxx.png'",
            },
            "width": {
                "type": "integer",
                "description": "生成圖片的寬度（pixels，預設 1024）",
                "default": 1024,
            },
            "height": {
                "type": "integer",
                "description": "生成圖片的高度（pixels，預設 1024）",
                "default": 1024,
            },
        },
        "required": ["prompt", "workflow_type"],
    },
}


def handle_comfyui_workflow(
    params: Dict[str, Any], task_id: str = None, **kwargs
) -> str:
    logger.info(f"handle_comfyui_workflow called with params: {params}")

    prompt = params.get("prompt", "")
    workflow_type = params.get("workflow_type", "text_to_image")
    image_url = params.get("image_url")
    width = params.get("width", 1024)
    height = params.get("height", 1024)

    logger.debug(
        f"Parsed - prompt: {prompt[:50]}..., workflow_type: {workflow_type}, image_url: {image_url}, width: {width}, height: {height}"
    )

    try:
        result = _run_workflow(
            prompt=prompt,
            workflow_type=workflow_type,
            image_url=image_url,
            width=width,
            height=height,
        )
        logger.info(f"Workflow completed, result: {result[:200]}...")
        return result
    except Exception as e:
        logger.exception(f"Exception in comfyui_workflow: {e}")
        return json.dumps({"status": "error", "message": str(e)})


def check_requirements() -> bool:
    """Return True only when COMFY_API_URL is configured."""
    return bool(os.getenv("COMFY_API_URL"))


def register(ctx):
    """Register the comfyui_workflow tool."""
    ctx.register_tool(
        "comfyui_workflow",
        "comfyui-workflow",  # toolset name
        COMFYUI_WORKFLOW_SCHEMA,
        handle_comfyui_workflow,
        check_fn=check_requirements,
    )
