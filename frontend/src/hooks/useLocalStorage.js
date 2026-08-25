import { useEffect, useState } from "react";

function revive(fallback, parsed) {
  if (Array.isArray(fallback)) {
    return Array.isArray(parsed) ? parsed : fallback;
  }
  if (fallback !== null && typeof fallback === "object") {
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { ...fallback, ...parsed };
    }
    return fallback;
  }
  return parsed === undefined || parsed === null ? fallback : parsed;
}

export default function useLocalStorage(key, fallback) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      return revive(fallback, JSON.parse(raw));
    } catch {
      return fallback;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // storage full or unavailable
    }
  }, [key, value]);

  return [value, setValue];
}
