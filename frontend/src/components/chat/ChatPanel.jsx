import { useEffect, useRef } from "react";
import ChatMessage from "../builder/ChatMessage";
import ChatInput from "../builder/ChatInput";
import BloubAvatar from "../shared/BloubAvatar";

/**
 * Presentational chat surface. Takes messages + send callback; renders
 * the conversation, optional sticky top form, empty state, and input.
 *
 * This component is intentionally framework-agnostic-ish: it knows about
 * the AgentSite message/role conventions but holds no streaming state.
 * Pair with `useChat` (hooks/useChat.js) for a self-contained
 * "drop-anywhere" chat, or wire your own state if you have richer needs
 * (e.g. AgentSite's PageBuilderPage that interleaves generation events).
 *
 * Props:
 *   - messages: ChatMessage[]
 *   - onSend({ text, image }): user submitted a message
 *   - onSteer?: optional secondary action (e.g. mid-build steering)
 *   - generating?: boolean — disables the input visually
 *   - topBanner?: ReactNode — sticky banner above messages (e.g. edit-mode)
 *   - stickyForm?: ReactNode — sticky form above messages (e.g. discovery survey)
 *   - belowMessages?: ReactNode — extra content under the last message (e.g. todo stream)
 *   - emptyState?: ReactNode — custom empty-state block
 *   - className?: outer aside class override
 *   - inputDisabledReason?: string — show a small hint instead of the input
 */
export default function ChatPanel({
  messages,
  onSend,
  onSteer = null,
  generating = false,
  topBanner = null,
  stickyForm = null,
  belowMessages = null,
  emptyState = null,
  className = "w-[420px] flex flex-col border-r border-slate-800 bg-slate-950 relative z-10 shadow-2xl",
  inputDisabledReason = null,
}) {
  const scrollRef = useRef(null);
  const formRef = useRef(null);

  useEffect(() => {
    // When a sticky form appears, scroll it into view instead of jumping
    // to the bottom (which buries the form below prior chat history).
    if (stickyForm && formRef.current) {
      formRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, generating, stickyForm]);

  return (
    <aside className={className}>
      {topBanner}

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-6">
        {messages.length === 0 && !generating && !stickyForm && (
          emptyState ?? <DefaultEmptyState />
        )}

        {stickyForm && (
          <div
            ref={formRef}
            className="sticky top-0 z-10 -mt-4 -mx-4 px-4 pt-4 pb-2 bg-slate-950 border-b border-slate-800"
          >
            {stickyForm}
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}

        {belowMessages}
      </div>

      {inputDisabledReason ? (
        <div className="px-4 py-3 border-t border-slate-800 text-xs text-slate-500 italic">
          {inputDisabledReason}
        </div>
      ) : (
        <ChatInput
          onSend={onSend}
          onSteer={onSteer}
          generating={generating}
          disabled={!!stickyForm}
        />
      )}
    </aside>
  );
}

function DefaultEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <div className="mb-3">
        <BloubAvatar size={88} state="idle" follow />
      </div>
      <h3 className="text-white font-medium mb-1">Start Building</h3>
      <p className="text-sm text-slate-500 max-w-[280px]">
        Describe what you want to create and the AI agents will build it for you.
      </p>
    </div>
  );
}
