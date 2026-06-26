import { app } from "../../../scripts/app.js";

const NODE_CLASS = "Seedance2BatchResultBrowser";
const LIST_WIDGET = "seedance_batch_result_list";
const NO_OUTPUT_WIDGET = "seedance_batch_no_output_preview";
const VIDEO_PREVIEW_WIDGET = "video-preview";
const CANVAS_IMAGE_PREVIEW_WIDGET = "$$canvas-image-preview";
const HEADER_HEIGHT = 24;
const ROW_HEIGHT = 24;
const MAX_ROWS = 10;
const LIST_HEIGHT = HEADER_HEIGHT + ROW_HEIGHT * MAX_ROWS + 10;

function widget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function setWidgetValue(node, name, value) {
    const w = widget(node, name);
    if (!w) {
        console.warn(`[Seedance2 Batch Browser] Widget not found: ${name}`);
        return;
    }
    w.value = value;
    if (w.inputEl && "value" in w.inputEl) {
        w.inputEl.value = value;
    }
    if (w.element && "value" in w.element) {
        w.element.value = value;
    }
    try {
        w.callback?.(value);
    } catch (err) {
        console.warn(`[Seedance2 Batch Browser] Widget callback failed for ${name}:`, err);
    }
    try {
        node.onWidgetChanged?.(name, value, w);
    } catch (err) {
        console.warn(`[Seedance2 Batch Browser] onWidgetChanged failed for ${name}:`, err);
    }
}

function markDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

function stopEvent(event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    event?.stopImmediatePropagation?.();
}

function clipText(ctx, text, maxWidth) {
    text = String(text ?? "");
    if (ctx.measureText(text).width <= maxWidth) {
        return text;
    }
    let lo = 0;
    let hi = text.length;
    while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (ctx.measureText(text.slice(0, mid) + "...").width <= maxWidth) {
            lo = mid;
        } else {
            hi = mid - 1;
        }
    }
    return text.slice(0, lo) + "...";
}

function messageValue(message, key) {
    if (!Object.prototype.hasOwnProperty.call(message || {}, key)) {
        return null;
    }
    return String(message?.[key]?.[0] ?? message?.[key] ?? "");
}

function parseItems(message) {
    const raw = message?.batch_items_json?.[0] ?? message?.batch_items_json;
    if (!raw) {
        return null;
    }
    try {
        const items = JSON.parse(raw);
        return Array.isArray(items) ? items : [];
    } catch (err) {
        console.warn("[Seedance2 Batch Browser] Failed to parse item list:", err);
        return [];
    }
}

function selectedRequestIdFromMessage(message) {
    return messageValue(message, "selected_request_id");
}

function selectItem(node, item) {
    if (!item) {
        return;
    }
    node.batchBrowserInternalUpdate = true;
    setWidgetValue(node, "selected_request_id", item.request_id || "");
    setWidgetValue(node, "selected_index", Number(item.index || 1));
    node.batchBrowserInternalUpdate = false;
    node.batchBrowserSelectedIndex = Number(item.index || 1);
    node.batchBrowserSelectedId = item.request_id || "";
    node.batchBrowserItems = (node.batchBrowserItems || []).map((candidate) => ({
        ...candidate,
        selected: candidate.index === item.index,
    }));
    markDirty(node);
}

function removeWidgetWhere(node, predicate) {
    if (!node.widgets?.length) {
        return;
    }
    for (let i = node.widgets.length - 1; i >= 0; i--) {
        const w = node.widgets[i];
        if (!predicate(w)) {
            continue;
        }
        try {
            w.onRemove?.();
        } catch (err) {
            console.warn("[Seedance2 Batch Browser] Preview cleanup failed:", err);
        }
        try {
            w.element?.remove?.();
        } catch {
            // Best effort cleanup.
        }
        node.widgets.splice(i, 1);
    }
}

function clearNativePreview(node) {
    removeWidgetWhere(node, (w) =>
        w.name === VIDEO_PREVIEW_WIDGET ||
        w.name === CANVAS_IMAGE_PREVIEW_WIDGET ||
        (w.type === "video" && String(w.name || "").includes("preview"))
    );
    try {
        node.videoContainer?.replaceChildren?.();
    } catch {
        // Best effort cleanup.
    }
    node.videoContainer = undefined;
    node.imgs = undefined;
    node.images = undefined;
    node.preview = undefined;
    node.animatedImages = undefined;
    node.imageIndex = null;
}

function removeNoOutputPreview(node) {
    removeWidgetWhere(node, (w) => w.name === NO_OUTPUT_WIDGET);
}

function buildNoOutputPreview(reason) {
    const box = document.createElement("div");
    box.style.cssText = [
        "box-sizing:border-box",
        "width:100%",
        "height:220px",
        "display:flex",
        "flex-direction:column",
        "align-items:center",
        "justify-content:center",
        "gap:12px",
        "border:1px solid #5a2329",
        "background:#1b0f12",
        "font-family:Inter,Arial,sans-serif",
        "user-select:none",
    ].join(";");

    const cross = document.createElement("div");
    cross.textContent = "X";
    cross.style.cssText = "color:#ff5c5c;font-size:112px;font-weight:200;line-height:1;";

    const title = document.createElement("div");
    title.textContent = "NO OUTPUT";
    title.style.cssText = "font-size:18px;font-weight:700;color:#ffd0d0;";

    const detail = document.createElement("div");
    detail.textContent = reason ? `item: ${reason}` : "Selected batch item has no video URL.";
    detail.style.cssText = "max-width:92%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:#c98f96;";

    box.append(cross, title, detail);
    return box;
}

function showNoOutputPreview(node, reason) {
    clearNativePreview(node);
    removeNoOutputPreview(node);
    if (typeof node.addDOMWidget !== "function") {
        markDirty(node);
        return;
    }
    const element = buildNoOutputPreview(reason);
    const w = node.addDOMWidget(NO_OUTPUT_WIDGET, "seedance-batch-no-output", element, {
        hideOnZoom: false,
        canvasOnly: true,
    });
    w.serialize = false;
    w.serializeValue = () => undefined;
    w.computeLayoutSize = () => ({ minHeight: 220, minWidth: 320 });
    markDirty(node);
}

function applyPreviewState(node, message) {
    const reason = messageValue(message, "batch_preview_no_output");
    if (reason === null) {
        return;
    }
    if (reason) {
        showNoOutputPreview(node, reason);
    } else {
        removeNoOutputPreview(node);
    }
}

function ensureListWidget(node) {
    if (widget(node, LIST_WIDGET)) {
        return;
    }
    node.batchBrowserItems ??= [];
    node.batchBrowserSelectedId ??= widget(node, "selected_request_id")?.value || "";

    const listWidget = {
        name: LIST_WIDGET,
        type: LIST_WIDGET,
        value: "",
        serialize: false,
        items: node.batchBrowserItems,
        computeSize(width) {
            return [Math.max(width, 640), LIST_HEIGHT];
        },
        draw(ctx, node, width, y) {
            this.items = node.batchBrowserItems || [];
            this.lastY = y;
            this.lastWidth = width;

            const x = 12;
            const innerWidth = width - 24;
            const rowX = x + 1;
            const rowWidth = innerWidth - 2;
            const selectedId = widget(node, "selected_request_id")?.value || node.batchBrowserSelectedId || "";
            const selectedIndex = Number(widget(node, "selected_index")?.value || node.batchBrowserSelectedIndex || 0);

            ctx.save();
            ctx.fillStyle = "#141414";
            ctx.strokeStyle = "#4a4a4a";
            ctx.lineWidth = 1;
            ctx.fillRect(x, y + 4, innerWidth, LIST_HEIGHT - 8);
            ctx.strokeRect(x, y + 4, innerWidth, LIST_HEIGHT - 8);

            ctx.fillStyle = "#222";
            ctx.fillRect(x + 1, y + 5, innerWidth - 2, HEADER_HEIGHT - 1);
            ctx.font = "12px sans-serif";
            ctx.fillStyle = "#bbb";
            ctx.fillText("Seedance batch results", x + 8, y + 21);
            ctx.fillStyle = "#888";
            ctx.textAlign = "right";
            ctx.fillText(`${this.items.length} item(s)`, x + innerWidth - 8, y + 21);
            ctx.textAlign = "left";

            if (!this.items.length) {
                ctx.fillStyle = "#888";
                ctx.fillText("Connect batch_json and run this node.", x + 8, y + 58);
                ctx.restore();
                return;
            }

            const indexWidth = 34;
            const seedWidth = 112;
            const statusWidth = 94;
            const idWidth = 196;
            const detailsWidth = Math.max(120, rowWidth - indexWidth - seedWidth - statusWidth - idWidth - 40);
            const count = Math.min(this.items.length, MAX_ROWS);

            for (let i = 0; i < count; i++) {
                const item = this.items[i];
                const rowY = y + HEADER_HEIGHT + i * ROW_HEIGHT + 5;
                const isSelected = selectedId
                    ? item.request_id === selectedId
                    : (selectedIndex ? Number(item.index) === selectedIndex : !!item.selected);
                const isSuccess = String(item.status || "").toLowerCase() === "succeeded" && item.video_url;
                const isFailed = !isSuccess && String(item.status || "").toLowerCase() !== "submitted";

                ctx.fillStyle = isSelected
                    ? (isFailed ? "#6b2630" : "#2f6fb2")
                    : (isFailed ? (i % 2 ? "#241416" : "#201214") : (i % 2 ? "#191919" : "#171717"));
                ctx.fillRect(rowX, rowY, rowWidth, ROW_HEIGHT);

                ctx.font = "12px sans-serif";
                ctx.fillStyle = isSelected ? "#fff" : (isFailed ? "#ff8a8a" : "#aaa");
                ctx.fillText(String(item.index || i + 1).padStart(2, "0"), rowX + 8, rowY + 16);
                ctx.fillText(clipText(String(item.seed ?? ""), seedWidth), rowX + indexWidth, rowY + 16);

                ctx.fillStyle = isSelected ? "#eaf4ff" : (isFailed ? "#d96d6d" : "#999");
                ctx.fillText(clipText(item.status || "", statusWidth), rowX + indexWidth + seedWidth, rowY + 16);

                ctx.fillStyle = isSelected ? "#fff" : (isFailed ? "#ff6b6b" : "#ddd");
                ctx.fillText(clipText(item.request_id || "", idWidth), rowX + indexWidth + seedWidth + statusWidth + 8, rowY + 16);

                ctx.fillStyle = isSelected ? "#eaf4ff" : (isFailed ? "#d96d6d" : "#999");
                ctx.fillText(
                    clipText(item.details || "", detailsWidth),
                    rowX + indexWidth + seedWidth + statusWidth + idWidth + 16,
                    rowY + 16
                );
            }
            ctx.restore();
        },
        mouse(event, pos, node) {
            this.items = node.batchBrowserItems || [];
            if (!this.items.length) {
                return false;
            }
            const eventType = event?.type || "";
            if (eventType !== "pointerdown" && eventType !== "mousedown") {
                return false;
            }
            const localY = Array.isArray(pos) ? pos[1] - this.lastY : (event.canvasY ?? 0) - node.pos[1] - this.lastY;
            const row = Math.floor((localY - HEADER_HEIGHT - 5) / ROW_HEIGHT);
            if (row < 0 || row >= Math.min(this.items.length, MAX_ROWS)) {
                return false;
            }
            selectItem(node, this.items[row]);
            stopEvent(event);
            return true;
        },
    };

    node.addCustomWidget(listWidget);
    if (node.size?.[0] < 640) {
        node.size[0] = 640;
    }
}

function applyExecutionMessage(node, message) {
    const items = parseItems(message);
    if (items) {
        node.batchBrowserItems = items;
    }
    const requestId = selectedRequestIdFromMessage(message);
    if (requestId !== null) {
        node.batchBrowserInternalUpdate = true;
        node.batchBrowserSelectedId = requestId;
        setWidgetValue(node, "selected_request_id", requestId);
        node.batchBrowserInternalUpdate = false;
    }
    const selectedIndex = String(message?.selected_index?.[0] ?? message?.selected_index ?? "");
    if (Object.prototype.hasOwnProperty.call(message || {}, "selected_index")) {
        node.batchBrowserInternalUpdate = true;
        setWidgetValue(node, "selected_index", selectedIndex ? Number(selectedIndex) : 1);
        node.batchBrowserInternalUpdate = false;
        node.batchBrowserSelectedIndex = selectedIndex ? Number(selectedIndex) : 1;
    }
    ensureListWidget(node);
    markDirty(node);
}

app.registerExtension({
    name: "seedance2.batch.result.listview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeType.comfyClass !== NODE_CLASS && nodeData.name !== NODE_CLASS) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            ensureListWidget(this);
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            applyExecutionMessage(this, message || {});
            applyPreviewState(this, message || {});
        };

        const configure = nodeType.prototype.configure;
        nodeType.prototype.configure = function () {
            configure?.apply(this, arguments);
            ensureListWidget(this);
        };

        const onWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name, value, w) {
            onWidgetChanged?.apply(this, arguments);
            if (this.batchBrowserInternalUpdate) {
                return;
            }
            if (name === "selected_index") {
                const index = Number(value);
                const item = (this.batchBrowserItems || []).find((candidate) => Number(candidate.index) === index);
                this.batchBrowserInternalUpdate = true;
                setWidgetValue(this, "selected_request_id", item?.request_id || "");
                this.batchBrowserInternalUpdate = false;
                this.batchBrowserSelectedIndex = index;
                this.batchBrowserSelectedId = item?.request_id || "";
                this.batchBrowserItems = (this.batchBrowserItems || []).map((candidate) => ({
                    ...candidate,
                    selected: item ? candidate.index === item.index : false,
                }));
                markDirty(this);
            } else if (name === "selected_request_id") {
                this.batchBrowserSelectedId = String(value || "");
                markDirty(this);
            }
        };
    },
});
