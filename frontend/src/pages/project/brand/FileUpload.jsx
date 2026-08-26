import { useState, useRef } from "react";
import { UploadSimple, Image } from "@phosphor-icons/react";
import * as assetsApi from "../../../api/assets";
import Spinner from "../../../components/shared/Spinner";

export default function FileUpload({ label, currentUrl, onUpload, projectId }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await assetsApi.uploadAsset(projectId, file);
      onUpload(result.path);
    } catch (err) {
      console.error("Upload failed:", err);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div>
      <label className="block text-xs text-slate-500 mb-2">{label}</label>
      <div className="flex items-center gap-4">
        <div
          onClick={() => inputRef.current?.click()}
          className="w-16 h-16 rounded-lg bg-black border border-slate-700 flex items-center justify-center relative group cursor-pointer overflow-hidden"
        >
          {currentUrl ? (
            <img
              src={`/preview/${projectId}/assets/${currentUrl}`}
              alt={label}
              className="w-full h-full object-contain"
            />
          ) : (
            <Image className="text-slate-600" size={24} />
          )}
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
            {uploading ? (
              <Spinner size={16} />
            ) : (
              <UploadSimple className="text-white" size={20} />
            )}
          </div>
        </div>
        <div>
          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="text-xs text-brand-400 hover:text-brand-300 font-medium"
          >
            {uploading ? "Uploading..." : currentUrl ? "Replace" : "Upload"}
          </button>
          {currentUrl && (
            <p className="text-[10px] text-slate-600 font-mono mt-0.5 truncate max-w-[200px]">
              {currentUrl}
            </p>
          )}
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={handleFile}
        className="hidden"
      />
    </div>
  );
}
