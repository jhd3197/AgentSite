import { useState } from "react";
import { Eye, EyeSlash, Trash } from "@phosphor-icons/react";

export default function EnvVarRow({ env, onUpdate, onRemove }) {
  const [show, setShow] = useState(false);
  return (
    <div className="grid grid-cols-[1fr_1fr_auto_auto] gap-2 items-center py-2 border-b border-slate-800/60 last:border-0">
      <input
        value={env.key}
        onChange={(e) => onUpdate({ ...env, key: e.target.value.toUpperCase() })}
        placeholder="VAR_NAME"
        className="bg-slate-950 border border-slate-800 text-white text-sm font-mono rounded-md py-1.5 px-2.5 focus:border-brand-500 focus:outline-none"
      />
      <input
        type={show ? "text" : "password"}
        value={env.value}
        onChange={(e) => onUpdate({ ...env, value: e.target.value })}
        placeholder="value"
        className="bg-slate-950 border border-slate-800 text-white text-sm font-mono rounded-md py-1.5 px-2.5 focus:border-brand-500 focus:outline-none"
      />
      <button onClick={() => setShow(!show)} className="p-1.5 text-slate-500 hover:text-white">
        {show ? <EyeSlash size={14} /> : <Eye size={14} />}
      </button>
      <button onClick={() => onRemove(env.key)} className="p-1.5 text-slate-600 hover:text-rose-400">
        <Trash size={14} />
      </button>
    </div>
  );
}
