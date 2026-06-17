import { app } from "../../../scripts/app.js";

const NODE_CLASS = "Seedance2VideoReferencePreview";

function widget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function setWidgetValue(node, name, value) {
    const w = widget(node, name);
    if (!w) {
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
    } catch {
        // Display-only update.
    }
    try {
        node.onWidgetChanged?.(name, value, w);
    } catch {
        // Display-only update.
    }
}

function valueFromMessage(message, name) {
    return String(message?.[name]?.[0] ?? message?.[name] ?? "");
}

function markDirty(node) {
    node.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
}

app.registerExtension({
    name: "seedance2.video_ref.inspector",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeType.comfyClass !== NODE_CLASS && nodeData.name !== NODE_CLASS) {
            return;
        }

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            setWidgetValue(this, "video_url", valueFromMessage(message, "video_url"));
            setWidgetValue(this, "s3_key", valueFromMessage(message, "s3_key"));
            markDirty(this);
        };
    },
});
