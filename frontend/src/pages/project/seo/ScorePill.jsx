import StatusPill, { scoreTone } from "../../../components/ui/StatusPill";

export default function ScorePill({ score }) {
  return <StatusPill tone={scoreTone(score)}>{score}</StatusPill>;
}
