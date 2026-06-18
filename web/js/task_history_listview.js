import { app } from "../../../scripts/app.js";

const NODE_CLASS = "Seedance2TaskHistoryBrowser";
const LIST_WIDGET = "seedance_task_history_list";
const EXPIRED_PREVIEW_WIDGET = "seedance_task_history_expired_preview";
const BUILTIN_VIDEO_PREVIEW_WIDGET = "video-preview";
const BUILTIN_CANVAS_IMAGE_PREVIEW_WIDGET = "$$canvas-image-preview";
const LIST_HEIGHT = 206;
const HEADER_HEIGHT = 24;
const ROW_HEIGHT = 24;
const SCROLLBAR_HIT_WIDTH = 30;
const SCROLLBAR_WIDTH = 8;
const SCROLLBAR_BUTTON_HEIGHT = 18;

function widget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function setWidgetValue(node, name, value) {
    const w = widget(node, name);
    if (!w) {
        console.warn(`[Seedance2 Task Browser] Widget not found: ${name}`);
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
        console.warn(`[Seedance2 Task Browser] Widget callback failed for ${name}:`, err);
    }
    try {
        node.onWidgetChanged?.(name, value, w);
    } catch (err) {
        console.warn(`[Seedance2 Task Browser] onWidgetChanged failed for ${name}:`, err);
    }
}

function markDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

function messageValue(message, key) {
    if (!Object.prototype.hasOwnProperty.call(message || {}, key)) {
        return null;
    }
    return String(message?.[key]?.[0] ?? message?.[key] ?? "");
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
            console.warn("[Seedance2 Task Browser] Preview widget cleanup failed:", err);
        }
        try {
            w.element?.remove?.();
        } catch {
            // DOMWidget removal is best effort; splicing the widget is the important part.
        }
        node.widgets.splice(i, 1);
    }
}

function clearNativePreview(node) {
    removeWidgetWhere(node, (w) =>
        w.name === BUILTIN_VIDEO_PREVIEW_WIDGET ||
        w.name === BUILTIN_CANVAS_IMAGE_PREVIEW_WIDGET ||
        (w.type === "video" && String(w.name || "").includes("preview"))
    );
    try {
        node.videoContainer?.replaceChildren?.();
    } catch {
        // Keep cleanup best effort.
    }
    node.videoContainer = undefined;
    node.imgs = undefined;
    node.images = undefined;
    node.preview = undefined;
    node.animatedImages = undefined;
    node.imageIndex = null;
    node.overIndex = null;
    node.pointerDown = null;
}

function removeExpiredPreview(node) {
    removeWidgetWhere(node, (w) => w.name === EXPIRED_PREVIEW_WIDGET);
}

function buildExpiredPreview(taskId) {
    const box = document.createElement("div");
    box.style.cssText = [
        "box-sizing:border-box",
        "width:100%",
        "height:260px",
        "min-height:220px",
        "display:flex",
        "flex-direction:column",
        "align-items:center",
        "justify-content:center",
        "gap:14px",
        "border:1px solid #5a2329",
        "background:#1b0f12",
        "color:#ffd0d0",
        "font-family:Inter,Arial,sans-serif",
        "user-select:none",
    ].join(";");

    const cross = document.createElement("div");
    cross.textContent = "X";
    cross.style.cssText = [
        "width:128px",
        "height:128px",
        "display:flex",
        "align-items:center",
        "justify-content:center",
        "color:#ff5c5c",
        "font-size:128px",
        "font-weight:200",
        "line-height:1",
    ].join(";");

    const title = document.createElement("div");
    title.textContent = "EXPIRED - NO OUTPUT";
    title.style.cssText = "font-size:18px;font-weight:700;letter-spacing:0;color:#ffd0d0;";

    const detail = document.createElement("div");
    detail.textContent = taskId ? `task: ${taskId}` : "BytePlus removed the generated video.";
    detail.style.cssText = "max-width:92%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:#c98f96;";

    box.append(cross, title, detail);
    return box;
}

function showExpiredPreview(node, taskId) {
    clearNativePreview(node);
    removeExpiredPreview(node);
    if (typeof node.addDOMWidget !== "function") {
        markDirty(node);
        return;
    }
    const element = buildExpiredPreview(taskId);
    const w = node.addDOMWidget(EXPIRED_PREVIEW_WIDGET, "seedance-expired-preview", element, {
        hideOnZoom: false,
        canvasOnly: true,
    });
    w.serialize = false;
    w.serializeValue = () => undefined;
    w.computeLayoutSize = () => ({ minHeight: 260, minWidth: 320 });
    markDirty(node);
}

function applyPreviewState(node, message) {
    const expiredTaskId = messageValue(message, "task_preview_expired");
    if (expiredTaskId === null) {
        return;
    }
    if (expiredTaskId) {
        showExpiredPreview(node, expiredTaskId);
    } else {
        removeExpiredPreview(node);
    }
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

function parseItems(message) {
    const raw = message?.task_items_json?.[0] ?? message?.task_items_json;
    if (!raw) {
        return null;
    }
    try {
        const items = JSON.parse(raw);
        return Array.isArray(items) ? items : [];
    } catch (err) {
        console.warn("[Seedance2 Task Browser] Failed to parse item list:", err);
        return [];
    }
}

function selectedTaskIdFromMessage(message) {
    if (Object.prototype.hasOwnProperty.call(message || {}, "selected_task_id")) {
        return String(message?.selected_task_id?.[0] ?? message?.selected_task_id ?? "");
    }
    return null;
}

function selectItem(node, item) {
    if (!item) {
        return;
    }
    node.taskBrowserInternalUpdate = true;
    setWidgetValue(node, "selected_task_id", item.task_id || "");
    setWidgetValue(node, "selected_index", Number(item.index || 1));
    node.taskBrowserInternalUpdate = false;
    node.taskBrowserSelectedIndex = Number(item.index || 1);
    node.taskBrowserSelectedId = item.task_id || "";
    node.taskBrowserItems = (node.taskBrowserItems || []).map((candidate) => ({
        ...candidate,
        selected: candidate.task_id === item.task_id,
    }));
    markDirty(node);
}

function visibleCount(w) {
    return Math.max(1, Math.floor((LIST_HEIGHT - HEADER_HEIGHT) / ROW_HEIGHT));
}

function clampScroll(w) {
    const maxScroll = Math.max(0, (w.items?.length || 0) - visibleCount(w));
    w.scroll = Math.max(0, Math.min(w.scroll || 0, maxScroll));
}

function scrollBy(w, node, delta) {
    w.scroll = (w.scroll || 0) + delta;
    clampScroll(w);
    markDirty(node);
}

function canvasPointFromEvent(event) {
    if (typeof event?.canvasX === "number" && typeof event?.canvasY === "number") {
        return [event.canvasX, event.canvasY];
    }
    const graphCanvas = app.canvas;
    const canvas = graphCanvas?.canvas;
    const rect = canvas?.getBoundingClientRect?.();
    if (!rect || typeof event?.clientX !== "number" || typeof event?.clientY !== "number") {
        return null;
    }
    const canvasOffset = [event.clientX - rect.left, event.clientY - rect.top];
    if (graphCanvas?.ds?.convertCanvasToOffset) {
        return graphCanvas.ds.convertCanvasToOffset(canvasOffset);
    }
    const scale = graphCanvas?.ds?.scale || 1;
    const offset = graphCanvas?.ds?.offset || [0, 0];
    return [canvasOffset[0] / scale - offset[0], canvasOffset[1] / scale - offset[1]];
}

function widgetPointFromEvent(event, node, w) {
    const canvasPoint = canvasPointFromEvent(event);
    if (!canvasPoint || !node?.pos) {
        return null;
    }
    return {
        x: canvasPoint[0] - node.pos[0],
        y: canvasPoint[1] - node.pos[1] - (w.lastY || 0),
    };
}

function localPoint(event, pos, node, w) {
    let x = Array.isArray(pos) ? pos[0] : (event.canvasX ?? 0) - node.pos[0];
    let y = Array.isArray(pos) ? pos[1] - w.lastY : (event.canvasY ?? 0) - node.pos[1] - w.lastY;
    if ((y < 0 || y > LIST_HEIGHT) && Array.isArray(pos)) {
        y = pos[1];
    }
    return { x, y };
}

function setScrollFromLocalY(w, localY, dragOffset = 0) {
    const scrollbar = w.scrollbar;
    if (!scrollbar || scrollbar.maxScroll <= 0) {
        return;
    }
    const y = localY - scrollbar.trackY - dragOffset;
    const denom = Math.max(1, scrollbar.trackH - scrollbar.thumbH);
    w.scroll = Math.round((y / denom) * scrollbar.maxScroll);
    clampScroll(w);
}

function stopScrollbarDrag(w) {
    w.draggingScrollbar = false;
    if (w.scrollbarDragCleanup) {
        w.scrollbarDragCleanup();
        w.scrollbarDragCleanup = null;
    }
}

function startScrollbarDrag(w, node, event) {
    const scrollbar = w.scrollbar;
    if (!scrollbar || scrollbar.maxScroll <= 0 || typeof event?.clientY !== "number") {
        return;
    }
    stopScrollbarDrag(w);
    w.draggingScrollbar = true;
    w.dragStartClientY = event.clientY;
    w.dragStartScroll = w.scroll || 0;
    w.dragScale = app.canvas?.ds?.scale || 1;

    const move = (moveEvent) => {
        if (!w.draggingScrollbar || typeof moveEvent.clientY !== "number") {
            return;
        }
        const denom = Math.max(1, (scrollbar.trackH - scrollbar.thumbH) * (w.dragScale || 1));
        const delta = ((moveEvent.clientY - w.dragStartClientY) / denom) * scrollbar.maxScroll;
        w.scroll = Math.round(w.dragStartScroll + delta);
        clampScroll(w);
        stopEvent(moveEvent);
        markDirty(node);
    };

    const up = (upEvent) => {
        stopScrollbarDrag(w);
        stopEvent(upEvent);
        markDirty(node);
    };

    document.addEventListener("pointermove", move, true);
    document.addEventListener("mousemove", move, true);
    document.addEventListener("pointerup", up, true);
    document.addEventListener("mouseup", up, true);
    document.addEventListener("pointercancel", up, true);
    w.scrollbarDragCleanup = () => {
        document.removeEventListener("pointermove", move, true);
        document.removeEventListener("mousemove", move, true);
        document.removeEventListener("pointerup", up, true);
        document.removeEventListener("mouseup", up, true);
        document.removeEventListener("pointercancel", up, true);
    };
}

function drawTriangle(ctx, x, y, size, direction) {
    ctx.beginPath();
    if (direction === "up") {
        ctx.moveTo(x + size / 2, y);
        ctx.lineTo(x + size, y + size);
        ctx.lineTo(x, y + size);
    } else {
        ctx.moveTo(x, y);
        ctx.lineTo(x + size, y);
        ctx.lineTo(x + size / 2, y + size);
    }
    ctx.closePath();
    ctx.fill();
}

let wheelCaptureInstalled = false;

function installWheelCapture() {
    if (wheelCaptureInstalled) {
        return;
    }
    const canvas = app.canvas?.canvas;
    if (!canvas) {
        window.setTimeout(installWheelCapture, 500);
        return;
    }
    canvas.addEventListener("wheel", (event) => {
        const nodes = app.graph?._nodes || [];
        for (const node of nodes) {
            if (node.comfyClass !== NODE_CLASS && node.type !== NODE_CLASS) {
                continue;
            }
            const listWidget = widget(node, LIST_WIDGET);
            if (!listWidget || !listWidget.items?.length || !listWidget.lastWidth) {
                continue;
            }
            const point = widgetPointFromEvent(event, node, listWidget);
            if (!point) {
                continue;
            }
            const insideX = point.x >= 0 && point.x <= listWidget.lastWidth;
            const insideY = point.y >= 0 && point.y <= LIST_HEIGHT;
            if (!insideX || !insideY) {
                continue;
            }
            const maxScroll = Math.max(0, listWidget.items.length - visibleCount(listWidget));
            if (maxScroll <= 0) {
                stopEvent(event);
                return;
            }
            const delta = event.deltaY ?? -event.wheelDelta ?? event.detail ?? 0;
            const steps = Math.max(1, Math.round(Math.abs(delta) / 80));
            scrollBy(listWidget, node, delta > 0 ? steps : -steps);
            stopEvent(event);
            return;
        }
    }, { capture: true, passive: false });
    wheelCaptureInstalled = true;
}

function ensureListWidget(node) {
    if (widget(node, LIST_WIDGET)) {
        return;
    }
    node.taskBrowserItems ??= [];
    node.taskBrowserSelectedId ??= widget(node, "selected_task_id")?.value || "";

    const listWidget = {
        name: LIST_WIDGET,
        type: LIST_WIDGET,
        value: "",
        serialize: false,
        scroll: 0,
        items: node.taskBrowserItems,
        computeSize(width) {
            return [Math.max(width, 600), LIST_HEIGHT];
        },
        draw(ctx, node, width, y) {
            this.items = node.taskBrowserItems || [];
            clampScroll(this);
            this.lastY = y;
            this.lastWidth = width;

            const x = 12;
            const innerWidth = width - 24;
            const rowX = x + 1;
            const rowWidth = innerWidth - 2;
            const selectedId = widget(node, "selected_task_id")?.value || node.taskBrowserSelectedId || "";
            const selectedIndex = Number(widget(node, "selected_index")?.value || node.taskBrowserSelectedIndex || 0);

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
            ctx.fillText("BytePlus generation tasks", x + 8, y + 21);
            ctx.fillStyle = "#888";
            ctx.textAlign = "right";
            ctx.fillText(`${this.items.length} item(s)`, x + innerWidth - 8, y + 21);
            ctx.textAlign = "left";

            if (!this.items.length) {
                ctx.fillStyle = "#888";
                ctx.fillText("Run this node to load generation history.", x + 8, y + 58);
                ctx.restore();
                return;
            }

            const dateWidth = 178;
            const statusWidth = 74;
            const indexWidth = 34;
            const idWidth = 178;
            const detailsWidth = Math.max(120, rowWidth - dateWidth - statusWidth - indexWidth - idWidth - 28);
            const start = this.scroll || 0;
            const end = Math.min(this.items.length, start + visibleCount(this));

            for (let i = start; i < end; i++) {
                const item = this.items[i];
                const row = i - start;
                const rowY = y + HEADER_HEIGHT + row * ROW_HEIGHT + 5;
                const isSelected = selectedId
                    ? item.task_id === selectedId
                    : (selectedIndex ? Number(item.index) === selectedIndex : !!item.selected);
                const isExpired = !!item.expired ||
                    String(item.status || "").toLowerCase() === "expired" ||
                    String(item.created_at || "").toLowerCase().includes("(expired)");

                ctx.fillStyle = isSelected
                    ? (isExpired ? "#6b2630" : "#2f6fb2")
                    : (isExpired ? (row % 2 ? "#241416" : "#201214") : (row % 2 ? "#191919" : "#171717"));
                ctx.fillRect(rowX, rowY, rowWidth, ROW_HEIGHT);

                ctx.fillStyle = isSelected ? (isExpired ? "#ffe1e1" : "#fff") : (isExpired ? "#ff8a8a" : "#aaa");
                ctx.font = "12px sans-serif";
                ctx.fillText(String(item.index || i + 1).padStart(2, "0"), rowX + 8, rowY + 16);

                ctx.fillStyle = isSelected ? (isExpired ? "#ffe1e1" : "#fff") : (isExpired ? "#ff6b6b" : "#ddd");
                ctx.fillText(clipText(ctx, item.task_id || "", idWidth), rowX + indexWidth, rowY + 16);

                ctx.fillStyle = isSelected ? (isExpired ? "#ffd0d0" : "#eaf4ff") : (isExpired ? "#d96d6d" : "#999");
                ctx.fillText(clipText(ctx, item.status || "", statusWidth), rowX + indexWidth + idWidth + 8, rowY + 16);
                ctx.fillText(clipText(ctx, item.details || "", detailsWidth), rowX + indexWidth + idWidth + statusWidth + 14, rowY + 16);
                ctx.fillText(
                    clipText(ctx, item.created_at || "", dateWidth),
                    rowX + indexWidth + idWidth + statusWidth + detailsWidth + 20,
                    rowY + 16
                );
            }

            if (this.items.length > visibleCount(this)) {
                const barX = x + innerWidth - SCROLLBAR_HIT_WIDTH;
                const buttonX = x + innerWidth - SCROLLBAR_HIT_WIDTH + 7;
                const trackX = x + innerWidth - 13;
                const upY = y + HEADER_HEIGHT + 6;
                const downY = y + LIST_HEIGHT - 6 - SCROLLBAR_BUTTON_HEIGHT;
                const trackY = upY + SCROLLBAR_BUTTON_HEIGHT + 3;
                const trackH = Math.max(24, downY - trackY - 3);
                const thumbH = Math.max(22, trackH * visibleCount(this) / this.items.length);
                const maxScroll = this.items.length - visibleCount(this);
                const thumbY = trackY + (trackH - thumbH) * (this.scroll || 0) / Math.max(1, maxScroll);
                this.scrollbar = {
                    hitX: barX,
                    upY: upY - y,
                    downY: downY - y,
                    buttonH: SCROLLBAR_BUTTON_HEIGHT,
                    trackX,
                    trackY: trackY - y,
                    trackH,
                    thumbY: thumbY - y,
                    thumbH,
                    maxScroll,
                };
                ctx.fillStyle = "#242424";
                ctx.fillRect(barX, upY, SCROLLBAR_HIT_WIDTH - 2, SCROLLBAR_BUTTON_HEIGHT);
                ctx.fillRect(barX, downY, SCROLLBAR_HIT_WIDTH - 2, SCROLLBAR_BUTTON_HEIGHT);
                ctx.fillStyle = "#888";
                drawTriangle(ctx, buttonX, upY + 6, 7, "up");
                drawTriangle(ctx, buttonX, downY + 6, 7, "down");
                ctx.fillStyle = "#303030";
                ctx.fillRect(trackX, trackY, SCROLLBAR_WIDTH, trackH);
                ctx.fillStyle = "#888";
                ctx.fillRect(trackX, thumbY, SCROLLBAR_WIDTH, thumbH);
            } else {
                this.scrollbar = null;
            }

            ctx.restore();
        },
        mouse(event, pos, node) {
            this.items = node.taskBrowserItems || [];
            if (!this.items.length) {
                return false;
            }
            const eventType = event?.type || "";
            const { x: localX, y: localY } = localPoint(event, pos, node, this);

            if (this.draggingScrollbar && (eventType === "pointermove" || eventType === "mousemove" || eventType === "drag")) {
                setScrollFromLocalY(this, localY, this.scrollbarDragOffset || 0);
                stopEvent(event);
                markDirty(node);
                return true;
            }
            if (this.draggingScrollbar && (
                eventType === "pointerup" || eventType === "mouseup" ||
                eventType === "pointercancel" || eventType === "mouseleave"
            )) {
                stopScrollbarDrag(this);
                stopEvent(event);
                markDirty(node);
                return true;
            }
            if (eventType === "wheel" || eventType === "mousewheel" || eventType === "DOMMouseScroll") {
                const delta = event.deltaY ?? -event.wheelDelta ?? event.detail ?? 0;
                scrollBy(this, node, delta > 0 ? 1 : -1);
                stopEvent(event);
                return true;
            }
            if (eventType !== "pointerdown" && eventType !== "mousedown") {
                return false;
            }

            if (this.scrollbar && localX >= this.scrollbar.hitX) {
                if (localY >= this.scrollbar.upY && localY <= this.scrollbar.upY + this.scrollbar.buttonH) {
                    scrollBy(this, node, -1);
                    stopEvent(event);
                    return true;
                }
                if (localY >= this.scrollbar.downY && localY <= this.scrollbar.downY + this.scrollbar.buttonH) {
                    scrollBy(this, node, 1);
                    stopEvent(event);
                    return true;
                }
                const withinTrack = localY >= this.scrollbar.trackY &&
                    localY <= this.scrollbar.trackY + this.scrollbar.trackH;
                if (withinTrack) {
                    const onThumb = localY >= this.scrollbar.thumbY &&
                        localY <= this.scrollbar.thumbY + this.scrollbar.thumbH;
                    if (onThumb) {
                        this.scrollbarDragOffset = localY - this.scrollbar.thumbY;
                        startScrollbarDrag(this, node, event);
                    } else {
                        scrollBy(this, node, localY < this.scrollbar.thumbY ? -visibleCount(this) : visibleCount(this));
                    }
                    stopEvent(event);
                    markDirty(node);
                    return true;
                }
            }

            const row = Math.floor((localY - HEADER_HEIGHT - 5) / ROW_HEIGHT);
            if (row < 0 || row >= visibleCount(this)) {
                return false;
            }
            const item = this.items[(this.scroll || 0) + row];
            if (!item) {
                return false;
            }
            selectItem(node, item);
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
        node.taskBrowserItems = items;
    }
    const taskId = selectedTaskIdFromMessage(message);
    if (taskId !== null) {
        node.taskBrowserInternalUpdate = true;
        node.taskBrowserSelectedId = taskId;
        setWidgetValue(node, "selected_task_id", taskId);
        node.taskBrowserInternalUpdate = false;
    }
    const selectedIndex = String(message?.selected_index?.[0] ?? message?.selected_index ?? "");
    if (Object.prototype.hasOwnProperty.call(message || {}, "selected_index")) {
        node.taskBrowserInternalUpdate = true;
        setWidgetValue(node, "selected_index", selectedIndex ? Number(selectedIndex) : 1);
        node.taskBrowserInternalUpdate = false;
        node.taskBrowserSelectedIndex = selectedIndex ? Number(selectedIndex) : 1;
    }
    ensureListWidget(node);
    markDirty(node);
}

app.registerExtension({
    name: "seedance2.task.history.listview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeType.comfyClass !== NODE_CLASS && nodeData.name !== NODE_CLASS) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            ensureListWidget(this);
            installWheelCapture();
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            applyExecutionMessage(this, message || {});
            applyPreviewState(this, message || {});
        };

        const configure = nodeType.prototype.configure;
        nodeType.prototype.configure = function (data) {
            configure?.apply(this, arguments);
            ensureListWidget(this);
            installWheelCapture();
        };

        const onWidgetChanged = nodeType.prototype.onWidgetChanged;
        nodeType.prototype.onWidgetChanged = function (name, value, w) {
            onWidgetChanged?.apply(this, arguments);
            if (this.taskBrowserInternalUpdate) {
                return;
            }
            if (name === "selected_index") {
                const index = Number(value);
                const item = (this.taskBrowserItems || []).find((candidate) => Number(candidate.index) === index);
                this.taskBrowserInternalUpdate = true;
                setWidgetValue(this, "selected_task_id", item?.task_id || "");
                this.taskBrowserInternalUpdate = false;
                this.taskBrowserSelectedIndex = index;
                this.taskBrowserSelectedId = item?.task_id || "";
                this.taskBrowserItems = (this.taskBrowserItems || []).map((candidate) => ({
                    ...candidate,
                    selected: item ? candidate.task_id === item.task_id : false,
                }));
                markDirty(this);
            } else if (name === "selected_task_id") {
                this.taskBrowserSelectedId = String(value || "");
                markDirty(this);
            }
        };
    },
});
