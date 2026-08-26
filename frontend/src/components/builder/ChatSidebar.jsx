import { PencilSimple, Cursor, MagicWand } from "@phosphor-icons/react";
import ChatPanel from "../chat/ChatPanel";

/**
 * AgentSite-specific chat host — thin wrapper around the reusable
 * <ChatPanel> that renders the tweak-mode banner and forwards the
 * legacy prop names PageBuilderPage uses.
 *
 * To embed the chat elsewhere, compose <ChatPanel> with your own
 * streaming state — this wrapper carries AgentSite's edit-mode awareness.
 */
export default function ChatSidebar({
  messages,
  onSend,
  onSteer = null,
  generating,
  discoveryForm = null,
  todoStream = null,
  editMode = false,
  editSelection = null,
  editSelections = [],
  onCreateNewDesign = null,
}) {
  const banner = editMode ? (
    <EditModeBanner selection={editSelection} selections={editSelections} />
  ) : onCreateNewDesign && !discoveryForm ? (
    <CreateNewDesignButton onClick={onCreateNewDesign} />
  ) : null;

  return (
    <ChatPanel
      messages={messages}
      onSend={onSend}
      onSteer={onSteer}
      generating={generating}
      topBanner={banner}
      stickyForm={discoveryForm}
      belowMessages={todoStream}
    />
  );
}

function CreateNewDesignButton({ onClick }) {
  return (
    <div className="px-3 py-2 border-b border-slate-800/70">
      <button
        onClick={onClick}
        className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-gradient-to-r from-brand-500 to-purple-600 hover:from-brand-400 hover:to-purple-500 text-white text-xs font-semibold shadow-lg shadow-brand-500/20 transition-all"
        title="Open the discovery brief and start a fresh design"
      >
        <MagicWand size={13} weight="fill" />
        Create new design
      </button>
    </div>
  );
}

function EditModeBanner({ selection, selections }) {
  return (
    <div className="border-b-2 border-brand-500/60 bg-gradient-to-r from-brand-500/20 via-brand-500/10 to-purple-500/10 px-4 py-3">
      <div className="flex items-center gap-2 text-sm text-white font-semibold">
        <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-brand-500 shadow-lg shadow-brand-500/40">
          <PencilSimple size={11} weight="fill" className="text-white" />
        </span>
        <span>Tweak mode</span>
        <span className="text-[10px] font-mono uppercase tracking-wider text-brand-300/80 ml-auto px-1.5 py-0.5 bg-brand-500/20 rounded">
          no rebuild
        </span>
      </div>
      <div className="mt-1.5 text-[11px] text-brand-200/80 leading-snug">
        Chat here adjusts what you see. The agent can only{" "}
        <span className="font-mono text-brand-300">patch</span> /{" "}
        <span className="font-mono text-brand-300">find</span> /{" "}
        <span className="font-mono text-brand-300">insert blocks</span> — it
        will not rerun the PM → Designer → Developer pipeline.
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[11px] font-mono">
        <Cursor size={11} className="text-brand-300/70" />
        {selections && selections.length > 1 ? (
          <span className="text-purple-300 font-semibold">
            {selections.length} elements selected
          </span>
        ) : selection ? (
          <>
            <span className="text-brand-200">&lt;{selection.tag}&gt;</span>
            <span className="text-brand-300/50 truncate">{selection.id}</span>
          </>
        ) : (
          <span className="text-brand-300/50">
            click an element (shift-click for multi-select)
          </span>
        )}
      </div>
    </div>
  );
}
