import { useEffect, useRef, useState } from "react";

export default function useFlash(duration = 1500) {
  const [on, setOn] = useState(false);
  const timerRef = useRef(null);

  const flash = () => {
    setOn(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setOn(false), duration);
  };

  useEffect(() => () => clearTimeout(timerRef.current), []);

  return [on, flash];
}
