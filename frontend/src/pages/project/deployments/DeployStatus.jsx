import StatusPill from "../../../components/ui/StatusPill";

const STATUS_MAP = {
  ready: { tone: "success", label: "Live" },
  building: { tone: "warning", label: "Building" },
  failed: { tone: "danger", label: "Failed" },
  queued: { tone: "neutral", label: "Queued" },
};

export default function DeployStatusPill({ status }) {
  const c = STATUS_MAP[status] || STATUS_MAP.queued;
  return (
    <StatusPill tone={c.tone} dot>
      {c.label}
    </StatusPill>
  );
}
