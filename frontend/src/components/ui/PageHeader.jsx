import { Link } from "react-router-dom";
import { CaretRight } from "@phosphor-icons/react";

export default function PageHeader({ items }) {
  return (
    <div className="h-12 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md flex items-center px-8 z-20">
      <div className="flex items-center gap-2 text-sm">
        {items.map((item, i) => {
          const last = i === items.length - 1;
          const label =
            last ? (
              <span className="text-white font-medium">{item.label}</span>
            ) : item.to ? (
              <Link
                to={item.to}
                className="text-slate-400 hover:text-white transition-colors"
              >
                {item.label}
              </Link>
            ) : (
              <span className={i === 0 ? "text-slate-500" : "text-slate-400"}>
                {item.label}
              </span>
            );
          return (
            <span key={i} className="flex items-center gap-2">
              {label}
              {!last && <CaretRight className="text-slate-600" size={12} />}
            </span>
          );
        })}
      </div>
    </div>
  );
}
