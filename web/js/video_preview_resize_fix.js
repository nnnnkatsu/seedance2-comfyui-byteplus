import { app } from "../../../scripts/app.js";

const TARGET_NODE_CLASSES = new Set([
    "Seedance2S3BrowseReferenceVideos",
    "Seedance2S3UploadReferenceVideo",
    "Seedance2VideoPreview",
    "Seedance2VideoSaver",
]);

const PREVIEW_MIN_WIDTH_CAP = 180;
const PREVIEW_MIN_HEIGHT_CAP = 120;

function markDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

function rememberConstructorConstraints(nodeType) {
    if (nodeType.seedance2PreviewOriginalConstraints) {
        return;
    }

    nodeType.seedance2PreviewOriginalConstraints = {
        hasSize: Object.prototype.hasOwnProperty.call(nodeType, "size"),
        size: Array.isArray(nodeType.size) ? [...nodeType.size] : nodeType.size,
        minHeight: nodeType.min_height,
        minWidth: nodeType.min_width,
        minHeightCamel: nodeType.minHeight,
        minWidthCamel: nodeType.minWidth,
    };
}

function restoreConstructorConstraints(node) {
    const nodeType = node.constructor;
    const original = nodeType?.seedance2PreviewOriginalConstraints;
    if (!nodeType || !original) {
        return;
    }

    if (original.hasSize) {
        nodeType.size = Array.isArray(original.size) ? [...original.size] : original.size;
    } else if (Object.prototype.hasOwnProperty.call(nodeType, "size")) {
        delete nodeType.size;
    }

    nodeType.min_height = original.minHeight;
    nodeType.min_width = original.minWidth;
    nodeType.minHeight = original.minHeightCamel;
    nodeType.minWidth = original.minWidthCamel;
}

function clampLayoutSize(size) {
    if (!size || typeof size !== "object") {
        return size;
    }

    const next = { ...size };
    if (typeof next.minWidth === "number") {
        next.minWidth = Math.min(next.minWidth, PREVIEW_MIN_WIDTH_CAP);
    }
    if (typeof next.minHeight === "number") {
        next.minHeight = Math.min(next.minHeight, PREVIEW_MIN_HEIGHT_CAP);
    }
    return next;
}

function relaxPreviewWidget(widget) {
    if (!widget || widget.seedance2PreviewResizeRelaxed) {
        return;
    }

    if (typeof widget.computeLayoutSize === "function") {
        const original = widget.computeLayoutSize;
        widget.computeLayoutSize = function () {
            return clampLayoutSize(original.apply(this, arguments));
        };
        widget.seedance2PreviewResizeRelaxed = true;
    }
}

function relaxPreviewSizing(node) {
    restoreConstructorConstraints(node);
    for (const widget of node.widgets || []) {
        relaxPreviewWidget(widget);
    }
    markDirty(node);
}

function scheduleRelaxPreviewSizing(node) {
    relaxPreviewSizing(node);
    for (const delay of [50, 150, 300, 700, 1500, 3000]) {
        window.setTimeout(() => relaxPreviewSizing(node), delay);
    }
}

app.registerExtension({
    name: "seedance2.video.preview.resize.fix",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET_NODE_CLASSES.has(nodeType.comfyClass) && !TARGET_NODE_CLASSES.has(nodeData.name)) {
            return;
        }

        rememberConstructorConstraints(nodeType);

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            scheduleRelaxPreviewSizing(this);
        };

        const configure = nodeType.prototype.configure;
        nodeType.prototype.configure = function () {
            configure?.apply(this, arguments);
            scheduleRelaxPreviewSizing(this);
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function () {
            onExecuted?.apply(this, arguments);
            scheduleRelaxPreviewSizing(this);
        };
    },
});
