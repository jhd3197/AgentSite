// Block catalog + render — pure client-side, no backend round-trip needed.
// (Block definitions ship in the vendored htmlstudio package.)

import { BUILTIN_BLOCKS, BUILTIN_REGISTRY, renderBlock, renderBlockUpdate } from "htmlstudio";

export function listBlocks() {
  return BUILTIN_BLOCKS;
}

export function getBlock(id) {
  return BUILTIN_REGISTRY.get(id);
}

/** Render a block to HTML, ready for set-outer-html patching. */
export function render(blockId, config = {}, options = {}) {
  const def = BUILTIN_REGISTRY.get(blockId);
  if (!def) throw new Error(`Unknown block: ${blockId}`);
  return renderBlock(def, config, options);
}

/** Re-render an existing instance with new config (preserves instanceId). */
export function rerender(blockId, config, instanceId) {
  const def = BUILTIN_REGISTRY.get(blockId);
  if (!def) throw new Error(`Unknown block: ${blockId}`);
  return renderBlockUpdate(def, config, instanceId);
}
