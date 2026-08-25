import { useParams } from "react-router-dom";
import useProject from "../../../hooks/useProject";
import PageHeader from "../../../components/ui/PageHeader";
import PageLoading from "../../../components/ui/PageLoading";
import BrandExtractor from "../../../components/project/BrandExtractor";
import DesignSystemPicker from "../../../components/project/DesignSystemPicker";
import MemoryPanel from "../../../components/project/MemoryPanel";
import BrandContent from "./BrandContent";
import KnowledgeBase from "./KnowledgeBase";

export default function BrandPage() {
  const { projectId } = useParams();
  const { project, loading, refresh } = useProject(projectId);

  if (loading) return <PageLoading />;

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader
        items={[
          { label: "Projects" },
          { label: project?.name || "...", to: `/project/${projectId}` },
          { label: "Brand" },
        ]}
      />

      <div className="p-8">
        <div className="max-w-4xl mx-auto">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-white">Brand</h1>
            <p className="text-sm text-slate-500 mt-1">
              Define the complete design system for your project — every generated page
              will follow these tokens.
            </p>
          </div>
          {project && <BrandContent project={project} refresh={refresh} />}

          {project && (
            <>
              <hr className="border-slate-800 my-10" />
              <div className="space-y-6">
                <BrandExtractor projectId={projectId} onExtracted={refresh} />
                <DesignSystemPicker
                  projectId={projectId}
                  currentId={project.style_spec?.inherits_from}
                  onPick={refresh}
                />
                <MemoryPanel projectId={projectId} />
              </div>
              <hr className="border-slate-800 my-10" />
              <KnowledgeBase projectId={projectId} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
