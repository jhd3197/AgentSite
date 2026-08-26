import { useState, useEffect } from "react";
import { Books, File } from "@phosphor-icons/react";
import * as projectsApi from "../../../api/projects";
import Spinner from "../../../components/shared/Spinner";
import Panel from "../../../components/ui/Panel";
import Accordion from "../../../components/ui/Accordion";

const DESCRIPTION =
  "Agent-generated guide files that persist across generations.";

function GuideCard({ filename, content }) {
  const [expanded, setExpanded] = useState(false);
  const isJson = filename.endsWith(".json");
  let displayContent = content;
  if (isJson) {
    try {
      displayContent = JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      // keep raw content
    }
  }

  return (
    <Accordion
      open={expanded}
      onToggle={() => setExpanded(!expanded)}
      icon={File}
      title={<span className="font-mono text-slate-300">{filename}</span>}
      contentClassName="px-4 py-3 max-h-96 overflow-auto"
    >
      <pre className="text-xs font-mono text-slate-400 whitespace-pre-wrap break-words">
        {displayContent}
      </pre>
    </Accordion>
  );
}

export default function KnowledgeBase({ projectId }) {
  const [guides, setGuides] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    projectsApi
      .fetchGuides(projectId)
      .then((data) => setGuides(data))
      .catch(() => setGuides(null))
      .finally(() => setLoading(false));
  }, [projectId]);

  const entries = guides ? Object.entries(guides) : [];

  if (loading) {
    return (
      <section>
        <h3 className="text-lg font-semibold text-white mb-1">Knowledge Base</h3>
        <p className="text-xs text-slate-500 mt-1 mb-5">{DESCRIPTION}</p>
        <div className="flex items-center justify-center py-8">
          <Spinner size={20} />
        </div>
      </section>
    );
  }

  if (entries.length === 0) {
    return (
      <section>
        <h3 className="text-lg font-semibold text-white mb-1">Knowledge Base</h3>
        <p className="text-xs text-slate-500 mt-1 mb-5">{DESCRIPTION}</p>
        <Panel className="p-6 text-center">
          <Books className="text-slate-600 mx-auto mb-3" size={32} />
          <p className="text-sm text-slate-500">
            No guide files yet — generate a page and agents will create
            design-system.md, architecture.md, style.json, and site-plan.json.
          </p>
        </Panel>
      </section>
    );
  }

  return (
    <section>
      <h3 className="text-lg font-semibold text-white mb-1">Knowledge Base</h3>
      <p className="text-xs text-slate-500 mt-1 mb-5">{DESCRIPTION}</p>
      <div className="space-y-2">
        {entries.map(([filename, content]) => (
          <GuideCard key={filename} filename={filename} content={content} />
        ))}
      </div>
    </section>
  );
}
